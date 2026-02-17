"""Ephemeral cluster testing for Helm charts.

This module provides functionality to:
1. Create kind clusters for testing
2. Deploy charts and verify they work
3. Run validation tests
4. Clean up clusters
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from subprocess import CompletedProcess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import click


@dataclass
class ChartTestResult:
    """Result of a chart test."""

    chart_name: str
    success: bool
    message: str
    duration_seconds: float
    details: dict[str, Any] | None = None


def check_kind_installed() -> bool:
    """Check if kind is installed."""
    try:
        subprocess.run(
            ["kind", "version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def check_kubectl_installed() -> bool:
    """Check if kubectl is installed."""
    try:
        subprocess.run(
            ["kubectl", "version", "--client"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def check_helm_installed() -> bool:
    """Check if helm is installed."""
    try:
        subprocess.run(
            ["helm", "version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def cluster_exists(cluster_name: str) -> bool:
    """Check if a kind cluster already exists."""
    try:
        result: CompletedProcess[str] = subprocess.run(
            ["kind", "get", "clusters"],
            capture_output=True,
            text=True,
            check=True,
        )
        clusters = result.stdout.strip().split("\n")
        return cluster_name in clusters
    except subprocess.CalledProcessError:
        return False


def create_kind_cluster(
    cluster_name: str,
    config_path: Path | None = None,
    wait_timeout: str = "60s",
) -> tuple[bool, str]:
    """Create a kind cluster.

    Returns (success, message).
    """
    if cluster_exists(cluster_name):
        return True, f"Cluster '{cluster_name}' already exists"

    cmd = ["kind", "create", "cluster", "--name", cluster_name, "--wait", wait_timeout]

    if config_path and config_path.exists():
        cmd.extend(["--config", str(config_path)])

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return True, f"Created cluster '{cluster_name}'"
    except subprocess.CalledProcessError as e:
        return False, f"Failed to create cluster: {e.stderr}"


def delete_kind_cluster(cluster_name: str) -> tuple[bool, str]:
    """Delete a kind cluster.

    Returns (success, message).
    """
    if not cluster_exists(cluster_name):
        return True, f"Cluster '{cluster_name}' doesn't exist"

    try:
        subprocess.run(
            ["kind", "delete", "cluster", "--name", cluster_name],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, f"Deleted cluster '{cluster_name}'"
    except subprocess.CalledProcessError as e:
        return False, f"Failed to delete cluster: {e.stderr}"


def set_kubectl_context(cluster_name: str) -> tuple[bool, str]:
    """Set kubectl context to the kind cluster.

    Returns (success, message).
    """
    context_name = f"kind-{cluster_name}"
    try:
        subprocess.run(
            ["kubectl", "config", "use-context", context_name],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, f"Switched to context '{context_name}'"
    except subprocess.CalledProcessError as e:
        return False, f"Failed to switch context: {e.stderr}"


def apply_manifests(manifest_paths: list[Path]) -> tuple[bool, str]:
    """Apply manifests to the cluster.

    Returns (success, message).
    """
    for path in manifest_paths:
        if not path.exists():
            return False, f"Manifest not found: {path}"

        try:
            subprocess.run(
                ["kubectl", "apply", "-f", str(path)],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            return False, f"Failed to apply {path}: {e.stderr}"

    return True, f"Applied {len(manifest_paths)} manifests"


def helm_install(
    release_name: str,
    chart_path: Path,
    namespace: str = "default",
    values_files: list[Path] | None = None,
    set_values: dict[str, str] | None = None,
    wait: bool = True,
    timeout: str = "5m",
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Install a Helm chart.

    Returns (success, message).
    """
    cmd = [
        "helm",
        "install",
        release_name,
        str(chart_path),
        "--namespace",
        namespace,
        "--create-namespace",
    ]

    if values_files:
        for vf in values_files:
            if vf.exists():
                cmd.extend(["--values", str(vf)])

    if set_values:
        for key, value in set_values.items():
            cmd.extend(["--set", f"{key}={value}"])

    if wait:
        cmd.append("--wait")
        cmd.extend(["--timeout", timeout])

    if dry_run:
        cmd.append("--dry-run")

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return True, f"Installed {release_name}"
    except subprocess.CalledProcessError as e:
        return False, f"Failed to install: {e.stderr}"


def helm_uninstall(release_name: str, namespace: str = "default") -> tuple[bool, str]:
    """Uninstall a Helm release.

    Returns (success, message).
    """
    try:
        subprocess.run(
            ["helm", "uninstall", release_name, "--namespace", namespace],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, f"Uninstalled {release_name}"
    except subprocess.CalledProcessError as e:
        return False, f"Failed to uninstall: {e.stderr}"


def wait_for_pods_ready(
    namespace: str = "default",
    timeout_seconds: int = 300,
    label_selector: str | None = None,
) -> tuple[bool, str]:
    """Wait for all pods in a namespace to be ready.

    Returns (success, message).
    """
    cmd = [
        "kubectl",
        "wait",
        "pods",
        "--namespace",
        namespace,
        "--for=condition=Ready",
        f"--timeout={timeout_seconds}s",
    ]

    if label_selector:
        cmd.extend(["--selector", label_selector])
    else:
        cmd.append("--all")

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return True, "All pods ready"
    except subprocess.CalledProcessError as e:
        status_result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-o", "wide"],
            capture_output=True,
            text=True,
        )
        return (
            False,
            f"Pods not ready: {e.stderr}\n\nPod status:\n{status_result.stdout}",
        )


def get_pod_logs(
    namespace: str = "default",
    label_selector: str | None = None,
    container: str | None = None,
    tail: int = 100,
) -> str:
    """Get logs from pods in a namespace."""
    cmd = ["kubectl", "logs", "-n", namespace, f"--tail={tail}"]

    if label_selector:
        cmd.extend(["--selector", label_selector])
    else:
        cmd.append("--all-containers=true")

    if container:
        cmd.extend(["-c", container])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return ""


def run_chart_deployment_test(
    chart_path: Path,
    release_name: str,
    namespace: str,
    values_files: list[Path] | None = None,
    timeout_seconds: int = 300,
) -> ChartTestResult:
    """Run a chart deployment test by actually installing it.

    This:
    1. Installs the chart with --wait
    2. Verifies pods are ready
    3. Uninstalls the chart
    """
    start_time = time.time()

    success, msg = helm_install(
        release_name=release_name,
        chart_path=chart_path,
        namespace=namespace,
        values_files=values_files,
        wait=True,
        timeout=f"{timeout_seconds}s",
    )

    if not success:
        return ChartTestResult(
            chart_name=chart_path.name,
            success=False,
            message=f"Installation failed: {msg}",
            duration_seconds=time.time() - start_time,
        )

    success, msg = wait_for_pods_ready(namespace=namespace, timeout_seconds=60)

    if not success:
        logs: str = get_pod_logs(namespace=namespace)
        return ChartTestResult(
            chart_name=chart_path.name,
            success=False,
            message=f"Pods not ready: {msg}",
            duration_seconds=time.time() - start_time,
            details={"logs": logs},
        )

    helm_uninstall(release_name, namespace)

    return ChartTestResult(
        chart_name=chart_path.name,
        success=True,
        message="Chart deployed and verified successfully",
        duration_seconds=time.time() - start_time,
    )


def run_chart_dry_run_test(
    chart_path: Path,
    release_name: str,
    namespace: str,
    values_files: list[Path] | None = None,
) -> ChartTestResult:
    """Run a chart dry-run test (no actual deployment).

    This validates that the chart templates correctly without deploying.
    """
    start_time: int | float = time.time()

    success, msg = helm_install(
        release_name=release_name,
        chart_path=chart_path,
        namespace=namespace,
        values_files=values_files,
        wait=False,
        dry_run=True,
    )

    return ChartTestResult(
        chart_name=chart_path.name,
        success=success,
        message=msg if not success else "Chart templates valid (dry-run)",
        duration_seconds=time.time() - start_time,
    )


class KindClusterManager:
    """Context manager for kind cluster lifecycle."""

    def __init__(
        self,
        cluster_name: str,
        cleanup_on_success: bool = True,
        cleanup_on_failure: bool = False,
    ):
        self.cluster_name: str = cluster_name
        self.cleanup_on_success: bool = cleanup_on_success
        self.cleanup_on_failure: bool = cleanup_on_failure
        self.created = False
        self.success = True

    def __enter__(self) -> KindClusterManager:
        if not cluster_exists(self.cluster_name):
            success, msg = create_kind_cluster(self.cluster_name)
            if not success:
                raise RuntimeError(f"Failed to create cluster: {msg}")
            self.created = True
            click.echo(f"✓ {msg}")
        else:
            click.echo(f"Using existing cluster '{self.cluster_name}'")

        success, msg = set_kubectl_context(self.cluster_name)
        if not success:
            raise RuntimeError(f"Failed to set context: {msg}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.success = False

        should_cleanup = (self.success and self.cleanup_on_success) or (
            not self.success and self.cleanup_on_failure
        )

        if should_cleanup and self.created:
            click.echo(f"Cleaning up cluster '{self.cluster_name}'...")
            delete_kind_cluster(self.cluster_name)
        elif not should_cleanup:
            click.echo(f"Leaving cluster '{self.cluster_name}' for inspection")
            click.echo(f"  Delete with: kind delete cluster --name {self.cluster_name}")

        return False
