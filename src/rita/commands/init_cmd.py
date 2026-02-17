"""Interactive initialization command for rita.

Creates a new .rita.yaml configuration file with interactive prompts.
"""

from __future__ import annotations
from pathlib import Path

import rich_click as click
from rich.prompt import Confirm, Prompt

from rita import console as con
from rita.config import (
    CONFIG_FILE_NAME,
    ChartConfig,
    ChartTestConfig,
    EnvironmentConfig,
    RegistryConfig,
    RenderConfig,
    RitaConfig,
    StorageConfig,
    save_config,
)
from rita.repository import get_repo_root
from rita.storage import list_aws_profiles


def _prompt_charts_config() -> ChartConfig:
    """Interactively configure charts settings."""
    con.print_header("Charts Configuration")
    con.console.print()
    con.console.print(
        "Configure where your Helm charts are located and how they are published."
    )
    con.console.print()

    
    con.console.print("[bold]Charts Directory[/bold]")
    con.console.print(
        "[dim]The local directory containing your Helm charts (relative to repo root).[/dim]"
    )
    con.console.print()

    charts_path: str = Prompt.ask(
        "Charts directory path",
        default="charts",
    )

    con.console.print()

    
    con.console.print("[bold]OCI Registry[/bold]")
    con.console.print(
        "[dim]The default OCI registry for publishing/pulling charts.[/dim]"
    )
    con.console.print("[dim]Examples: ghcr.io/myorg, docker.io/myuser, registry.example.com[/dim]")
    con.console.print()

    registry: str = Prompt.ask(
        "Default OCI registry",
        default="ghcr.io/myorg",
    )

    return ChartConfig(path=charts_path, registry=registry)


def _prompt_environments() -> list[EnvironmentConfig]:
    """Interactively configure environments."""
    con.print_header("Environments Configuration")
    con.console.print()
    con.console.print(
        "Configure the environments where your ArgoCD applications are deployed."
    )
    con.console.print(
        "[dim]Each environment has paths where ArgoCD application manifests are located.[/dim]"
    )
    con.console.print()

    environments: list[EnvironmentConfig] = []

    
    use_defaults: bool = Confirm.ask(
        "Use default environments (dev, prod)?",
        default=True,
    )

    if use_defaults:
        con.console.print()
        con.console.print("[bold]Development Environment[/bold]")
        dev_path = Prompt.ask(
            "Dev ArgoCD applications path",
            default="kubernetes/argocd/applications/dev/templates",
        )

        environments.append(
            EnvironmentConfig(
                name="dev",
                paths=[dev_path],
                aliases=["development", "staging"],
            )
        )

        con.console.print()
        con.console.print("[bold]Production Environment[/bold]")
        prod_path = Prompt.ask(
            "Prod ArgoCD applications path",
            default="kubernetes/argocd/applications/prod/templates",
        )

        environments.append(
            EnvironmentConfig(
                name="prod",
                paths=[prod_path],
                aliases=["production"],
            )
        )
    else:
        con.console.print()
        while True:
            con.console.print("[bold]Add Environment[/bold]")

            env_name: str = Prompt.ask("Environment name (e.g., dev, staging, prod)")

            if not env_name:
                break

            env_path: str = Prompt.ask(
                f"ArgoCD applications path for {env_name}",
                default=f"kubernetes/argocd/applications/{env_name}/templates",
            )

            aliases_str: str = Prompt.ask(
                f"Aliases for {env_name} (comma-separated, optional)",
                default="",
            )
            aliases = (
                [a.strip() for a in aliases_str.split(",") if a.strip()]
                if aliases_str
                else []
            )

            environments.append(
                EnvironmentConfig(
                    name=env_name,
                    paths=[env_path],
                    aliases=aliases,
                )
            )

            con.console.print()
            if not Confirm.ask("Add another environment?", default=False):
                break

    return environments


def _prompt_storage_config() -> StorageConfig | None:
    """Interactively configure storage settings."""
    con.print_header("Storage Configuration")
    con.console.print()
    con.console.print("Configure how rendered manifests are stored.")
    con.console.print(
        "[dim]Storage options enable diffing against baselines and sharing across team members.[/dim]"
    )
    con.console.print()

    con.console.print("[bold]Storage Backend[/bold]")
    con.console.print()
    con.console.print("  [cyan]1[/cyan]. Local filesystem (simple, no setup required)")
    con.console.print("  [cyan]2[/cyan]. AWS S3 (recommended for teams)")
    con.console.print("  [cyan]3[/cyan]. S3-compatible storage (Garage, MinIO, etc.)")
    con.console.print()

    storage_choice = Prompt.ask(
        "Select storage backend",
        choices=["1", "2", "3"],
        default="1",
    )

    if storage_choice == "1":
        
        return None

    con.console.print()

    if storage_choice == "2":
        
        return _prompt_aws_s3_config()
    else:
        
        return _prompt_s3_compatible_config()


def _prompt_aws_s3_config() -> StorageConfig:
    """Configure AWS S3 storage."""
    con.console.print("[bold]AWS S3 Configuration[/bold]")
    con.console.print()

    bucket: str = Prompt.ask("S3 bucket name")

    prefix: str = Prompt.ask(
        "S3 key prefix for manifests",
        default="rendered-manifests",
    )

    region: str = Prompt.ask(
        "AWS region",
        default="us-east-1",
    )

    con.console.print()

    
    profiles = list_aws_profiles()
    profile = None

    if profiles:
        con.console.print("[bold]AWS Authentication[/bold]")
        con.console.print("[dim]For local development, you can use an AWS SSO profile.[/dim]")
        con.console.print()
        con.console.print("Available AWS profiles:")
        for i, p in enumerate(profiles, 1):
            con.console.print(f"  [cyan]{i:2}[/cyan]. {p}")
        con.console.print()

        use_profile = Confirm.ask(
            "Configure an AWS profile for local development?",
            default=True,
        )

        if use_profile:
            profile_input = Prompt.ask(
                "AWS profile name (or number from list)",
                default="",
            )

            if profile_input:
                try:
                    idx = int(profile_input)
                    if 1 <= idx <= len(profiles):
                        profile = profiles[idx - 1]
                except ValueError:
                    profile = profile_input

    return StorageConfig(
        type="s3",
        s3_bucket=bucket,
        s3_prefix=prefix,
        aws_region=region,
        aws_profile=profile,
    )


def _prompt_s3_compatible_config() -> StorageConfig:
    """Configure S3-compatible storage (Garage, MinIO, etc.)."""
    con.console.print("[bold]S3-Compatible Storage Configuration[/bold]")
    con.console.print()
    con.console.print(
        "[dim]Supported backends: Garage, MinIO, DigitalOcean Spaces, Backblaze B2, etc.[/dim]"
    )
    con.console.print()

    
    con.console.print("  [cyan]1[/cyan]. Garage")
    con.console.print("  [cyan]2[/cyan]. MinIO")
    con.console.print("  [cyan]3[/cyan]. DigitalOcean Spaces")
    con.console.print("  [cyan]4[/cyan]. Backblaze B2")
    con.console.print("  [cyan]5[/cyan]. Other S3-compatible")
    con.console.print()

    provider = Prompt.ask(
        "Select provider",
        choices=["1", "2", "3", "4", "5"],
        default="1",
    )

    provider_hints = {
        "1": ("Garage", "http://localhost:3900", "garage"),
        "2": ("MinIO", "http://localhost:9000", "minio"),
        "3": ("DigitalOcean Spaces", "https://nyc3.digitaloceanspaces.com", "do-spaces"),
        "4": ("Backblaze B2", "https://s3.us-west-001.backblazeb2.com", "b2"),
        "5": ("S3-compatible", "http://localhost:9000", "s3-compatible"),
    }

    provider_name, default_endpoint, _ = provider_hints[provider]

    con.console.print()
    con.console.print(f"[bold]{provider_name} Configuration[/bold]")
    con.console.print()

    endpoint = Prompt.ask(
        "S3 endpoint URL",
        default=default_endpoint,
    )

    bucket: str = Prompt.ask("Bucket name")

    prefix: str = Prompt.ask(
        "Key prefix for manifests",
        default="rendered-manifests",
    )

    con.console.print()
    con.console.print("[bold]Credentials[/bold]")
    con.console.print(
        "[dim]You can set credentials via environment variables (recommended).[/dim]"
    )
    con.console.print()
    con.console.print("  Environment variables:")
    con.console.print("    [cyan]AWS_ACCESS_KEY_ID[/cyan] - Access key")
    con.console.print("    [cyan]AWS_SECRET_ACCESS_KEY[/cyan] - Secret key")
    con.console.print()

    return StorageConfig(
        type="s3",
        s3_bucket=bucket,
        s3_prefix=prefix,
        
        aws_region="auto",
        
        aws_profile=None,
        
        s3_endpoint=endpoint,
    )


def _prompt_render_config(storage: StorageConfig | None) -> RenderConfig:
    """Configure render settings."""
    con.print_header("Render Configuration")
    con.console.print()

    output_path: str = Prompt.ask(
        "Local output path for rendered manifests",
        default="rendered",
    )

    local_charts_only: bool = Confirm.ask(
        "Only render applications using local charts by default?",
        default=True,
    )

    compare_branch: str = Prompt.ask(
        "Default branch to compare against when diffing",
        default="main",
    )

    return RenderConfig(
        output_path=output_path,
        local_charts_only=local_charts_only,
        storage=storage,
        compare_branch=compare_branch,
    )


def _prompt_registries() -> list[RegistryConfig]:
    """Interactively configure OCI registry authentication."""
    con.print_header("Registry Authentication")
    con.console.print()
    con.console.print(
        "Configure authentication for OCI registries used by your charts."
    )
    con.console.print(
        "[dim]Credentials can be stored as environment variable references for security.[/dim]"
    )
    con.console.print()

    registries: list[RegistryConfig] = []

    if not Confirm.ask("Configure registry authentication?", default=False):
        return registries

    while True:
        con.console.print()
        con.console.print("[bold]Add Registry[/bold]")
        con.console.print()
        con.console.print("Common registries:")
        con.console.print("  [cyan]1[/cyan]. Docker Hub (docker.io)")
        con.console.print("  [cyan]2[/cyan]. GitHub Container Registry (ghcr.io)")
        con.console.print("  [cyan]3[/cyan]. AWS ECR")
        con.console.print("  [cyan]4[/cyan]. Google Artifact Registry")
        con.console.print("  [cyan]5[/cyan]. Other")
        con.console.print()

        registry_choice = Prompt.ask(
            "Select registry",
            choices=["1", "2", "3", "4", "5"],
            default="1",
        )

        registry_urls = {
            "1": "docker.io",
            "2": "ghcr.io",
            "3": "ecr.aws",
            "4": "gcr.io",
            "5": "",
        }

        url = registry_urls[registry_choice]
        if not url:
            url = Prompt.ask("Registry URL")

        con.console.print()
        con.console.print("[bold]Authentication Method[/bold]")
        con.console.print()
        con.console.print("  [cyan]1[/cyan]. Environment variables (recommended)")
        con.console.print("  [cyan]2[/cyan]. AWS Secrets Manager")
        con.console.print("  [cyan]3[/cyan]. Direct credentials (not recommended)")
        con.console.print()

        auth_choice = Prompt.ask(
            "Select authentication method",
            choices=["1", "2", "3"],
            default="1",
        )

        if auth_choice == "1":
            
            con.console.print()
            con.console.print(
                "[dim]Use $VAR_NAME or ${VAR_NAME} syntax to reference environment variables.[/dim]"
            )

            username_default = "$DOCKER_USERNAME" if url == "docker.io" else "$REGISTRY_USERNAME"
            password_default = "$DOCKER_PASSWORD" if url == "docker.io" else "$REGISTRY_PASSWORD"

            username = Prompt.ask(
                "Username (env var reference)",
                default=username_default,
            )
            password = Prompt.ask(
                "Password/token (env var reference)",
                default=password_default,
            )

            registries.append(
                RegistryConfig(
                    url=url,
                    username=username,
                    password=password,
                )
            )

        elif auth_choice == "2":
            
            secret_name: str = Prompt.ask(
                "AWS Secrets Manager secret name",
                default="registry-credentials",
            )

            registries.append(
                RegistryConfig(
                    url=url,
                    aws_secret_name=secret_name,
                )
            )

        else:
            
            con.print_warning(
                "Direct credentials will be stored in .rita.yaml (should be gitignored)"
            )
            username = Prompt.ask("Username")
            password = Prompt.ask("Password/token", password=True)

            registries.append(
                RegistryConfig(
                    url=url,
                    username=username,
                    password=password,
                )
            )

        con.console.print()
        if not Confirm.ask("Add another registry?", default=False):
            break

    return registries


def _prompt_test_config() -> ChartTestConfig:
    """Configure test settings."""
    con.print_header("Test Configuration")
    con.console.print()
    con.console.print("Configure settings for ephemeral cluster testing.")
    con.console.print()

    use_defaults: bool = Confirm.ask("Use default test settings?", default=True)

    if use_defaults:
        return ChartTestConfig()

    cluster_name: str = Prompt.ask(
        "Kind cluster name for testing",
        default="rita-test",
    )

    timeout_str: str = Prompt.ask(
        "Deployment timeout (seconds)",
        default="300",
    )
    timeout = int(timeout_str)

    cleanup_on_success: bool = Confirm.ask(
        "Delete cluster after successful tests?",
        default=True,
    )

    cleanup_on_failure: bool = Confirm.ask(
        "Delete cluster after failed tests?",
        default=False,
    )

    return ChartTestConfig(
        kind_cluster_name=cluster_name,
        timeout_seconds=timeout,
        cleanup_on_success=cleanup_on_success,
        cleanup_on_failure=cleanup_on_failure,
    )


@click.command("init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing config file.")
@click.option("--minimal", "-m", is_flag=True, help="Use minimal prompts with sensible defaults.")
def init(force: bool, minimal: bool) -> None:
    """Initialize a new rita project with interactive setup.

    Creates a .rita.yaml configuration file with settings for:

    \b
    • Charts directory and OCI registry
    • Environments (dev, prod, etc.)
    • Storage backend (local, S3, Garage, MinIO)
    • Registry authentication
    • Test configuration
    """
    try:
        repo_root: Path = get_repo_root()
    except Exception:
        con.print_error("Not in a git repository.")
        con.print_hint("Run 'git init' first or navigate to a git repository.")
        raise SystemExit(1) from None

    config_path: Path = repo_root / CONFIG_FILE_NAME

    if config_path.exists() and not force:
        con.print_error(f"Configuration file already exists: {config_path}")
        con.print_hint("Use --force to overwrite the existing configuration.")
        raise SystemExit(1)

    
    con.print_banner(
        "RITA Project Initialization",
        "Configure your Helm chart management workflow",
    )
    con.console.print()

    if minimal:
        
        con.console.print("[dim]Using minimal setup with sensible defaults...[/dim]")
        con.console.print()

        charts_path: str = Prompt.ask("Charts directory", default="charts")
        registry: str = Prompt.ask("OCI registry", default="ghcr.io/myorg")

        config = RitaConfig(
            environments=[
                EnvironmentConfig(
                    name="dev",
                    paths=["kubernetes/argocd/applications/dev/templates"],
                    aliases=["development", "staging"],
                ),
                EnvironmentConfig(
                    name="prod",
                    paths=["kubernetes/argocd/applications/prod/templates"],
                    aliases=["production"],
                ),
            ],
            charts=ChartConfig(path=charts_path, registry=registry),
            render=RenderConfig(),
            test=ChartTestConfig(),
            registries=[],
            auto_discover=True,
        )
    else:
        
        charts = _prompt_charts_config()
        environments = _prompt_environments()
        storage = _prompt_storage_config()
        render = _prompt_render_config(storage)
        registries = _prompt_registries()
        test = _prompt_test_config()

        con.console.print()
        auto_discover = Confirm.ask(
            "Auto-discover ArgoCD applications in configured paths?",
            default=True,
        )

        config = RitaConfig(
            environments=environments,
            charts=charts,
            render=render,
            test=test,
            registries=registries,
            auto_discover=auto_discover,
        )

    
    con.console.print()
    con.print_header("Configuration Summary")
    con.console.print()

    con.print_key_value("Charts directory", config.charts.path)
    con.print_key_value("OCI registry", config.charts.registry)
    con.print_key_value("Environments", ", ".join(e.name for e in config.environments))
    con.print_key_value(
        "Storage",
        config.render.storage.type if config.render.storage else "local",
    )
    if config.render.storage and config.render.storage.s3_bucket:
        con.print_key_value("  Bucket", config.render.storage.s3_bucket)
    con.print_key_value("Output path", config.render.output_path)
    con.print_key_value("Compare branch", config.render.compare_branch)
    con.print_key_value("Auto-discover", "yes" if config.auto_discover else "no")
    con.print_key_value("Registries", str(len(config.registries)))

    con.console.print()

    if not Confirm.ask("Save this configuration?", default=True):
        con.print_info("Configuration not saved.")
        return

    save_config(config, config_path)
    con.print_success(f"Configuration saved to {config_path}")

    
    con.console.print()
    con.print_header("Next Steps")
    con.console.print()

    
    charts_dir = repo_root / config.charts.path
    if not charts_dir.exists():
        con.console.print(f"  1. Create your charts directory: [cyan]mkdir -p {config.charts.path}[/cyan]")
    else:
        con.console.print(f"  1. Charts directory exists: [success]✓[/success] {config.charts.path}")

    
    for env in config.environments:
        for path in env.paths:
            env_path = repo_root / path
            if not env_path.exists():
                con.console.print(f"  2. Create {env.name} applications path: [cyan]mkdir -p {path}[/cyan]")
                break
    else:
        con.console.print("  2. Environment paths configured [success]✓[/success]")

    con.console.print()
    con.console.print("  Common commands:")
    con.console.print("    [cyan]rita chart list[/cyan]         - List local charts")
    con.console.print("    [cyan]rita render list[/cyan]        - List ArgoCD applications")
    con.console.print("    [cyan]rita render apply[/cyan]       - Render all manifests")
    con.console.print("    [cyan]rita schema list[/cyan]        - List charts with schemas")

    
    if config.render.storage and config.render.storage.type == "s3":
        con.console.print()
        if config.render.storage.aws_profile:
            con.console.print(
                f"  For S3 access, log in with: [cyan]aws sso login --profile {config.render.storage.aws_profile}[/cyan]"
            )
        else:
            con.console.print(
                "  Ensure AWS credentials are configured for S3 access."
            )

    
    gitignore_path = repo_root / ".gitignore"
    if gitignore_path.exists():
        gitignore_content = gitignore_path.read_text()
        if CONFIG_FILE_NAME not in gitignore_content:
            con.console.print()
            con.print_hint(
                f"Consider adding '{CONFIG_FILE_NAME}' to .gitignore if it contains sensitive data."
            )
            con.print_hint(
                "Use '.rita.template.yaml' for team-shared configuration without secrets."
            )
