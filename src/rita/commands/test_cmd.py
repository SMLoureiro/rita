"""Test commands for Helm charts with ephemeral clusters."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from rita.repository import get_chart_path, get_repo_root, list_apps_for_env
from rita.testing import (
    ChartTestResult,
    KindClusterManager,
    check_helm_installed,
    check_kind_installed,
    check_kubectl_installed,
    cluster_exists,
    create_kind_cluster,
    delete_kind_cluster,
    run_chart_deployment_test,
    run_chart_dry_run_test,
)


@click.group()
def test() -> None:
    """Test Helm charts with ephemeral clusters."""
    pass


@test.command("check")
def test_check() -> None:
    """Check if required tools are installed for testing."""
    all_good = True

    if check_helm_installed():
        click.echo("✓ helm is installed")
    else:
        click.echo("✗ helm is not installed")
        all_good = False

    if check_kubectl_installed():
        click.echo("✓ kubectl is installed")
    else:
        click.echo("✗ kubectl is not installed")
        all_good = False

    if check_kind_installed():
        click.echo("✓ kind is installed")
    else:
        click.echo("✗ kind is not installed (required for cluster testing)")
        all_good = False

    if all_good:
        click.echo()
        click.echo("All tools installed. Ready for testing!")
    else:
        click.echo()
        click.echo("Some tools are missing. Install them to enable testing.")
        raise SystemExit(1)


@test.command("cluster")
@click.option(
    "--name",
    "-n",
    "cluster_name",
    default="rita-test",
    help="Name of the kind cluster.",
)
@click.option(
    "--delete", is_flag=True, help="Delete the cluster instead of creating it."
)
def test_cluster(cluster_name: str, delete: bool) -> None:
    """Create or delete a kind cluster for testing."""
    if delete:
        if cluster_exists(cluster_name):
            success, msg = delete_kind_cluster(cluster_name)
            if success:
                click.echo(f"✓ {msg}")
            else:
                click.echo(f"Error: {msg}", err=True)
                raise SystemExit(1)
        else:
            click.echo(f"Cluster '{cluster_name}' doesn't exist.")
    else:
        if cluster_exists(cluster_name):
            click.echo(f"Cluster '{cluster_name}' already exists.")
            click.echo(
                f"  Delete with: rita test cluster --name {cluster_name} --delete"
            )
        else:
            click.echo(f"Creating kind cluster '{cluster_name}'...")
            success, msg = create_kind_cluster(cluster_name)
            if success:
                click.echo(f"✓ {msg}")
            else:
                click.echo(f"Error: {msg}", err=True)
                raise SystemExit(1)


@test.command("dry-run")
@click.option("--chart", "-c", "chart_name", help="Name of the chart to test.")
@click.option("--app", "-a", "app_name", help="Name of the ArgoCD application to test.")
@click.option(
    "--env", "-e", default="dev", help="Environment for ArgoCD application lookup."
)
@click.option(
    "--values",
    "-f",
    "values_file",
    multiple=True,
    type=click.Path(exists=True),
    help="Values file.",
)
def test_dry_run(
    chart_name: str | None,
    app_name: str | None,
    env: str,
    values_file: tuple[str, ...],
) -> None:
    """Test a chart with helm install --dry-run."""
    if not chart_name and not app_name:
        click.echo("Error: Must specify either --chart or --app", err=True)
        raise SystemExit(1)

    if chart_name:
        chart_path: Path = get_chart_path(chart_name)
        if not chart_path.exists():
            click.echo(f"Error: Chart not found: {chart_path}", err=True)
            raise SystemExit(1)

        values_files = [Path(vf) for vf in values_file] if values_file else None

        result: ChartTestResult = run_chart_dry_run_test(
            chart_path=chart_path,
            release_name=chart_name,
            namespace="default",
            values_files=values_files,
        )
    else:
        apps = list_apps_for_env(env)
        app = next((a for a in apps if a.name == app_name), None)

        if not app:
            click.echo(f"Error: Application '{app_name}' not found in {env}.", err=True)
            raise SystemExit(1)

        if not app.is_local_chart:
            click.echo(
                f"Error: Application '{app_name}' uses external chart.", err=True
            )
            raise SystemExit(1)

        chart_path: Path = get_chart_path(app.chart_name)
        repo_root: Path = get_repo_root()
        values_files = [repo_root / vf for vf in app.values_files]

        result: ChartTestResult = run_chart_dry_run_test(
            chart_path=chart_path,
            release_name=app.release_name,
            namespace=app.namespace,
            values_files=values_files,
        )

    if result.success:
        click.echo(f"✓ {result.chart_name}: {result.message}")
        click.echo(f"  Duration: {result.duration_seconds:.2f}s")
    else:
        click.echo(f"✗ {result.chart_name}: {result.message}", err=True)
        raise SystemExit(1)


@test.command("deploy")
@click.option("--chart", "-c", "chart_name", help="Name of the chart to test.")
@click.option("--app", "-a", "app_name", help="Name of the ArgoCD application to test.")
@click.option(
    "--env", "-e", default="dev", help="Environment for ArgoCD application lookup."
)
@click.option("--cluster", default="rita-test", help="Name of the kind cluster to use.")
@click.option(
    "--create-cluster",
    is_flag=True,
    help="Create the kind cluster if it doesn't exist.",
)
@click.option("--cleanup", is_flag=True, help="Delete the cluster after testing.")
@click.option("--timeout", default=300, help="Timeout in seconds for deployment.")
def test_deploy(
    chart_name: str | None,
    app_name: str | None,
    env: str,
    cluster: str,
    create_cluster: bool,
    cleanup: bool,
    timeout: int,
) -> None:
    """Deploy a chart to a kind cluster and verify it works."""
    if not chart_name and not app_name:
        click.echo("Error: Must specify either --chart or --app", err=True)
        raise SystemExit(1)

    if chart_name:
        chart_path: Path = get_chart_path(chart_name)
        if not chart_path.exists():
            click.echo(f"Error: Chart not found: {chart_path}", err=True)
            raise SystemExit(1)
        release_name = chart_name
        namespace = "default"
        values_files = None
    else:
        apps = list_apps_for_env(env)
        app = next((a for a in apps if a.name == app_name), None)

        if not app:
            click.echo(f"Error: Application '{app_name}' not found in {env}.", err=True)
            raise SystemExit(1)

        if not app.is_local_chart:
            click.echo(
                f"Error: Application '{app_name}' uses external chart.", err=True
            )
            raise SystemExit(1)

        chart_path: Path = get_chart_path(app.chart_name)
        repo_root: Path = get_repo_root()
        release_name = app.release_name
        namespace = app.namespace
        values_files = [repo_root / vf for vf in app.values_files]

    if not cluster_exists(cluster) and not create_cluster:
        click.echo(f"Error: Cluster '{cluster}' doesn't exist.", err=True)
        click.echo(f"  Create with: rita test cluster --name {cluster}")
        click.echo("  Or use: --create-cluster")
        raise SystemExit(1)

    with KindClusterManager(
        cluster_name=cluster,
        cleanup_on_success=cleanup,
        cleanup_on_failure=False,
    ):
        click.echo(f"Deploying {chart_path.name}...")

        result: ChartTestResult = run_chart_deployment_test(
            chart_path=chart_path,
            release_name=release_name,
            namespace=namespace,
            values_files=values_files,
            timeout_seconds=timeout,
        )

        if result.success:
            click.echo(f"✓ {result.chart_name}: {result.message}")
            click.echo(f"  Duration: {result.duration_seconds:.2f}s")
        else:
            click.echo(f"✗ {result.chart_name}: {result.message}", err=True)
            if result.details and "logs" in result.details:
                click.echo()
                click.echo("Pod logs:")
                click.echo(result.details["logs"])
            raise SystemExit(1)
