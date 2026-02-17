"""Kustomize operations for rendering Kubernetes manifests."""

from __future__ import annotations

import subprocess
from subprocess import CompletedProcess
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from pathlib import Path

import yaml


class K8sResource(TypedDict, total=False):
    """Basic Kubernetes resource structure."""

    apiVersion: str
    kind: str
    metadata: dict[str, Any]
    spec: dict[str, Any]
    data: dict[str, Any]
    stringData: dict[str, Any]


def render_kustomize(
    kustomize_path: Path,
    output_dir: Path,
) -> tuple[bool, str]:
    """Render Kustomize manifests to Kubernetes YAML.

    Args:
        kustomize_path: Path to the kustomization directory (containing kustomization.yaml)
        output_dir: Directory where rendered manifests will be written

    Returns:
        Tuple of (success, message)
    """
    if not kustomize_path.exists():
        return False, f"Kustomize path does not exist: {kustomize_path}"

    kustomization_file: Path = kustomize_path / "kustomization.yaml"
    if not kustomization_file.exists():
        return False, f"No kustomization.yaml found in {kustomize_path}"

    cmd: list[str] = ["kubectl", "kustomize", str(kustomize_path)]

    try:
        result: CompletedProcess[str] = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        )
        rendered: str = result.stdout
    except FileNotFoundError:
        try:
            cmd: list[str] = ["kustomize", "build", str(kustomize_path)]
            result: CompletedProcess[str] = subprocess.run(
                cmd, capture_output=True, text=True, check=True
            )
            rendered: str = result.stdout
        except FileNotFoundError:
            return (
                False,
                "Neither 'kubectl kustomize' nor 'kustomize' command found. "
                "Please install kubectl or kustomize CLI.",
            )
        except subprocess.CalledProcessError as e:
            return False, f"Kustomize build failed: {e.stderr}"
    except subprocess.CalledProcessError as e:
        return False, f"Kustomize render failed: {e.stderr}"

    doc_count: int = _write_rendered_output(rendered, output_dir)
    return True, f"Rendered {doc_count} resources from Kustomize"


def _write_rendered_output(rendered: str, output_dir: Path) -> int:
    """Write rendered Kustomize output to files.

    Similar to Helm rendering, writes:
    - Individual files by resource kind
    - Combined _all.yaml file with all resources
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        docs: list[Any] = list(yaml.safe_load_all(rendered))
        by_kind: dict[str, list[K8sResource]] = _group_docs_by_kind(docs)

        for kind, resources in by_kind.items():
            _write_kind_file(output_dir, kind, resources)

        doc_count: int = len([d for d in docs if d])
    except yaml.YAMLError:
        doc_count: int = rendered.count("\n---\n") + 1

    all_file: Path = output_dir / "_all.yaml"
    with all_file.open("w", encoding="utf-8") as f:
        f.write(rendered)

    return doc_count


def _group_docs_by_kind(docs: list[Any]) -> dict[str, list[K8sResource]]:
    by_kind: dict[str, list[K8sResource]] = {}
    for doc in docs:
        if not doc:
            continue
        kind: str = doc.get("kind", "Unknown")
        if kind not in by_kind:
            by_kind[kind] = []
        by_kind[kind].append(doc)
    return by_kind


def _write_kind_file(output_dir: Path, kind: str, resources: list[K8sResource]) -> None:
    kind_file: Path = output_dir / f"{kind.lower()}.yaml"
    with kind_file.open("w", encoding="utf-8") as f:
        for i, resource in enumerate(resources):
            if i > 0:
                f.write("---\n")
            yaml.safe_dump(resource, f, default_flow_style=False, sort_keys=False)


def render_kustomize_to_string(
    kustomize_path: Path,
) -> tuple[bool, str, str]:
    """Render Kustomize manifests and return as string.

    Args:
        kustomize_path: Path to the kustomization directory

    Returns:
        Tuple of (success, rendered_content, error_message)
    """
    if not kustomize_path.exists():
        return False, "", f"Kustomize path does not exist: {kustomize_path}"

    kustomization_file: Path = kustomize_path / "kustomization.yaml"
    if not kustomization_file.exists():
        return False, "", f"No kustomization.yaml found in {kustomize_path}"

    cmd: list[str] = ["kubectl", "kustomize", str(kustomize_path)]

    try:
        result: CompletedProcess[str] = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        )
        return True, result.stdout, ""
    except FileNotFoundError:
        try:
            cmd: list[str] = ["kustomize", "build", str(kustomize_path)]
            result: CompletedProcess[str] = subprocess.run(
                cmd, capture_output=True, text=True, check=True
            )
            return True, result.stdout, ""
        except FileNotFoundError:
            return (
                False,
                "",
                "Neither 'kubectl kustomize' nor 'kustomize' command found.",
            )
        except subprocess.CalledProcessError as e:
            return False, "", f"Kustomize build failed: {e.stderr}"
    except subprocess.CalledProcessError as e:
        return False, "", f"Kustomize render failed: {e.stderr}"


def render_plain_manifests(manifests_path: Path, output_dir: Path) -> tuple[bool, str]:
    """Copy plain YAML manifests from a directory.

    Reads all .yaml and .yml files from the directory and combines them into
    the standard output structure (_all.yaml and per-kind files).

    Args:
        manifests_path: Path to directory containing plain YAML files
        output_dir: Directory to write rendered manifests to

    Returns:
        (success, message) tuple
    """
    if not manifests_path.exists():
        return False, f"Manifests path not found: {manifests_path}"

    if not manifests_path.is_dir():
        return False, f"Manifests path is not a directory: {manifests_path}"

    yaml_files: list[Path] = list(manifests_path.glob("*.yaml")) + list(
        manifests_path.glob("*.yml")
    )

    if not yaml_files:
        return False, f"No YAML files found in {manifests_path}"

    all_content: list[str] = []
    for yaml_file in sorted(yaml_files):
        try:
            content: str = yaml_file.read_text(encoding="utf-8").strip()
            if content:
                all_content.append(content)
        except Exception as e:
            return False, f"Failed to read {yaml_file}: {e}"

    combined: str = "\n---\n".join(all_content)

    doc_count: int = _write_rendered_output(combined, output_dir)

    return (
        True,
        f"Rendered {doc_count} resources from {len(yaml_files)} plain YAML files",
    )
