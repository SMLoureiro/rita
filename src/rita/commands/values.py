"""Values commands for fetching and comparing Helm chart values."""

from __future__ import annotations

from pathlib import Path

import rich_click as click
from rich.prompt import Prompt

from rita import console as con
from rita.helm import list_helm_chart_versions, pull_helm_chart_values
from rita.repository import get_repo_root, list_apps_for_env, list_available_envs


@click.group()
def values() -> None:
    """Fetch and compare Helm chart values."""
    pass


@values.command("list")
@click.option(
    "--env", "-e", default="dev", help="Environment to list applications for."
)
@click.option(
    "--all-envs", is_flag=True, help="List applications for all environments."
)
def values_list(env: str, all_envs: bool) -> None:
    """List ArgoCD applications with external Helm charts."""
    envs_to_list = list_available_envs() if all_envs or env == "all" else [env]

    for current_env in envs_to_list:
        apps = list_apps_for_env(current_env)
        external_apps = [a for a in apps if not a.is_local_chart]

        if not external_apps:
            con.print_warning(
                f"No external chart applications found in {con.format_env(current_env)} environment."
            )
            continue

        con.print_header(f"External Chart Applications in {current_env}")

        app_data = [
            (
                app.name,
                app.chart_name,
                app.chart_version,
                app.namespace,
                app.is_local_chart,
                app.values_files,
            )
            for app in external_apps
        ]
        con.print_app_list(app_data)


@values.command("versions")
@click.option(
    "--app", "-a", "app_name", required=True, help="Name of the ArgoCD application."
)
@click.option("--env", "-e", default="dev", help="Environment.")
@click.option(
    "--max",
    "-n",
    "max_versions",
    default=20,
    help="Maximum number of versions to show.",
)
def values_versions(app_name: str, env: str, max_versions: int) -> None:
    """List available versions of a Helm chart."""
    apps = list_apps_for_env(env)
    app = next((a for a in apps if a.name == app_name), None)

    if not app:
        con.print_error(f"Application '{app_name}' not found in {env}.")
        raise SystemExit(1)

    con.print_header(f"Versions for {app.chart_name}")
    con.print_key_value("Repository", app.chart_repo)
    con.print_key_value("Current version", app.chart_version)
    con.console.print()

    success, versions, error = list_helm_chart_versions(
        app.chart_repo, app.chart_name, max_versions
    )

    if not success:
        con.print_warning(error)
        return

    if not versions:
        con.print_warning("No versions found.")
        return

    con.console.print("[bold]Available versions:[/bold]")
    for version in versions:
        marker = " [green]← current[/green]" if version == app.chart_version else ""
        con.console.print(f"  {version}{marker}")


def _interactive_version_select(
    versions: list[str], current_version: str
) -> str | None:
    """Show an interactive version selection menu."""
    con.console.print("\n[bold]Available versions:[/bold]")
    for i, version in enumerate(versions, 1):
        marker = " [green](current)[/green]" if version == current_version else ""
        con.console.print(f"  [cyan]{i:2}[/cyan]. {version}{marker}")

    con.console.print(f"  [cyan] 0[/cyan]. Use current version ({current_version})")
    con.console.print()

    while True:
        choice: str = Prompt.ask("Select version", default="0")

        if choice == "0" or choice == "":
            return current_version

        try:
            idx = int(choice)
            if 1 <= idx <= len(versions):
                return versions[idx - 1]
            else:
                con.console.print("[red]Invalid selection. Try again.[/red]")
        except ValueError:
            if choice in versions:
                return choice
            con.console.print(
                "[red]Invalid input. Enter a number or version string.[/red]"
            )


@values.command("fetch")
@click.option(
    "--app", "-a", "app_name", required=True, help="Name of the ArgoCD application."
)
@click.option("--env", "-e", default="dev", help="Environment.")
@click.option("--version", "-v", "target_version", help="Version to fetch.")
@click.option("--output", "-o", "output_path", type=click.Path(), help="Output path.")
@click.option(
    "--use-current",
    is_flag=True,
    help="Use the current ArgoCD version without prompting.",
)
def values_fetch(
    app_name: str,
    env: str,
    target_version: str | None,
    output_path: str | None,
    use_current: bool,
) -> None:
    """Fetch default values from a Helm chart."""
    apps = list_apps_for_env(env)
    app = next((a for a in apps if a.name == app_name), None)

    if not app:
        con.print_error(f"Application '{app_name}' not found in {env}.")
        raise SystemExit(1)

    con.print_header(f"Fetching values for {app.chart_name}")
    con.print_key_value("Environment", f"[bold cyan]{env}[/bold cyan]")
    con.print_key_value("ArgoCD Application", app.name)
    if app.source_file:
        repo_root = get_repo_root()
        try:
            rel_source = app.source_file.relative_to(repo_root)
            con.print_key_value("Source file", str(rel_source))
        except ValueError:
            con.print_key_value("Source file", str(app.source_file))
    con.print_key_value("Repository", app.chart_repo)
    con.print_key_value("Current version", app.chart_version)
    con.console.print()

    if target_version:
        version = target_version
    elif use_current:
        version = app.chart_version
    else:
        success, versions, error = list_helm_chart_versions(
            app.chart_repo, app.chart_name, max_versions=30
        )

        if success and versions:
            selected: str | None = _interactive_version_select(
                versions, app.chart_version
            )
            if selected is None:
                con.console.print("Cancelled.")
                return
            version: str = selected
        else:
            if error:
                con.print_warning(error)
            con.print_info(f"Using current version: {app.chart_version}")
            version = app.chart_version

    if output_path:
        dest_path = Path(output_path)
    else:
        if not app.values_files:
            con.print_error(
                "Application has no values files. Use --output to specify destination."
            )
            raise SystemExit(1)

        repo_root: Path = get_repo_root()
        first_values = repo_root / app.values_files[0]
        stem = first_values.stem
        dest_path = first_values.parent / f"{stem}.temp.yaml"

    con.print_header(f"Fetching values for {app.chart_name}")
    con.print_key_value("Repository", app.chart_repo)
    con.print_key_value("Chart", app.chart_name)
    con.print_key_value("Version", version)
    con.print_key_value("Output", str(dest_path))
    con.console.print()

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    success, error = pull_helm_chart_values(
        app.chart_repo, app.chart_name, version, dest_path
    )

    if success:
        con.print_success(f"Values saved to: {dest_path}")
        con.console.print()

        if app.values_files:
            repo_root: Path = get_repo_root()
            values_file = repo_root / app.values_files[0]
            con.print_hint(f"Compare with: diff {values_file} {dest_path}")
    else:
        con.print_error(f"Failed to fetch values: {error}")
        raise SystemExit(1)


@values.command("clean")
@click.option(
    "--path",
    "-p",
    "search_path",
    default="kubernetes",
    help="Path to search for .temp.yaml files.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be deleted without actually deleting.",
)
def values_clean(search_path: str, dry_run: bool) -> None:
    """Remove all .temp.yaml files."""
    repo_root: Path = get_repo_root()
    search_dir: Path = repo_root / search_path

    if not search_dir.exists():
        con.print_warning(f"Path not found: {search_dir}")
        return

    temp_files: list[Path] = list(search_dir.rglob("*.temp.yaml"))

    if not temp_files:
        con.console.print("No .temp.yaml files found.")
        return

    for temp_file in temp_files:
        rel_path: Path = temp_file.relative_to(repo_root)
        if dry_run:
            con.console.print(f"Would delete: {rel_path}")
        else:
            temp_file.unlink()
            con.console.print(f"Deleted: {rel_path}")

    if dry_run:
        con.console.print(f"\n{len(temp_files)} files would be deleted.")
    else:
        con.print_success(f"Deleted {len(temp_files)} files.")
