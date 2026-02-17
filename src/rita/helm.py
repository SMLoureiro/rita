"""Helm chart operations."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from subprocess import CompletedProcess
from typing import TYPE_CHECKING, Any, TypedDict

import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

    from rita.models import ArgoAppConfig

from rita.argocd import (
    ArgoAppSetConfig,
    is_applicationset_chart,
    parse_applicationset_from_manifest,
    parse_argocd_resources_from_manifest,
)
from rita.config import RitaConfig, get_registry_credentials, load_config
from rita.storage import (
    AWSTokenExpiredError,
    S3StorageBackend,
    download_cached_chart,
    get_chart_cache,
    upload_chart_to_cache,
)


class K8sResource(TypedDict, total=False):
    """Basic Kubernetes resource structure."""

    apiVersion: str
    kind: str
    metadata: dict[str, Any]
    spec: dict[str, Any]
    data: dict[str, Any]
    stringData: dict[str, Any]


class ChartMetadata(TypedDict, total=False):
    """Helm Chart.yaml metadata."""

    version: str
    name: str
    dependencies: list[dict[str, Any]]


OCI_REGISTRY_INDICATORS = [
    "ghcr.io",
    "gcr.io",
    "azurecr.io",
    "dkr.ecr.",
    "pkg.dev",
    "docker.io",
    "registry.io",
    "quay.io",
]

TRADITIONAL_REPO_INDICATORS = [
    "github.io",
    "charts.",
    "/charts",
    "/helm",
    "hub.jupyter.org",
    "tigera.io",
]


def get_local_chart_version(chart_path: Path) -> str | None:
    chart_yaml: Path = chart_path / "Chart.yaml"
    if not chart_yaml.exists():
        return None

    try:
        with chart_yaml.open(encoding="utf-8") as f:
            chart_data: Any = yaml.safe_load(f)
        return chart_data.get("version")
    except Exception:
        return None


def is_oci_registry(repo_url: str) -> bool:
    repo_lower: str = repo_url.lower()

    if repo_lower.startswith("oci://"):
        return True

    for indicator in TRADITIONAL_REPO_INDICATORS:
        if indicator in repo_lower:
            return False

    return any(indicator in repo_lower for indicator in OCI_REGISTRY_INDICATORS)


def has_packaged_dependencies(chart_path: Path) -> bool:
    charts_dir: Path = chart_path / "charts"
    if not charts_dir.exists():
        return False

    tgz_files: list[Path] = list(charts_dir.glob("*.tgz"))
    return len(tgz_files) > 0


def build_chart_dependencies(chart_path: Path) -> tuple[bool, str]:
    cmd: list[str] = ["helm", "dependency", "build", str(chart_path)]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, "Dependencies built successfully"
    except subprocess.CalledProcessError as e:
        return False, f"Failed to build dependencies: {e.stderr}"


def ensure_registry_auth(registry_url: str) -> bool:
    config: RitaConfig = load_config()
    username, password = get_registry_credentials(config, registry_url)

    if not username or not password:
        return True

    registry = _extract_registry_host(registry_url)
    cmd = [
        "helm",
        "registry",
        "login",
        registry,
        "--username",
        username,
        "--password-stdin",
    ]

    try:
        subprocess.run(cmd, input=password, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def _extract_registry_host(registry_url: str) -> str:
    registry: str = registry_url.replace("https://", "").replace("http://", "")
    if "/" in registry:
        registry: str = registry.split("/")[0]
    return registry


def pull_traditional_helm_chart(
    repo_url: str, chart_name: str, version: str, dest_dir: Path
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as temp_config_dir:
        temp_config: Path = Path(temp_config_dir)
        temp_repo_name: str = "rita-temp-repo"
        helm_env: dict[str, str] = _create_isolated_helm_env(temp_config)

        try:
            if not _add_helm_repo(temp_repo_name, repo_url, helm_env):
                return False, f"Failed to add helm repo: {repo_url}"

            _update_helm_repo(temp_repo_name, helm_env)
            _pull_chart_from_repo(
                temp_repo_name, chart_name, version, dest_dir, helm_env
            )
            return _find_extracted_chart(dest_dir, chart_name)

        except subprocess.CalledProcessError as e:
            return False, f"Failed to pull chart: {e.stderr}"


def pull_oci_chart(
    repo_url: str, chart_name: str, version: str, dest_dir: Path
) -> tuple[bool, str]:
    ensure_registry_auth(repo_url)

    oci_url = f"oci://{repo_url}/{chart_name}"
    cmd = [
        "helm",
        "pull",
        oci_url,
        "--version",
        version,
        "--destination",
        str(dest_dir),
        "--untar",
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return _find_extracted_chart(dest_dir, chart_name)
    except subprocess.CalledProcessError as e:
        return False, f"Failed to pull chart: {e.stderr}"


def _create_isolated_helm_env(temp_config: Path) -> dict[str, str]:
    helm_env: dict[str, str] = os.environ.copy()
    helm_env["HELM_REPOSITORY_CONFIG"] = str(temp_config / "repositories.yaml")
    helm_env["HELM_REPOSITORY_CACHE"] = str(temp_config / "cache")
    return helm_env


def _add_helm_repo(repo_name: str, repo_url: str, helm_env: dict[str, str]) -> bool:
    result: CompletedProcess[str] = subprocess.run(
        ["helm", "repo", "add", repo_name, repo_url],
        capture_output=True,
        text=True,
        check=False,
        env=helm_env,
    )
    return result.returncode == 0


def _update_helm_repo(repo_name: str, helm_env: dict[str, str]) -> None:
    subprocess.run(
        ["helm", "repo", "update", repo_name],
        capture_output=True,
        text=True,
        check=False,
        env=helm_env,
    )


def _pull_chart_from_repo(
    repo_name: str, chart_name: str, version: str, dest_dir: Path, helm_env: dict
) -> None:
    cmd = [
        "helm",
        "pull",
        f"{repo_name}/{chart_name}",
        "--version",
        version,
        "--destination",
        str(dest_dir),
        "--untar",
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True, env=helm_env)


def _find_extracted_chart(dest_dir: Path, chart_name: str) -> tuple[bool, str]:
    simple_name: str = chart_name.split("/")[-1] if "/" in chart_name else chart_name
    chart_dir: Path = dest_dir / simple_name

    if chart_dir.exists():
        return True, str(chart_dir)

    subdirs = [d for d in dest_dir.iterdir() if d.is_dir()]
    if subdirs:
        return True, str(subdirs[0])

    return False, f"Chart extracted but directory not found in {dest_dir}"


def prepare_chart_for_rendering(
    app: ArgoAppConfig,
    temp_dir: Path,
    chart_path_resolver: Callable[[str], Path],
    use_chart_cache: bool = True,
) -> tuple[bool, str, Path | None]:
    if not app.is_local_chart:
        return _prepare_external_chart(app, temp_dir, use_chart_cache)

    local_version: str | None = get_local_chart_version(
        chart_path_resolver(app.chart_name)
    )
    local_chart_path: Path = chart_path_resolver(app.chart_name)

    if local_version == app.chart_version:
        return _prepare_local_chart(app, temp_dir, local_chart_path)
    else:
        return _prepare_versioned_chart(app, temp_dir, use_chart_cache)


def _prepare_external_chart(
    app: ArgoAppConfig, temp_dir: Path, use_chart_cache: bool
) -> tuple[bool, str, Path | None]:
    config: RitaConfig = load_config()
    cache: S3StorageBackend | None = (
        get_chart_cache(config) if use_chart_cache else None
    )

    if cache:
        success, msg, chart_path = download_cached_chart(
            cache, app.chart_name, app.chart_version, temp_dir
        )
        if success and chart_path:
            return True, msg, chart_path

    if is_oci_registry(app.chart_repo):
        success, result = pull_oci_chart(
            app.chart_repo, app.chart_name, app.chart_version, temp_dir
        )
        pull_type = "OCI"
    else:
        success, result = pull_traditional_helm_chart(
            app.chart_repo, app.chart_name, app.chart_version, temp_dir
        )
        pull_type = "Helm repo"

    if not success:
        return False, result, None

    chart_path = Path(result)
    _cache_chart_if_possible(cache, app.chart_name, app.chart_version, chart_path)

    return True, f"Chart pulled from {pull_type}", chart_path


def _cache_chart_if_possible(
    cache: Any, chart_name: str, version: str, chart_path: Path
) -> None:
    if cache:
        with contextlib.suppress(Exception):
            upload_chart_to_cache(cache, chart_name, version, chart_path)


def _prepare_local_chart(
    app: ArgoAppConfig, temp_dir: Path, local_chart_path: Path
) -> tuple[bool, str, Path | None]:
    local_version: str | None = get_local_chart_version(local_chart_path)
    temp_chart_path: Path = temp_dir / app.chart_name
    shutil.copytree(local_chart_path, temp_chart_path, dirs_exist_ok=True)

    _copy_file_dependencies(temp_chart_path, local_chart_path.parent, temp_dir)

    if not has_packaged_dependencies(temp_chart_path):
        success, msg = build_chart_dependencies(temp_chart_path)
        if not success:
            return False, msg, None

    return True, f"Using local chart (v{local_version})", temp_chart_path


def _copy_file_dependencies(chart_path: Path, charts_dir: Path, temp_dir: Path) -> None:
    """Copy file:// dependencies from Chart.yaml to the temp directory.

    This handles charts that have dependencies like:
        repository: "file://../postgresql"

    The dependency path is resolved relative to the original chart's location
    in charts_dir, then copied to temp_dir to maintain the same relative structure.
    """
    chart_yaml: Path = chart_path / "Chart.yaml"
    if not chart_yaml.exists():
        return

    try:
        with chart_yaml.open(encoding="utf-8") as f:
            chart_data = yaml.safe_load(f)
    except Exception:
        return

    dependencies = chart_data.get("dependencies", [])
    for dep in dependencies:
        repo = dep.get("repository", "")
        if repo.startswith("file://"):
            rel_path = repo.replace("file://", "")
            source_path = (charts_dir / chart_path.name / rel_path).resolve()

            if source_path.exists() and source_path.is_dir():
                dest_path = temp_dir / source_path.name
                if not dest_path.exists():
                    shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                    _copy_file_dependencies(dest_path, charts_dir, temp_dir)


def _prepare_versioned_chart(
    app: ArgoAppConfig, temp_dir: Path, use_chart_cache: bool
) -> tuple[bool, str, Path | None]:
    config: RitaConfig = load_config()
    cache: S3StorageBackend | None = (
        get_chart_cache(config) if use_chart_cache else None
    )

    if cache:
        success, msg, chart_path = download_cached_chart(
            cache, app.chart_name, app.chart_version, temp_dir
        )
        if success and chart_path:
            return True, msg, chart_path

    chart_name: str = app.oci_chart_name or app.chart_name
    success, result = pull_oci_chart(
        app.chart_repo, chart_name, app.chart_version, temp_dir
    )
    if not success:
        return False, result, None

    chart_path = Path(result)
    _cache_chart_if_possible(cache, app.chart_name, app.chart_version, chart_path)

    return True, f"Chart pulled from OCI (v{app.chart_version})", chart_path


def render_helm_chart(
    app: ArgoAppConfig,
    output_dir: Path,
    repo_root: Path,
    chart_path_resolver: Callable[[str], Path],
    include_crds: bool = True,
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        success, prep_msg, chart_path = prepare_chart_for_rendering(
            app, temp_path, chart_path_resolver
        )
        if not success:
            return False, prep_msg

        if chart_path is None:
            return False, "Chart path not set"

        for vf in app.values_files:
            values_path: Path = repo_root / vf
            if not values_path.exists():
                return False, f"Values file not found: {values_path}"

        cmd: list[str] = _build_template_command(
            app, chart_path, repo_root, include_crds
        )

        try:
            result: CompletedProcess[str] = subprocess.run(
                cmd, capture_output=True, text=True, check=True, cwd=str(repo_root)
            )
            rendered: str = result.stdout
        except subprocess.CalledProcessError as e:
            return False, f"Helm template failed: {e.stderr}"
        except FileNotFoundError:
            return False, "helm command not found. Please install Helm."

        doc_count: int = _write_rendered_output(rendered, output_dir)
        return True, f"Rendered {doc_count} resources ({prep_msg})"


def _build_template_command(
    app: ArgoAppConfig, chart_path: Path, repo_root: Path, include_crds: bool
) -> list[str]:
    cmd = [
        "helm",
        "template",
        app.release_name,
        str(chart_path),
        "--namespace",
        app.namespace,
        "--skip-schema-validation",
    ]

    for vf in app.values_files:
        values_path: Path = repo_root / vf
        if values_path.exists():
            cmd.extend(["--values", str(values_path)])

    if include_crds:
        cmd.append("--include-crds")

    return cmd


def _write_rendered_output(rendered: str, output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        docs = list(yaml.load_all(rendered, Loader=_create_safe_loader()))
        by_kind: dict[str, list[dict[str, Any]]] = _group_docs_by_kind(docs)

        for kind, resources in by_kind.items():
            _write_kind_file(output_dir, kind, resources)

        doc_count: int = len([d for d in docs if d])
    except yaml.YAMLError:
        doc_count: int = rendered.count("\n---\n") + 1

    all_file: Path = output_dir / "_all.yaml"
    with all_file.open("w", encoding="utf-8") as f:
        f.write(rendered)

    return doc_count


def _create_safe_loader():
    class SafeLoaderWithValue(yaml.SafeLoader):
        pass

    SafeLoaderWithValue.add_constructor(
        "tag:yaml.org,2002:value",
        lambda loader, node: loader.construct_scalar(node),
    )
    return SafeLoaderWithValue


def _group_docs_by_kind(docs: list[dict]) -> dict[str, list[dict[str, Any]]]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        if not doc:
            continue
        kind = doc.get("kind", "Unknown")
        if kind not in by_kind:
            by_kind[kind] = []
        by_kind[kind].append(doc)
    return by_kind


def _write_kind_file(output_dir: Path, kind: str, resources: list[dict]) -> None:
    kind_file: Path = output_dir / f"{kind.lower()}.yaml"
    with kind_file.open("w", encoding="utf-8") as f:
        for i, resource in enumerate(resources):
            if i > 0:
                f.write("---\n")
            yaml.safe_dump(resource, f, default_flow_style=False, sort_keys=False)


def list_helm_chart_versions(
    repo_url: str, chart_name: str, max_versions: int = 20
) -> tuple[bool, list[str], str]:
    if is_oci_registry(repo_url):
        return (
            False,
            [],
            "OCI registries don't support version listing directly. "
            "Use --version to specify a version.",
        )

    return _list_traditional_repo_versions(repo_url, chart_name, max_versions)


def _list_traditional_repo_versions(
    repo_url: str, chart_name: str, max_versions: int
) -> tuple[bool, list[str], str]:
    with tempfile.TemporaryDirectory() as temp_config_dir:
        temp_config = Path(temp_config_dir)
        temp_repo_name = "rita-temp-repo"
        helm_env: dict[str, str] = _create_isolated_helm_env(temp_config)

        try:
            if not _add_helm_repo(temp_repo_name, repo_url, helm_env):
                return False, [], f"Failed to add helm repo: {repo_url}"

            _update_helm_repo(temp_repo_name, helm_env)

            search_result: CompletedProcess[str] = subprocess.run(
                [
                    "helm",
                    "search",
                    "repo",
                    f"{temp_repo_name}/{chart_name}",
                    "--versions",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
                env=helm_env,
            )

            results: Any = json.loads(search_result.stdout)
            versions = [
                r.get("version", "") for r in results[:max_versions] if r.get("version")
            ]

            return True, versions, ""

        except subprocess.CalledProcessError as e:
            return False, [], f"Failed to search helm repo: {e.stderr}"
        except json.JSONDecodeError:
            return False, [], "Failed to parse helm search output"


def pull_helm_chart_values(
    repo_url: str, chart_name: str, version: str, dest_path: Path
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        if is_oci_registry(repo_url):
            success, result = _pull_oci_for_values(
                repo_url, chart_name, version, temp_path
            )
        else:
            success, result = _pull_traditional_for_values(
                repo_url, chart_name, version, temp_path
            )

        if not success:
            return False, result

        chart_dir = Path(result)
        values_file: Path = chart_dir / "values.yaml"

        if not values_file.exists():
            return False, f"No values.yaml found in chart at {chart_dir}"

        shutil.copy(values_file, dest_path)
        return True, ""


def _pull_oci_for_values(
    repo_url: str, chart_name: str, version: str, temp_path: Path
) -> tuple[bool, str]:
    if not repo_url.startswith("oci://"):
        oci_url = f"oci://{repo_url}/{chart_name}"
    else:
        oci_url = f"{repo_url}/{chart_name}"

    cmd = [
        "helm",
        "pull",
        oci_url,
        "--version",
        version,
        "--destination",
        str(temp_path),
        "--untar",
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return _find_chart_dir(temp_path)
    except subprocess.CalledProcessError as e:
        return False, f"Failed to pull chart: {e.stderr}"


def _pull_traditional_for_values(
    repo_url: str, chart_name: str, version: str, temp_path: Path
) -> tuple[bool, str]:
    helm_config: Path = temp_path / "helm-config"
    helm_env: dict[str, str] = _create_isolated_helm_env(helm_config)

    temp_repo_name = "rita-temp-repo"

    if not _add_helm_repo(temp_repo_name, repo_url, helm_env):
        return False, f"Failed to add helm repo: {repo_url}"

    _update_helm_repo(temp_repo_name, helm_env)

    cmd = [
        "helm",
        "pull",
        f"{temp_repo_name}/{chart_name}",
        "--version",
        version,
        "--destination",
        str(temp_path),
        "--untar",
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, env=helm_env)
        return _find_chart_dir(temp_path, exclude="helm-config")
    except subprocess.CalledProcessError as e:
        return False, f"Failed to pull chart: {e.stderr}"


def _find_chart_dir(temp_path: Path, exclude: str | None = None) -> tuple[bool, str]:
    subdirs = [
        d
        for d in temp_path.iterdir()
        if d.is_dir() and (exclude is None or d.name != exclude)
    ]
    if not subdirs:
        return False, "Chart extracted but no directory found"
    return True, str(subdirs[0])


# ============================================================================
# ApplicationSet Rendering Support
# ============================================================================


def render_helm_chart_to_string(
    app: ArgoAppConfig,
    repo_root: Path,
    chart_path_resolver: Callable[[str], Path],
    include_crds: bool = True,
) -> tuple[bool, str, str]:
    """Render a Helm chart and return the rendered content as a string.

    Returns (success, rendered_content, error_message).
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        success, prep_msg, chart_path = prepare_chart_for_rendering(
            app, temp_path, chart_path_resolver
        )
        if not success:
            return False, "", prep_msg

        if chart_path is None:
            return False, "", "Chart path not set"

        for vf in app.values_files:
            values_path = repo_root / vf
            if not values_path.exists():
                return False, "", f"Values file not found: {values_path}"

        cmd: list[str] = _build_template_command(
            app, chart_path, repo_root, include_crds
        )

        if app.values_object:
            values_file: Path = temp_path / "inline-values.yaml"
            with values_file.open("w", encoding="utf-8") as f:
                yaml.safe_dump(app.values_object, f, default_flow_style=False)
            cmd.extend(["--values", str(values_file)])

        try:
            result: CompletedProcess[str] = subprocess.run(
                cmd, capture_output=True, text=True, check=True, cwd=str(repo_root)
            )
            return True, result.stdout, prep_msg
        except subprocess.CalledProcessError as e:
            return False, "", f"Helm template failed: {e.stderr}"
        except FileNotFoundError:
            return False, "", "helm command not found. Please install Helm."


def render_application_with_appset_expansion(
    app: ArgoAppConfig,
    output_dir: Path,
    repo_root: Path,
    chart_path_resolver: Callable[[str], Path],
    include_crds: bool = True,
) -> tuple[bool, str, list[ArgoAppConfig]]:
    """Render an Application and expand any ApplicationSets it produces.

    This is the main entry point for expanded rendering. It:
    1. Renders the Application's chart
    2. If the rendered output contains ApplicationSets, parses them
    3. For each ApplicationSet, extracts child Application configs
    4. Renders each child Application's chart
    5. Combines all manifests into the output directory

    Returns (success, message, list of child apps that were rendered).
    """
    success, rendered_content, msg = render_helm_chart_to_string(
        app, repo_root, chart_path_resolver, include_crds
    )

    if not success:
        return False, msg, []

    appset: ArgoAppSetConfig | None = parse_applicationset_from_manifest(
        rendered_content, app.source_file
    )

    if not appset:
        doc_count: int = _write_rendered_output(rendered_content, output_dir)
        return True, f"Rendered {doc_count} resources ({msg})", []

    child_apps: list[ArgoAppConfig] = appset.to_app_configs(
        chart_path_resolver, repo_root
    )

    appset_dir: Path = output_dir / "_applicationset"
    appset_dir.mkdir(parents=True, exist_ok=True)
    _write_rendered_output(rendered_content, appset_dir)

    rendered_children = []
    all_child_content = []
    child_errors = []

    for child_app in child_apps:
        child_output_dir: Path = output_dir / child_app.name
        child_success, child_rendered, child_msg = render_helm_chart_to_string(
            child_app, repo_root, chart_path_resolver, include_crds
        )

        if child_success:
            _write_rendered_output(child_rendered, child_output_dir)
            all_child_content.append(f"# === {child_app.name} ===\n{child_rendered}")
            rendered_children.append(child_app)
        else:
            child_errors.append(f"{child_app.name}: {child_msg}")

    combined_content = rendered_content + "\n---\n" + "\n---\n".join(all_child_content)
    all_file: Path = output_dir / "_all.yaml"
    with all_file.open("w", encoding="utf-8") as f:
        f.write(combined_content)

    child_names = ", ".join(c.name for c in rendered_children)
    error_msg = ""
    if child_errors:
        error_msg = f" (errors: {'; '.join(child_errors)})"

    if len(child_apps) > 0 and len(rendered_children) == 0:
        return (
            True,
            f"ApplicationSet with {len(child_apps)} children, all failed to render{error_msg}",
            [],
        )

    return (
        True,
        f"Rendered ApplicationSet with {len(rendered_children)} children: {child_names}{error_msg}",
        rendered_children,
    )


def is_appset_producing_app(app: ArgoAppConfig) -> bool:
    """Check if an Application uses a chart that produces ApplicationSets."""
    return is_applicationset_chart(app.chart_name) or is_applicationset_chart(
        app.oci_chart_name or ""
    )


def render_with_appset_detection(
    app: ArgoAppConfig,
    output_dir: Path,
    repo_root: Path,
    chart_path_resolver: Callable[[str], Path],
    expand_appsets: bool = False,
    include_crds: bool = True,
) -> tuple[bool, str]:
    """Render an Application, optionally expanding ApplicationSets.

    This is a convenience function that:
    - If expand_appsets is True and the app produces an ApplicationSet,
      uses render_application_with_appset_expansion
    - Otherwise uses the standard render_helm_chart

    Returns (success, message).
    """
    if expand_appsets and is_appset_producing_app(app):
        success, msg, _ = render_application_with_appset_expansion(
            app, output_dir, repo_root, chart_path_resolver, include_crds
        )
        return success, msg
    else:
        return render_helm_chart(
            app, output_dir, repo_root, chart_path_resolver, include_crds
        )


# ============================================================================
# Recursive Rendering (App-of-Apps Pattern)
# ============================================================================


def _render_child_app(
    child_app: ArgoAppConfig,
    output_dir: Path,
    repo_root: Path,
    chart_path_resolver: Callable[[str], Path],
    include_crds: bool,
    max_depth: int,
    current_depth: int,
) -> tuple[str, bool, str, list[str]]:
    """Render a single child app. Returns (app_name, success, msg, rendered_names)."""
    child_output_dir: Path = output_dir / child_app.name
    success, msg, grandchildren = render_recursive(
        child_app,
        child_output_dir,
        repo_root,
        chart_path_resolver,
        include_crds,
        max_depth,
        current_depth + 1,
    )
    return child_app.name, success, msg, grandchildren


def render_recursive(
    app: ArgoAppConfig,
    output_dir: Path,
    repo_root: Path,
    chart_path_resolver: Callable[[str], Path],
    include_crds: bool = True,
    max_depth: int = 5,
    current_depth: int = 0,
    parallel: bool = True,
    max_workers: int = 4,
) -> tuple[bool, str, list[str]]:
    """Recursively render an Application and all nested Applications/ApplicationSets.

    This handles the app-of-apps pattern where a parent Application may produce:
    - Child Application resources
    - ApplicationSet resources (which in turn produce multiple Applications)

    The function will:
    1. Render the root Application
    2. Parse the rendered output for Application and ApplicationSet resources
    3. Recursively render each discovered Application (in parallel if enabled)
    4. For ApplicationSets, expand and recursively render each child Application
    5. Continue until no more nested resources are found or max_depth is reached

    Args:
        parallel: Enable parallel rendering of child apps (default True)
        max_workers: Maximum number of parallel workers (default 4)

    Returns (success, message, list of all rendered app names).
    """
    if current_depth >= max_depth:
        return True, f"Max recursion depth ({max_depth}) reached", []

    success, rendered_content, msg = render_helm_chart_to_string(
        app, repo_root, chart_path_resolver, include_crds
    )

    if not success:
        return False, msg, []

    _write_rendered_output(rendered_content, output_dir)
    child_apps, child_appsets = parse_argocd_resources_from_manifest(
        rendered_content, app.source_file, chart_path_resolver
    )

    all_child_apps: list[ArgoAppConfig] = list(child_apps)
    for appset in child_appsets:
        appset_children: list[ArgoAppConfig] = appset.to_app_configs(
            chart_path_resolver, repo_root
        )
        all_child_apps.extend(appset_children)

    all_rendered = [app.name]
    child_errors = []

    if all_child_apps:
        if parallel and len(all_child_apps) > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        _render_child_app,
                        child_app,
                        output_dir,
                        repo_root,
                        chart_path_resolver,
                        include_crds,
                        max_depth,
                        current_depth,
                    ): child_app.name
                    for child_app in all_child_apps
                }

                for future in as_completed(futures):
                    try:
                        app_name, child_success, child_msg, grandchildren = (
                            future.result()
                        )
                        if child_success:
                            all_rendered.extend(grandchildren)
                        else:
                            child_errors.append(f"{app_name}: {child_msg}")
                    except Exception as e:
                        if isinstance(e, AWSTokenExpiredError):
                            raise
                        if hasattr(e, "__cause__") and isinstance(
                            e.__cause__, AWSTokenExpiredError
                        ):
                            raise e.__cause__ from None
                        app_name = futures[future]
                        child_errors.append(f"{app_name}: {e}")
        else:
            for child_app in all_child_apps:
                app_name, child_success, child_msg, grandchildren = _render_child_app(
                    child_app,
                    output_dir,
                    repo_root,
                    chart_path_resolver,
                    include_crds,
                    max_depth,
                    current_depth,
                )
                if child_success:
                    all_rendered.extend(grandchildren)
                else:
                    child_errors.append(f"{app_name}: {child_msg}")

        _write_combined_recursive_output(output_dir)

    total_children: int = len(all_child_apps)

    if total_children > 0:
        error_msg: str = f" (errors: {'; '.join(child_errors)})" if child_errors else ""
        return (
            True,
            f"Rendered with {len(all_rendered) - 1} nested resources{error_msg}",
            all_rendered,
        )
    else:
        return True, msg, all_rendered


def _write_combined_recursive_output(output_dir: Path) -> None:
    all_content = []

    parent_all: Path = output_dir / "_all.yaml"
    if parent_all.exists():
        with parent_all.open(encoding="utf-8") as f:
            all_content.append(f.read())

    for child_dir in sorted(output_dir.iterdir()):
        if child_dir.is_dir() and not child_dir.name.startswith("_"):
            child_all: Path = child_dir / "_all.yaml"
            if child_all.exists():
                with child_all.open(encoding="utf-8") as f:
                    all_content.append(f"# === {child_dir.name} ===\n{f.read()}")

    if all_content:
        with parent_all.open("w", encoding="utf-8") as f:
            f.write("\n---\n".join(all_content))
