"""Render commands for Helm chart manifest generation and diffing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rich_click as click
import yaml

from rita import console as con
from rita.config import RitaConfig, get_canonical_env_name, load_config
from rita.helm import (
    render_helm_chart,
    render_recursive,
    render_with_appset_detection,
)
from rita.kustomize import render_kustomize, render_plain_manifests
from rita.repository import (
    get_chart_path,
    get_rendered_path,
    get_repo_root,
    list_apps_for_env,
    list_available_envs,
)
from rita.storage import (
    AWSTokenExpiredError,
    ManifestRef,
    S3StorageBackend,
    StorageBackend,
    create_storage_backend,
)


@click.group()
def render() -> None:
    pass


@dataclass
class RenderResult:
    app_name: str
    success: bool
    message: str
    rel_path: str | None = None
    nested_count: int = 0


def _render_single_app(
    app: Any,
    env: str,
    recursive: bool,
    repo_root: Path,
) -> RenderResult:
    output_path: Path = get_rendered_path(env, app.name)

    if output_path.exists():
        shutil.rmtree(output_path)

    has_helm = bool(app.chart_name)
    has_kustomize = bool(app.is_kustomize and app.kustomize_path)
    has_plain = bool(app.plain_manifests_path)
    source_count: int = sum([has_helm, has_kustomize, has_plain])

    if source_count > 1:
        with tempfile.TemporaryDirectory() as tmpdir:
            helm_dir: Path = Path(tmpdir) / "helm"
            kustomize_dir: Path = Path(tmpdir) / "kustomize"
            plain_dir: Path = Path(tmpdir) / "plain"
            helm_dir.mkdir()
            kustomize_dir.mkdir()
            plain_dir.mkdir()

            if has_helm:
                if recursive:
                    helm_success, helm_msg, all_apps = render_recursive(
                        app=app,
                        output_dir=helm_dir,
                        repo_root=repo_root,
                        chart_path_resolver=get_chart_path,
                    )
                else:
                    helm_success, helm_msg = render_with_appset_detection(
                        app=app,
                        output_dir=helm_dir,
                        repo_root=repo_root,
                        chart_path_resolver=get_chart_path,
                        expand_appsets=False,
                    )

                if not helm_success:
                    return RenderResult(
                        app_name=app.name,
                        success=False,
                        message=f"Helm rendering failed: {helm_msg}",
                        rel_path=None,
                    )

            if has_kustomize:
                kustomize_full_path: Any = repo_root / app.kustomize_path
                kustomize_success, kustomize_msg = render_kustomize(
                    kustomize_full_path, kustomize_dir
                )

                if not kustomize_success:
                    return RenderResult(
                        app_name=app.name,
                        success=False,
                        message=f"Kustomize rendering failed: {kustomize_msg}",
                        rel_path=None,
                    )

            if has_plain:
                plain_full_path: Any = repo_root / app.plain_manifests_path
                plain_success, plain_msg = render_plain_manifests(
                    plain_full_path, plain_dir
                )

                if not plain_success:
                    return RenderResult(
                        app_name=app.name,
                        success=False,
                        message=f"Plain YAML rendering failed: {plain_msg}",
                        rel_path=None,
                    )

            output_path.mkdir(parents=True, exist_ok=True)

            combined_content = []
            source_dirs = []
            if has_helm:
                source_dirs.append(helm_dir)
            if has_kustomize:
                source_dirs.append(kustomize_dir)
            if has_plain:
                source_dirs.append(plain_dir)

            for src_dir in source_dirs:
                all_yaml = src_dir / "_all.yaml"
                if all_yaml.exists():
                    combined_content.append(
                        all_yaml.read_text(encoding="utf-8").strip()
                    )

            combined_all: Path = output_path / "_all.yaml"
            combined_all.write_text("\n---\n".join(combined_content), encoding="utf-8")

            from shutil import copy2

            for src_dir in source_dirs:
                for yaml_file in src_dir.glob("*.yaml"):
                    if yaml_file.name != "_all.yaml":
                        dest: Path = output_path / yaml_file.name
                        if dest.exists():
                            existing: str = dest.read_text(encoding="utf-8").strip()
                            new = yaml_file.read_text(encoding="utf-8").strip()
                            dest.write_text(f"{existing}\n---\n{new}", encoding="utf-8")
                        else:
                            copy2(yaml_file, dest)

            rel_path = str(output_path.relative_to(repo_root))

            sources = []
            if has_helm:
                sources.append("Helm")
            if has_kustomize:
                sources.append("Kustomize")
            if has_plain:
                sources.append("Plain YAML")

            return RenderResult(
                app_name=app.name,
                success=True,
                message=f"Rendered {' + '.join(sources)}",
                rel_path=rel_path,
            )

    if has_kustomize:
        kustomize_full_path: Any = repo_root / app.kustomize_path
        success, msg = render_kustomize(kustomize_full_path, output_path)
        rel_path: str | None = (
            str(output_path.relative_to(repo_root)) if success else None
        )
        return RenderResult(
            app_name=app.name,
            success=success,
            message=msg,
            rel_path=rel_path,
        )

    if has_plain:
        plain_full_path: Any = repo_root / app.plain_manifests_path
        success, msg = render_plain_manifests(plain_full_path, output_path)
        rel_path: str | None = (
            str(output_path.relative_to(repo_root)) if success else None
        )
        return RenderResult(
            app_name=app.name,
            success=success,
            message=msg,
            rel_path=rel_path,
        )

    if recursive:
        success, msg, all_apps = render_recursive(
            app=app,
            output_dir=output_path,
            repo_root=repo_root,
            chart_path_resolver=get_chart_path,
        )
        rel_path = str(output_path.relative_to(repo_root))
        return RenderResult(
            app_name=app.name,
            success=success,
            message=msg,
            rel_path=rel_path,
            nested_count=len(all_apps) if success else 0,
        )
    else:
        success, msg = render_with_appset_detection(
            app=app,
            output_dir=output_path,
            repo_root=repo_root,
            chart_path_resolver=get_chart_path,
            expand_appsets=False,
        )
        rel_path: str | None = (
            str(output_path.relative_to(repo_root)) if success else None
        )
        return RenderResult(
            app_name=app.name,
            success=success,
            message=msg,
            rel_path=rel_path,
        )


def _render_applications(
    env: str,
    app_filter: str | None,
    dry_run: bool,
    recursive: bool = False,
    workers: int = 1,
) -> tuple[int, int]:
    apps = list_apps_for_env(env)

    if app_filter:
        apps = [a for a in apps if app_filter.lower() in a.name.lower()]

    if not apps:
        con.print_warning(f"No applications found in {con.format_env(env)}")
        return 0, 0

    success_count = 0
    failure_count = 0
    repo_root: Path = get_repo_root()

    if dry_run:
        for app in apps:
            output_path: Path = get_rendered_path(env, app.name)
            indicator = " [recursive]" if recursive else ""
            con.print_info(
                f"Would render: {app.name}{indicator} → {output_path.relative_to(repo_root)}"
            )
            success_count += 1
        return success_count, failure_count

    if workers > 1:
        results: list[RenderResult] = []

        with con.status(f"Rendering {len(apps)} apps with {workers} workers..."), ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        _render_single_app, app, env, recursive, repo_root
                    ): app
                    for app in apps
                }

                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)

        for result in sorted(results, key=lambda r: r.app_name):
            if result.success:
                con.print_success(f"{result.app_name} → {result.rel_path}")
                if result.nested_count > 1:
                    con.print_info(f"  ↳ {result.message}")
                success_count += 1
            else:
                con.print_error(f"{result.app_name}: {result.message}")
                failure_count += 1
    else:
        for app in apps:
            with con.status(f"Rendering {app.name}..."):
                result = _render_single_app(app, env, recursive, repo_root)

            if result.success:
                con.print_success(f"{result.app_name} → {result.rel_path}")
                if result.message and result.nested_count > 1:
                    con.print_info(f"  ↳ {result.message}")
                success_count += 1
            else:
                con.print_error(f"{result.app_name}: {result.message}")
                failure_count += 1

    return success_count, failure_count


@render.command("list")
@click.option(
    "--env", "-e", default="dev", help="Environment to list applications for."
)
@click.option(
    "--all-envs", is_flag=True, help="List applications for all environments."
)
def render_list(env: str, all_envs: bool) -> None:
    """List ArgoCD applications that can be rendered."""
    if all_envs or env == "all":
        envs_to_list: list[str] = list_available_envs()
    else:
        envs_to_list = [env]

    for current_env in envs_to_list:
        apps = list_apps_for_env(current_env)

        if not apps:
            con.print_warning(f"No applications found in {con.format_env(current_env)}")
            continue

        con.print_header(f"Applications in {current_env}")

        app_data = [
            (
                app.name,
                app.chart_name,
                app.chart_version,
                app.namespace,
                app.is_local_chart,
                app.values_files,
            )
            for app in apps
        ]
        con.print_app_list(app_data)


@render.command("apply")
@click.option("--env", "-e", default="dev", help="Environment to render.")
@click.option("--all-envs", is_flag=True, help="Render all environments.")
@click.option("--app", "-a", "app_filter", help="Filter applications by name.")
@click.option("--dry-run", is_flag=True, help="Show what would be rendered.")
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    help="Recursively render all nested Applications and ApplicationSets (app-of-apps pattern).",
)
@click.option(
    "--workers",
    "-w",
    default=1,
    help="Number of parallel workers for rendering.",
)
@click.option(
    "--expand-appsets",
    is_flag=True,
    hidden=True,
    help="Alias for --recursive.",
)
def render_apply(
    env: str,
    all_envs: bool,
    app_filter: str | None,
    dry_run: bool,
    recursive: bool,
    workers: int,
    expand_appsets: bool,
) -> None:
    """Render Helm charts to Kubernetes manifests.

    For Applications that produce nested Applications or ApplicationSets
    (like app-of-apps or feature-deployment patterns), use --recursive
    to render all nested resources recursively.

    Use --workers to parallelize rendering for faster execution when
    rendering many applications.

    Examples:
        rita render apply --env dev
        rita render apply --app feature-patient-app --recursive
        rita render apply --all-envs -r
        rita render apply --all-envs --recursive --workers 8
    """
    recursive = recursive or expand_appsets

    if all_envs or env == "all":
        envs_to_render: list[str] = list_available_envs()
    else:
        envs_to_render = [env]

    total_success = 0
    total_failure = 0

    if recursive:
        con.print_info(
            "Recursive rendering enabled (expands Applications & ApplicationSets)"
        )
        con.console.print()

    if workers > 1:
        con.print_info(f"Using {workers} parallel workers")

    try:
        for current_env in envs_to_render:
            con.print_header(f"Rendering {current_env}")
            success, failure = _render_applications(
                current_env, app_filter, dry_run, recursive, workers
            )
            total_success += success
            total_failure += failure
            con.console.print()
    except AWSTokenExpiredError as e:
        con.console.print()
        con.print_error(str(e))
        con.print_hint("After logging in, run the command again.")
        raise SystemExit(1) from None

    if total_failure > 0:
        con.print_warning(
            f"Completed: {total_success} succeeded, {total_failure} failed"
        )
        raise SystemExit(1)
    else:
        con.print_success(f"Rendered {total_success} applications")


@render.command("push")
@click.option("--env", "-e", default="dev", help="Environment to push.")
@click.option("--all-envs", is_flag=True, help="Push all environments.")
@click.option("--branch", "-b", help="Branch name for the manifest set.")
@click.option("--dry-run", is_flag=True, help="Show what would be pushed.")
def render_push(env: str, all_envs: bool, branch: str | None, dry_run: bool) -> None:
    """Push rendered manifests to S3 storage."""
    cfg: RitaConfig = load_config()

    if not cfg.render.storage:
        con.print_error("Storage not configured. Run: rita config setup")
        raise SystemExit(1)

    backend: StorageBackend = create_storage_backend(cfg)

    if not branch:
        branch: str | None = os.environ.get("GITHUB_HEAD_REF") or os.environ.get(
            "GITHUB_REF_NAME"
        )
        if not branch:
            import subprocess

            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                branch = result.stdout.strip()
            except subprocess.CalledProcessError:
                con.print_error("Could not determine branch name. Use --branch.")
                raise SystemExit(1) from None

    con.print_key_value("Branch", branch)
    con.print_key_value("Bucket", cfg.render.storage.s3_bucket or "")
    con.console.print()

    if not isinstance(backend, S3StorageBackend):
        con.print_error("Push command requires S3 storage backend")
        raise SystemExit(1)

    envs_to_push = list_available_envs() if all_envs or env == "all" else [env]

    repo_root: Path = get_repo_root()

    for current_env in envs_to_push:
        rendered_dir = repo_root / "rendered" / current_env

        if not rendered_dir.exists():
            con.print_warning(f"No rendered manifests for {current_env}")
            continue

        all_yaml_files = list(rendered_dir.rglob("_all.yaml"))

        if not all_yaml_files:
            con.print_warning(f"No _all.yaml files in {rendered_dir}")
            continue

        con.print_header(f"Pushing {current_env}")

        for manifest_file in all_yaml_files:
            rel_to_env = manifest_file.relative_to(rendered_dir)
            s3_key = f"{current_env}/{rel_to_env}"

            if dry_run:
                con.print_info(f"Would push: {current_env}/{rel_to_env}")
            else:
                with manifest_file.open(encoding="utf-8") as f:
                    content: str = f.read()
                backend.upload_manifest(s3_key, content)
                con.print_success(f"Pushed: {current_env}/{rel_to_env}")

    if not dry_run:
        con.console.print()
        con.print_success("Push complete")


@render.command("pull")
@click.option("--env", "-e", default="dev", help="Environment to pull.")
@click.option("--all-envs", is_flag=True, help="Pull all environments.")
@click.option(
    "--branch", "-b", required=True, help="Branch name to pull manifests from."
)
@click.option("--output", "-o", type=click.Path(), help="Output directory.")
def render_pull(env: str, all_envs: bool, branch: str, output: str | None) -> None:
    """Pull rendered manifests from S3 storage."""
    cfg = load_config()

    if not cfg.render.storage:
        con.print_error("Storage not configured. Run: rita config setup")
        raise SystemExit(1)

    backend = create_storage_backend(cfg)

    envs_to_pull = list_available_envs() if all_envs or env == "all" else [env]

    repo_root: Path = get_repo_root()
    output_dir: Path = Path(output) if output else repo_root / ".rita-compare" / branch

    con.print_key_value("Branch", branch)
    con.print_key_value("Output", str(output_dir))
    con.console.print()

    if not isinstance(backend, S3StorageBackend):
        con.print_error("Pull command requires S3 storage backend")
        raise SystemExit(1)

    for current_env in envs_to_pull:
        con.print_header(f"Pulling {current_env}")

        prefix = f"{branch}/rendered/{current_env}/"
        manifest_keys = backend.list_manifest_keys(prefix)

        if not manifest_keys:
            con.print_warning(f"No manifests found for {current_env}")
            continue

        for s3_key in manifest_keys:
            rel_path = s3_key.replace(f"{branch}/", "")
            local_path = output_dir / rel_path

            local_path.parent.mkdir(parents=True, exist_ok=True)

            content = backend.download_manifest(s3_key)
            if content is None:
                con.print_warning(f"Failed to download: {s3_key}")
                continue

            with local_path.open("w", encoding="utf-8") as f:
                f.write(content)

            con.print_success(f"Pulled: {rel_path}")

    con.console.print()
    con.print_success(f"Manifests saved to: {output_dir}")


@dataclass
class DiffResult:
    """Result of a single app diff operation."""

    env: str
    app_name: str
    has_diff: bool
    diff_content: str
    error: str | None = None
    changed_files: list[str] | None = None


def _get_manifest_name(doc: dict) -> str:
    """Get a human-readable name for a Kubernetes manifest."""
    kind = doc.get("kind", "Unknown")
    metadata = doc.get("metadata", {})
    name = metadata.get("name", "unnamed")
    namespace = metadata.get("namespace", "")
    if namespace:
        return f"{kind}/{namespace}/{name}"
    return f"{kind}/{name}"


def _diff_manifests(
    baseline_content: str,
    new_content: str,
    max_lines_per_manifest: int = 250,
) -> tuple[bool, str]:
    """Diff YAML content at the manifest level.

    Instead of diffing the whole file, split by '---' and diff each
    manifest individually. Only show manifests that have changes.
    """
    import difflib

    baseline_docs_raw = baseline_content.split("\n---\n")
    new_docs_raw = new_content.split("\n---\n")

    def parse_docs(docs_raw: list[str]) -> dict[str, tuple[str, dict]]:
        result = {}
        for raw in docs_raw:
            raw = raw.strip()
            if not raw:
                continue
            try:
                doc = yaml.safe_load(raw)
                if doc and isinstance(doc, dict):
                    identity = _get_manifest_name(doc)
                    result[identity] = (raw, doc)
            except yaml.YAMLError:
                result[f"unparseable-{hash(raw)}"] = (raw, {})
        return result

    baseline_docs = parse_docs(baseline_docs_raw)
    new_docs = parse_docs(new_docs_raw)

    all_identities = set(baseline_docs.keys()) | set(new_docs.keys())

    diffs = []
    for identity in sorted(all_identities):
        baseline_raw = baseline_docs.get(identity, ("", {}))[0]
        new_raw = new_docs.get(identity, ("", {}))[0]

        if baseline_raw == new_raw:
            continue

        baseline_lines = baseline_raw.splitlines(keepends=True) if baseline_raw else []
        new_lines = new_raw.splitlines(keepends=True) if new_raw else []

        if not baseline_raw:
            diff_lines = [f"+++ NEW: {identity}\n"]
            for line in new_lines[:max_lines_per_manifest]:
                diff_lines.append(f"+{line.rstrip()}\n")
            if len(new_lines) > max_lines_per_manifest:
                diff_lines.append(
                    f"... ({len(new_lines) - max_lines_per_manifest} more lines)\n"
                )
        elif not new_raw:
            diff_lines = [f"--- REMOVED: {identity}\n"]
            for line in baseline_lines[:max_lines_per_manifest]:
                diff_lines.append(f"-{line.rstrip()}\n")
            if len(baseline_lines) > max_lines_per_manifest:
                diff_lines.append(
                    f"... ({len(baseline_lines) - max_lines_per_manifest} more lines)\n"
                )
        else:
            diff: list[str] = list(
                difflib.unified_diff(
                    baseline_lines,
                    new_lines,
                    fromfile=f"baseline/{identity}",
                    tofile=f"current/{identity}",
                    n=150,
                )
            )
            if diff:
                if len(diff) > max_lines_per_manifest:
                    diff: list[str] = diff[:max_lines_per_manifest]
                    diff.append(
                        f"... (truncated, showing first {max_lines_per_manifest} lines)\n"
                    )
                diff_lines: list[str] = diff
            else:
                continue

        diffs.append("".join(diff_lines))

    if not diffs:
        return False, ""

    return True, "\n".join(diffs)


def _get_changed_files_from_git(base_ref: str) -> list[str]:
    """Get list of files changed between current branch and base ref.

    Uses three-dot syntax to compare from merge-base, showing only changes
    in the current branch (like GitHub PR diffs).
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except subprocess.CalledProcessError:
        return []


def _find_affected_apps(
    changed_files: list[str], envs: list[str]
) -> list[tuple[str, Any, str]]:
    affected = []

    for env in envs:
        apps = list_apps_for_env(env)
        for app in apps:
            for changed_file in changed_files:
                conditions = [
                    app.is_local_chart
                    and changed_file.startswith(f"charts/{app.chart_name}/"),
                    changed_file.startswith(f"kubernetes/{app.name}/"),
                    changed_file in app.values_files,
                ]

                if any(conditions):
                    affected.append((env, app, changed_file))
                    break

    return affected


def _read_combined_manifest(directory: Path) -> str:
    """Read the combined _all.yaml manifest from a rendered directory."""
    all_yaml = directory / "_all.yaml"
    if all_yaml.exists():
        return all_yaml.read_text(encoding="utf-8")
    return ""


def _diff_single_app(args: tuple) -> DiffResult:
    """Diff a single app against S3 baseline."""
    import tempfile

    (
        env,
        app_name,
        _chart_name,
        _chart_repo,
        _chart_version,
        _values_files,
        _namespace,
        _release_name,
        _is_local_chart,
        _base_ref,
        recursive,
    ) = args

    try:
        cfg = load_config()
        backend = create_storage_backend(cfg)
        repo_root = get_repo_root()

        apps = list_apps_for_env(env)
        app = next((a for a in apps if a.name == app_name), None)

        if not app:
            return DiffResult(
                env=env,
                app_name=app_name,
                has_diff=False,
                diff_content="",
                error="App not found",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            render_dir = Path(tmpdir) / "render"
            render_dir.mkdir()

            if app.is_kustomize:
                kustomize_full_path = repo_root / app.kustomize_path
                success, msg = render_kustomize(kustomize_full_path, render_dir)

            elif recursive:
                success, msg, _ = render_recursive(
                    app=app,
                    output_dir=render_dir,
                    repo_root=repo_root,
                    chart_path_resolver=get_chart_path,
                )
            else:
                success, msg = render_helm_chart(
                    app=app,
                    output_dir=render_dir,
                    repo_root=repo_root,
                    chart_path_resolver=get_chart_path,
                )

            if not success:
                return DiffResult(
                    env=env,
                    app_name=app_name,
                    has_diff=False,
                    diff_content="",
                    error=msg,
                )

            current_combined: str = _read_combined_manifest(render_dir)
            current_file: Path = Path(tmpdir) / "current.yaml"
            current_file.write_text(current_combined, encoding="utf-8")
            ref = ManifestRef(env=env, app_name=app_name, git_ref=None)

            if not backend.exists(ref):
                return DiffResult(
                    env=env,
                    app_name=app_name,
                    has_diff=True,
                    diff_content="New app (no baseline in S3)",
                )

            baseline_content = backend.read(ref) or ""

            has_diff, diff_content = _diff_manifests(baseline_content, current_combined)

            return DiffResult(
                env=env, app_name=app_name, has_diff=has_diff, diff_content=diff_content
            )

    except Exception as e:
        return DiffResult(
            env=env, app_name=app_name, has_diff=False, diff_content="", error=str(e)
        )


def _format_github_diff(
    results: list[DiffResult], changed_files: list[str], elapsed: float, workers: int
) -> str:
    lines = []

    results_with_diff = [r for r in results if r.has_diff and not r.error]
    results_with_error = [r for r in results if r.error]

    if not results_with_diff and not results_with_error:
        return "✅ **No manifest changes detected**\n\nNo apps were affected by the changes in this branch."

    lines.append("## 📦 Helm Manifest Changes\n")

    by_env: dict[str, list[DiffResult]] = {}
    for r in results_with_diff:
        by_env.setdefault(r.env, []).append(r)

    lines.append("| Environment | Apps Changed | Changed Files |")
    lines.append("|-------------|--------------|---------------|")

    for env, env_results in sorted(by_env.items()):
        env_icon = "🔧" if env == "dev" else "🚀" if env == "prod" else "📦"
        env_files = set()
        for cf in changed_files:
            if any(env in cf or app.app_name in cf for app in env_results):
                env_files.add(cf)
        files_str = ", ".join(f"`{f}`" for f in sorted(env_files)[:3])
        if len(env_files) > 3:
            files_str += f" (+{len(env_files) - 3} more)"
        lines.append(f"| {env_icon} {env} | {len(env_results)} | {files_str} |")

    lines.append("")

    for env, env_results in sorted(by_env.items()):
        lines.append(f"### {env}\n")

        for r in env_results:
            lines.append("<details>")
            lines.append(f"<summary><b>{r.app_name}</b></summary>\n")
            lines.append("```diff")
            lines.append(r.diff_content if r.diff_content else "(no diff content)")
            lines.append("```\n")
            lines.append("</details>\n")

    if results_with_error:
        lines.append("\n### ⚠️ Errors\n")
        for r in results_with_error:
            lines.append(f"- **{r.env}/{r.app_name}**: {r.error}")

    lines.append("\n---")
    lines.append(
        f"<sub>Checked {len(results)} apps in {elapsed:.1f}s using {workers} workers</sub>"
    )

    return "\n".join(lines)


@render.command("diff")
@click.option("--app", "-a", "app_name", help="Name of the application to diff.")
@click.option("--env", "-e", "env_name", help="Environment to diff (supports aliases).")
@click.option("--base-ref", "-b", "base_ref", help="Git reference to compare against.")
@click.option("--workers", "-w", default=4, help="Number of parallel workers.")
@click.option(
    "--changed-only", is_flag=True, help="Only diff apps affected by changed files."
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    help="Recursively render and diff all nested Applications/ApplicationSets.",
)
@click.option(
    "--expand-appsets",
    is_flag=True,
    hidden=True,
    help="Alias for --recursive.",
)
@click.option(
    "--output-format",
    "-f",
    type=click.Choice(["text", "json", "github"]),
    default="text",
    help="Output format.",
)
def render_diff(
    app_name: str | None,
    env_name: str | None,
    base_ref: str | None,
    workers: int,
    changed_only: bool,
    recursive: bool,
    expand_appsets: bool,
    output_format: str,
) -> None:
    """Compare rendered manifests against S3 baseline (main branch).

    For Applications that produce nested Applications or ApplicationSets,
    use --recursive to render and diff all nested resources.

    Examples:
        rita render diff --app patient-app-stack --env dev
        rita render diff --env prod --workers 8
        rita render diff --changed-only --output-format github
        rita render diff --recursive --output-format github
    """
    recursive: bool = recursive or expand_appsets
    config: RitaConfig = load_config()

    if not config.render.storage or config.render.storage.type != "s3":
        con.print_error("S3 storage is not configured.")
        con.print_hint("Run: rita config setup")
        raise SystemExit(1)

    if not base_ref:
        base_ref: str = config.render.compare_branch

    if env_name:
        canonical_env: str = get_canonical_env_name(config, env_name)
        envs = [canonical_env]
    else:
        envs: list[str] = list_available_envs()

    changed_files: list[str] = []

    if changed_only:
        changed_files: list[str] = _get_changed_files_from_git(f"origin/{base_ref}")
        affected: list[tuple[str, Any, str]] = _find_affected_apps(changed_files, envs)

        if not affected:
            if output_format == "json":
                click.echo(
                    json.dumps(
                        {
                            "has_diff": False,
                            "results": [],
                            "message": "No affected apps found",
                        }
                    )
                )
            elif output_format == "github":
                click.echo(
                    "✅ **No manifest changes detected**\n\nNo apps were affected by the changes in this branch."
                )
            else:
                con.print_success("No apps affected by changes.")
            return

        apps_to_diff = [(env, app) for env, app, _ in affected]
        click.echo(
            f"Found {len(apps_to_diff)} affected apps from {len(changed_files)} changed files",
            err=True,
        )
    elif app_name:
        apps_to_diff = []
        for env in envs:
            apps = list_apps_for_env(env)
            for app in apps:
                if app.name == app_name and app.is_local_chart:
                    apps_to_diff.append((env, app))

        if not apps_to_diff:
            con.print_error(
                f"Application '{app_name}' not found or doesn't use a local chart."
            )
            raise SystemExit(1)
    else:
        apps_to_diff = []
        for env in envs:
            apps = list_apps_for_env(env)
            for app in apps:
                if app.is_local_chart:
                    apps_to_diff.append((env, app))

    if not apps_to_diff:
        if output_format == "json":
            click.echo(json.dumps({"has_diff": False, "results": []}))
        elif output_format == "github":
            click.echo("✅ **No apps to diff**\n\nNo local chart applications found.")
        else:
            con.print_warning("No apps to diff.")
        return

    diff_args = [
        (
            env,
            app.name,
            app.chart_name,
            app.chart_repo,
            app.chart_version,
            app.values_files,
            app.namespace,
            app.release_name,
            app.is_local_chart,
            base_ref,
            recursive,
        )
        for env, app in apps_to_diff
    ]

    start_time: int | float = time.time()
    results: list[DiffResult] = []

    use_spinner: bool = output_format in ("github", "json")

    def _run_diff_with_progress() -> None:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_diff_single_app, args): args for args in diff_args
            }

            for future in as_completed(futures):
                result = future.result()
                results.append(result)

                if output_format == "text":
                    if result.error:
                        click.echo(
                            f"✗ {result.env}/{result.app_name}: {result.error}",
                            err=True,
                        )
                    elif result.has_diff:
                        click.echo(f"⚡ {result.env}/{result.app_name} has changes")
                    else:
                        click.echo(f"✓ {result.env}/{result.app_name} unchanged")
                elif use_spinner and status_updater:
                    status_updater.update(
                        f"Diffing apps... ({len(results)}/{len(diff_args)})"
                    )

    status_updater = None
    if use_spinner:
        with con.status(f"Diffing {len(diff_args)} apps...") as s:
            status_updater = s
            _run_diff_with_progress()
    else:
        _run_diff_with_progress()

    elapsed: int | float = time.time() - start_time

    if output_format == "json":
        output_data = {
            "has_diff": any(r.has_diff for r in results),
            "elapsed_seconds": elapsed,
            "results": [
                {
                    "env": r.env,
                    "app": r.app_name,
                    "has_diff": r.has_diff,
                    "error": r.error,
                }
                for r in results
            ],
        }
        click.echo(json.dumps(output_data, indent=2))
    elif output_format == "github":
        click.echo(_format_github_diff(results, changed_files, elapsed, workers))
    else:
        has_diffs: bool = any(r.has_diff for r in results)
        has_errors: bool = any(r.error for r in results)

        con.console.print()
        if has_errors:
            con.print_warning(f"Completed with errors in {elapsed:.1f}s")
        elif has_diffs:
            con.print_info(
                f"Changes detected in {sum(1 for r in results if r.has_diff)} apps ({elapsed:.1f}s)"
            )
        else:
            con.print_success(f"No changes detected ({elapsed:.1f}s)")


@render.command("clean")
@click.option("--env", "-e", help="Environment to clean.")
@click.option("--all", "clean_all", is_flag=True, help="Clean all rendered manifests.")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted.")
def render_clean(env: str | None, clean_all: bool, dry_run: bool) -> None:
    """Remove rendered manifests."""
    import shutil

    repo_root: Path = get_repo_root()
    rendered_dir: Path = repo_root / "rendered"

    if not rendered_dir.exists():
        con.console.print("No rendered directory found.")
        return

    if clean_all:
        if dry_run:
            con.print_info(f"Would remove: {rendered_dir}")
        else:
            shutil.rmtree(rendered_dir)
            con.print_success("Removed all rendered manifests")
    elif env:
        env_dir: Path = rendered_dir / env
        if not env_dir.exists():
            con.console.print(f"No rendered manifests for {env}")
            return

        if dry_run:
            con.print_info(f"Would remove: {env_dir}")
        else:
            shutil.rmtree(env_dir)
            con.print_success(f"Removed rendered manifests for {env}")
    else:
        con.print_error("Specify --env or --all")
        raise SystemExit(1)
