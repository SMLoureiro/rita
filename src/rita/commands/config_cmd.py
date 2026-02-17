"""Configuration management commands."""

from __future__ import annotations

import os
import shutil

import rich_click as click
import yaml
from rich.prompt import Prompt

from rita import console as con
from rita.argocd import parse_argocd_application
from rita.config import (
    CONFIG_FILE_NAME,
    RegistryConfig,
    fetch_secret_from_aws,
    find_config_file,
    generate_default_config,
    load_config,
    save_config,
)
from rita.repository import get_chart_path, get_repo_root
from rita.storage import (
    check_aws_credentials,
    create_storage_backend,
    get_default_branch,
    list_aws_profiles,
)


@click.group()
def config() -> None:
    """Manage rita configuration."""
    pass


@config.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing config file.")
def config_init(force: bool) -> None:
    """Initialize a new .rita.yaml configuration file."""
    repo_root = get_repo_root()
    config_path = repo_root / CONFIG_FILE_NAME

    if config_path.exists() and not force:
        click.echo(f"Config file already exists: {config_path}")
        click.echo("Use --force to overwrite.")
        return

    config_content = generate_default_config()

    with config_path.open("w", encoding="utf-8") as f:
        f.write(config_content)

    click.echo(f"✓ Created {config_path}")
    click.echo()
    click.echo("Default configuration:")
    click.echo(config_content)


@config.command("show")
def config_show() -> None:
    """Show current configuration."""
    config_path = find_config_file()
    cfg = load_config(config_path)

    if config_path:
        click.echo(f"Config file: {config_path}")
    else:
        click.echo("Config file: (using defaults)")
    click.echo()

    click.echo(yaml.safe_dump(cfg.to_dict(), default_flow_style=False, sort_keys=False))


@config.command("setup")
def config_setup() -> None:
    """Interactive setup for local development."""
    repo_root = get_repo_root()
    template_path = repo_root / ".rita.template.yaml"
    config_path = repo_root / CONFIG_FILE_NAME

    if not template_path.exists():
        con.print_error("Template file not found: .rita.template.yaml")
        con.print_hint("The template file should be committed to the repository.")
        raise SystemExit(1)

    if not config_path.exists():
        shutil.copy(template_path, config_path)
        con.print_success(f"Created {CONFIG_FILE_NAME} from template")
    else:
        con.print_info(f"Updating existing config: {config_path}")

    cfg = load_config(config_path)

    con.console.print()
    con.print_header("Local Development Setup")
    con.console.print()
    con.console.print("Configure your AWS SSO profile for local development.")
    con.console.print("[dim]Other settings come from the template.[/dim]")
    con.console.print()

    if cfg.render.storage:
        con.print_key_value("S3 Bucket", cfg.render.storage.s3_bucket or "(not set)")
        con.print_key_value(
            "S3 Prefix", cfg.render.storage.s3_prefix or "rendered-manifests"
        )
        con.print_key_value("AWS Region", cfg.render.storage.aws_region or "(not set)")
        con.console.print()

    con.console.print("[bold]AWS SSO Profile[/bold]")
    con.console.print()

    profiles = list_aws_profiles()

    if profiles:
        con.console.print("Available AWS profiles:")
        for i, profile in enumerate(profiles, 1):
            con.console.print(f"  [cyan]{i:2}[/cyan]. {profile}")
        con.console.print()

    default_profile = ""
    if cfg.render.storage and cfg.render.storage.aws_profile:
        default_profile = cfg.render.storage.aws_profile

    while True:
        user_input = Prompt.ask(
            "AWS SSO profile name (or number)",
            default=default_profile if default_profile else None,
        )

        if not user_input:
            con.print_warning("Profile name cannot be empty.")
            continue

        try:
            idx = int(user_input)
            if profiles and 1 <= idx <= len(profiles):
                aws_profile = profiles[idx - 1]
                con.print_info(f"Selected: {aws_profile}")
                break
            else:
                con.print_warning(
                    f"Invalid number. Enter 1-{len(profiles)} or a profile name."
                )
                continue
        except ValueError:
            pass

        if profiles and user_input in profiles:
            aws_profile = user_input
            break
        elif profiles:
            con.print_warning(
                f"Profile '{user_input}' not found in available profiles."
            )
            con.print_hint("Enter a number or exact profile name from the list above.")
            continue
        else:
            aws_profile = user_input
            break

    con.console.print()
    con.console.print("[bold]Compare Branch[/bold]")
    con.console.print(
        "[dim]The branch to compare against when running 'rita render diff'[/dim]"
    )

    default_branch = get_default_branch()

    compare_branch = Prompt.ask(
        "Default branch to compare against",
        default=cfg.render.compare_branch or default_branch,
    )

    if cfg.render.storage:
        cfg.render.storage.aws_profile = aws_profile
    cfg.render.compare_branch = compare_branch

    con.console.print()
    con.console.print("[bold]Docker Hub Credentials[/bold]")
    con.console.print("[dim]Required for pulling charts from docker.io.[/dim]")
    con.console.print()

    docker_registry = next(
        (r for r in cfg.registries if "docker" in r.url.lower()), None
    )

    if docker_registry:
        if docker_registry.aws_secret_name:
            con.print_success(
                f"Docker credentials configured via AWS Secrets Manager: {docker_registry.aws_secret_name}"
            )
        elif docker_registry.username:
            con.print_success("Docker credentials already configured")
        else:
            con.print_warning("Docker registry configured but no credentials set")
    else:
        con.print_info("Docker Hub credentials not configured")

    con.console.print()
    con.console.print("How would you like to configure Docker Hub credentials?")
    con.console.print("  [cyan]1[/cyan]. Use AWS Secrets Manager (recommended)")
    con.console.print("  [cyan]2[/cyan]. Enter credentials manually")
    con.console.print("  [cyan]3[/cyan]. Skip (no Docker Hub auth)")
    con.console.print()

    docker_choice = Prompt.ask(
        "Select option",
        choices=["1", "2", "3"],
        default="3" if docker_registry else "1",
    )

    if docker_choice == "1":
        default_secret = "ecr-pullthroughcache/dockerhub"
        secret_name = Prompt.ask(
            "AWS Secrets Manager secret name",
            default=docker_registry.aws_secret_name
            if docker_registry and docker_registry.aws_secret_name
            else default_secret,
        )

        con.console.print()
        con.console.print("[bold]Verifying secret access...[/bold]")

        region = cfg.render.storage.aws_region if cfg.render.storage else None
        secret_data = fetch_secret_from_aws(secret_name, region, aws_profile)

        if secret_data and "username" in secret_data and "password" in secret_data:
            con.print_success(
                "Successfully accessed Docker Hub credentials from AWS Secrets Manager"
            )
            if docker_registry:
                docker_registry.aws_secret_name = secret_name
                docker_registry.username = None
                docker_registry.password = None
            else:
                cfg.registries.append(
                    RegistryConfig(url="docker.io", aws_secret_name=secret_name)
                )
        else:
            con.print_warning(
                "Could not access secret or missing username/password keys"
            )
            con.print_hint(
                f"Ensure the secret '{secret_name}' exists and contains 'username' and 'password' keys"
            )
            if docker_registry:
                docker_registry.aws_secret_name = secret_name
                docker_registry.username = None
                docker_registry.password = None
            else:
                cfg.registries.append(
                    RegistryConfig(url="docker.io", aws_secret_name=secret_name)
                )

    elif docker_choice == "2":
        con.console.print()
        con.console.print(
            "[yellow]⚠ Credentials will be stored in .rita.yaml (gitignored)[/yellow]"
        )
        con.console.print(
            "[dim]Consider using AWS Secrets Manager for better security.[/dim]"
        )
        con.console.print()

        docker_username = Prompt.ask("Docker Hub username")
        docker_password = Prompt.ask("Docker Hub password/token", password=True)

        if docker_username and docker_password:
            if docker_registry:
                docker_registry.username = docker_username
                docker_registry.password = docker_password
                docker_registry.aws_secret_name = None
            else:
                cfg.registries.append(
                    RegistryConfig(
                        url="docker.io",
                        username=docker_username,
                        password=docker_password,
                    )
                )
            con.print_success("Docker credentials configured")
        else:
            con.print_warning("Skipping - empty username or password")

    else:
        con.print_info("Skipping Docker Hub credentials configuration")

    save_config(cfg, config_path)

    con.console.print()
    con.print_success(f"Configuration saved to {config_path}")
    con.console.print()

    con.print_header("Configuration Summary")
    if cfg.render.storage:
        con.print_key_value("S3 bucket", cfg.render.storage.s3_bucket or "(not set)")
        con.print_key_value(
            "S3 prefix", cfg.render.storage.s3_prefix or "rendered-manifests"
        )
        con.print_key_value("AWS region", cfg.render.storage.aws_region or "(not set)")
    con.print_key_value("AWS profile", aws_profile)
    con.print_key_value("Compare branch", compare_branch)
    con.console.print()

    con.console.print("[bold]Validating AWS credentials...[/bold]")
    success, message = check_aws_credentials(aws_profile)

    if success:
        con.print_success(message)

        con.console.print()
        con.console.print("[bold]Checking S3 bucket access...[/bold]")
        try:
            backend = create_storage_backend(cfg)
            backend.list_manifests()
            bucket_name = (
                cfg.render.storage.s3_bucket if cfg.render.storage else "unknown"
            )
            con.print_success(f"Successfully accessed bucket: {bucket_name}")
        except Exception as e:
            con.print_warning(f"Could not access S3 bucket: {e}")
            con.print_hint(
                f"Ensure you're logged in: aws sso login --profile {aws_profile}"
            )
    else:
        con.print_warning(message)
        con.print_hint(f"Run: aws sso login --profile {aws_profile}")

    con.console.print()

    con.console.print("[bold]Next steps:[/bold]")
    if not success:
        con.console.print(
            f"  1. Log in to AWS: [cyan]aws sso login --profile {aws_profile}[/cyan]"
        )
        con.console.print(
            "  2. Render baseline manifests: [cyan]rita render apply --all-envs[/cyan]"
        )
        con.console.print("  3. Push to S3: [cyan]rita render push --all-envs[/cyan]")
    else:
        con.console.print(
            "  1. Render baseline manifests: [cyan]rita render apply --all-envs[/cyan]"
        )
        con.console.print("  2. Push to S3: [cyan]rita render push --all-envs[/cyan]")
        con.console.print("  3. View diffs: [cyan]rita render diff[/cyan]")


@config.command("check")
def config_check() -> None:
    """Check if S3 storage is properly configured and accessible."""
    cfg = load_config()

    con.print_header("Storage Configuration Check")
    con.console.print()

    if not cfg.render.storage or cfg.render.storage.type != "s3":
        con.print_warning("S3 storage is not configured.")
        con.print_hint("Run: rita config setup")
        return

    storage = cfg.render.storage

    con.print_key_value("Storage type", storage.type)
    con.print_key_value("S3 bucket", storage.s3_bucket or "(not set)")
    con.print_key_value("S3 prefix", storage.s3_prefix)
    con.print_key_value("AWS profile", storage.aws_profile or "(not set)")
    con.print_key_value("AWS region", storage.aws_region or "(not set)")
    con.console.print()
    con.console.print("[bold]Checking AWS credentials...[/bold]")

    profile = None
    if not os.environ.get("CI") and not os.environ.get("GITHUB_ACTIONS"):
        profile = storage.aws_profile

    success, message = check_aws_credentials(profile)

    if success:
        con.print_success(message)
    else:
        con.print_error(message)
        if profile:
            con.print_hint(f"Run: aws sso login --profile {profile}")
        return

    con.console.print()
    con.console.print("[bold]Checking S3 bucket access...[/bold]")

    try:
        backend = create_storage_backend(cfg)
        backend.list_manifests()
        con.print_success(f"Successfully accessed bucket: {storage.s3_bucket}")
    except Exception as e:
        con.print_error(f"Failed to access bucket: {e}")
        return

    con.console.print()
    con.print_success("All checks passed!")


@config.command("discover")
@click.option(
    "--path",
    "-p",
    "search_path",
    default=".",
    help="Path to search for ArgoCD applications.",
)
def config_discover(search_path: str) -> None:
    """Discover ArgoCD applications in a path."""
    repo_root = get_repo_root()
    search_dir = repo_root / search_path

    if not search_dir.exists():
        click.echo(f"Error: Path does not exist: {search_dir}", err=True)
        raise SystemExit(1)

    click.echo(f"Searching for ArgoCD Applications in: {search_dir}")
    click.echo()

    found_apps = []
    for yaml_file in search_dir.rglob("*.yaml"):
        app = parse_argocd_application(yaml_file, chart_path_resolver=get_chart_path)
        if app:
            found_apps.append((yaml_file, app))

    for yml_file in search_dir.rglob("*.yml"):
        app = parse_argocd_application(yml_file, chart_path_resolver=get_chart_path)
        if app:
            found_apps.append((yml_file, app))

    if not found_apps:
        click.echo("No ArgoCD Applications found.")
        return

    click.echo(f"Found {len(found_apps)} ArgoCD Applications:")
    click.echo()

    for file_path, app in sorted(found_apps, key=lambda x: x[1].name):
        rel_path = file_path.relative_to(repo_root)
        local_marker = "📦" if app.is_local_chart else "🌐"
        click.echo(f"  {local_marker} {app.name}")
        click.echo(f"      File: {rel_path}")
        click.echo(f"      Chart: {app.chart_name}@{app.chart_version}")
        click.echo()
