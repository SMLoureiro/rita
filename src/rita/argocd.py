"""ArgoCD application and ApplicationSet parsing and management."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from collections.abc import Callable

import yaml

from rita.models import ArgoAppConfig, ArgoAppSetConfig, ArgoAppSetGeneratorElement


class ArgoMetadata(TypedDict, total=False):
    """ArgoCD Application/ApplicationSet metadata."""

    name: str
    namespace: str


class ArgoDestination(TypedDict, total=False):
    """ArgoCD Application destination."""

    server: str
    namespace: str


class ArgoHelmConfig(TypedDict, total=False):
    """Helm configuration in ArgoCD source."""

    releaseName: str
    valueFiles: list[str]
    valuesObject: dict[str, Any]


class ArgoSource(TypedDict, total=False):
    """ArgoCD Application source configuration."""

    repoURL: str
    chart: str
    targetRevision: str
    path: str
    ref: str
    helm: ArgoHelmConfig


class ArgoApplicationSpec(TypedDict, total=False):
    """ArgoCD Application spec."""

    source: ArgoSource
    sources: list[ArgoSource]
    destination: ArgoDestination


class ArgoApplicationDocument(TypedDict, total=False):
    """Complete ArgoCD Application document."""

    apiVersion: str
    kind: str
    metadata: ArgoMetadata
    spec: ArgoApplicationSpec


class ArgoGeneratorElement(TypedDict, total=False):
    """Element in ApplicationSet list generator."""

    name: str
    origin: str
    version: str
    valuesFile: str
    wave: str
    dependsOn: str


class ArgoListGenerator(TypedDict, total=False):
    """ApplicationSet list generator."""

    elements: list[ArgoGeneratorElement]


class ArgoGenerator(TypedDict, total=False):
    """ApplicationSet generator."""

    list: ArgoListGenerator


class ArgoApplicationSetTemplateSpec(TypedDict, total=False):
    """ApplicationSet template spec."""

    sources: list[ArgoSource]
    destination: ArgoDestination


class ArgoApplicationSetTemplate(TypedDict, total=False):
    """ApplicationSet template."""

    spec: ArgoApplicationSetTemplateSpec


class ArgoApplicationSetSpec(TypedDict, total=False):
    """ApplicationSet spec."""

    generators: list[ArgoGenerator]
    template: ArgoApplicationSetTemplate


class ArgoApplicationSetDocument(TypedDict, total=False):
    """Complete ArgoCD ApplicationSet document."""

    apiVersion: str
    kind: str
    metadata: ArgoMetadata
    spec: ArgoApplicationSetSpec


def _find_application_document(app_path: Path) -> ArgoApplicationDocument | None:
    try:
        with app_path.open(encoding="utf-8") as f:
            content: str = f.read()
    except Exception:
        return None

    try:
        for doc in yaml.safe_load_all(content):
            if doc and isinstance(doc, dict) and doc.get("kind") == "Application":
                return doc
    except Exception:
        return None

    return None


def _find_applicationset_document(content: str) -> ArgoApplicationSetDocument | None:
    try:
        for doc in yaml.safe_load_all(content):
            if doc and isinstance(doc, dict) and doc.get("kind") == "ApplicationSet":
                return doc
    except Exception:
        return None

    return None


def parse_argocd_application(
    app_path: Path, chart_path_resolver: Callable[[str], Path]
) -> ArgoAppConfig | None:
    doc: ArgoApplicationDocument | None = _find_application_document(app_path)
    if not doc:
        return None

    metadata: ArgoMetadata = doc.get("metadata", {})
    spec: ArgoApplicationSpec = doc.get("spec", {})
    name: str = metadata.get("name", "")
    destination: ArgoDestination = spec.get("destination", {})
    namespace: str = destination.get("namespace", "default")

    chart_source: ArgoSource | None = _find_chart_source(spec)
    if not chart_source:
        return None

    sources: list[ArgoSource] = spec.get("sources", [])
    source: ArgoSource | None = spec.get("source")
    if source and not sources:
        sources: list[ArgoSource] = [source]

    helm_source: ArgoSource | None = None
    kustomize_source_path: str | None = None
    plain_manifests_path: str | None = None

    for src in sources:
        if "chart" in src and not helm_source:
            helm_source: ArgoSource = src
        if "path" in src and not src.get("ref"):
            path: str | None = src.get("path")
            if path:
                if _is_kustomize_directory(path):
                    kustomize_source_path = path
                else:
                    plain_manifests_path = path

    if not helm_source and kustomize_source_path:
        return ArgoAppConfig(
            name=name,
            chart_repo="",
            chart_name="",
            chart_version="",
            values_files=[],
            namespace=namespace,
            release_name=name,
            is_local_chart=False,
            source_file=app_path,
            is_kustomize=True,
            kustomize_path=kustomize_source_path,
        )

    chart_repo: str = helm_source.get("repoURL", "") if helm_source else ""
    chart_name: str = helm_source.get("chart", "") if helm_source else ""
    chart_version: str = (
        helm_source.get("targetRevision", "latest") if helm_source else "latest"
    )

    helm_config: ArgoHelmConfig = helm_source.get("helm", {}) if helm_source else {}
    release_name: str = helm_config.get("releaseName", name)
    values_files: list[str] = _extract_values_files(helm_config)
    values_object: dict[str, Any] | None = helm_config.get("valuesObject")

    local_chart_name: str = _extract_local_chart_name(chart_name)
    is_local_chart: bool = (
        chart_path_resolver(local_chart_name).exists() if chart_name else False
    )

    return ArgoAppConfig(
        name=name,
        chart_repo=chart_repo,
        chart_name=local_chart_name if is_local_chart else chart_name,
        chart_version=chart_version,
        values_files=values_files,
        namespace=namespace,
        release_name=release_name,
        is_local_chart=is_local_chart,
        source_file=app_path,
        oci_chart_name=chart_name,
        values_object=values_object,
        is_kustomize=bool(kustomize_source_path),
        kustomize_path=kustomize_source_path,
        plain_manifests_path=plain_manifests_path,
    )


def parse_applicationset_from_manifest(
    manifest_content: str, source_file: Path | None = None
) -> ArgoAppSetConfig | None:
    """Parse an ApplicationSet from rendered manifest content.

    This is used to extract ApplicationSet configuration from rendered Helm output.
    """
    doc: ArgoApplicationSetDocument | None = _find_applicationset_document(
        manifest_content
    )
    if not doc:
        return None

    metadata: ArgoMetadata = doc.get("metadata", {})
    spec: ArgoApplicationSetSpec = doc.get("spec", {})

    name: str = metadata.get("name", "")
    namespace: str = metadata.get("namespace", "argocd")

    generators: list[ArgoGenerator] = spec.get("generators", [])
    generator_elements: list[ArgoAppSetGeneratorElement] = []

    for gen in generators:
        if "list" in gen:
            list_gen: ArgoListGenerator = gen["list"]
            elements: list[ArgoGeneratorElement] = list_gen.get("elements", [])

            for elem in elements:
                gen_elem: ArgoAppSetGeneratorElement = ArgoAppSetGeneratorElement(
                    name=elem.get("name", ""),
                    chart_name=elem.get("origin", ""),
                    chart_version=elem.get("version", ""),
                    values_file=elem.get("valuesFile", ""),
                    namespace=namespace,
                    wave=elem.get("wave", "0"),
                    depends_on=elem.get("dependsOn"),
                    extra_fields=dict(elem),
                )
                generator_elements.append(gen_elem)

    template: ArgoApplicationSetTemplate = spec.get("template", {})
    template_spec: ArgoApplicationSetTemplateSpec = template.get("spec", {})

    destination: ArgoDestination = template_spec.get("destination", {})
    dest_server: str = destination.get("server", "https://kubernetes.default.svc")
    dest_namespace: str = destination.get("namespace", "default")

    sources: list[ArgoSource] = template_spec.get("sources", [])
    chart_repo: str = ""
    values_overlay: dict[str, Any] | None = None

    for source in sources:
        if "chart" in source:
            chart_repo: str = source.get("repoURL", "")
            helm_config: ArgoHelmConfig = source.get("helm", {})
            values_overlay: dict[str, Any] | None = helm_config.get("valuesObject")
            break

    return ArgoAppSetConfig(
        name=name,
        namespace=namespace,
        chart_repo=chart_repo,
        destination_server=dest_server,
        destination_namespace=dest_namespace,
        generator_elements=generator_elements,
        template_spec=dict(template_spec),
        source_file=source_file,
        values_overlay=values_overlay,
    )


def is_applicationset_chart(chart_name: str) -> bool:
    appset_charts = [
        "feature-deployment",
        "pharma-feature-deployment",
    ]
    return any(appset in chart_name.lower() for appset in appset_charts)


def extract_applicationsets_from_rendered(
    rendered_content: str,
) -> list[dict[str, Any]]:
    appsets: list[dict[str, Any]] = []
    try:
        for doc in yaml.safe_load_all(rendered_content):
            if doc and isinstance(doc, dict) and doc.get("kind") == "ApplicationSet":
                appsets.append(doc)
    except Exception:
        pass
    return appsets


def parse_argocd_resources_from_manifest(
    manifest_content: str,
    source_file: Path | None,
    chart_path_resolver: Callable[[str], Path],
) -> tuple[list[ArgoAppConfig], list[ArgoAppSetConfig]]:
    """Parse all ArgoCD Applications and ApplicationSets from rendered manifest content.

    Returns a tuple of (applications, applicationsets) found in the manifest.
    This is used for recursive rendering of app-of-apps patterns.
    """
    applications: list[ArgoAppConfig] = []
    applicationsets: list[ArgoAppSetConfig] = []

    try:
        docs: list[Any] = list(yaml.safe_load_all(manifest_content))
    except yaml.YAMLError:
        return [], []

    for doc in docs:
        if not doc or not isinstance(doc, dict):
            continue

        api_version: str = doc.get("apiVersion", "")
        kind: str = doc.get("kind", "")

        if kind == "Application" and "argoproj.io" in api_version:
            app: ArgoAppConfig | None = _parse_application_from_doc(
                doc, source_file, chart_path_resolver
            )
            if app:
                applications.append(app)
        elif kind == "ApplicationSet" and "argoproj.io" in api_version:
            appset: ArgoAppSetConfig | None = _parse_applicationset_from_doc(
                doc, source_file
            )
            if appset:
                applicationsets.append(appset)

    return applications, applicationsets


def _parse_application_from_doc(
    doc: ArgoApplicationDocument,
    source_file: Path | None,
    chart_path_resolver: Callable[[str], Path],
) -> ArgoAppConfig | None:
    """Parse a single Application document into an ArgoAppConfig."""

    typed_doc: ArgoApplicationDocument = doc

    metadata: ArgoMetadata = typed_doc.get("metadata", {})
    spec: ArgoApplicationSpec = typed_doc.get("spec", {})

    name: str = metadata.get("name", "")
    destination: ArgoDestination = spec.get("destination", {})
    namespace: str = destination.get("namespace", "default")

    chart_source: ArgoSource | None = _find_chart_source(spec)
    if not chart_source:
        return None

    repo_url: str = chart_source.get("repoURL", "")
    chart: str = chart_source.get("chart", "")
    target_revision: str = chart_source.get("targetRevision", "latest")

    helm: ArgoHelmConfig = chart_source.get("helm", {})
    values_files: list[str] = _extract_values_files(helm)
    values_object: dict[str, Any] | None = helm.get("valuesObject")
    release_name: str = helm.get("releaseName", name)

    local_chart_name: str = _extract_local_chart_name(chart)
    is_local_chart: bool = chart_path_resolver(local_chart_name).exists()

    return ArgoAppConfig(
        name=name,
        chart_repo=repo_url,
        chart_name=local_chart_name if is_local_chart else chart,
        chart_version=target_revision,
        values_files=values_files,
        namespace=namespace,
        release_name=release_name,
        is_local_chart=is_local_chart,
        source_file=source_file,
        oci_chart_name=chart,
        values_object=values_object,
    )


def _parse_applicationset_from_doc(
    doc: dict[str, Any], source_file: Path | None
) -> ArgoAppSetConfig | None:
    metadata: dict[str, Any] = doc.get("metadata", {})
    spec: dict[str, Any] = doc.get("spec", {})

    name: str = metadata.get("name", "")
    namespace: str = metadata.get("namespace", "argocd")

    generators: list[dict[str, Any]] = spec.get("generators", [])
    generator_elements: list[ArgoAppSetGeneratorElement] = []

    for gen in generators:
        if "list" in gen:
            list_gen: dict[str, Any] = gen["list"]
            elements: list[dict[str, Any]] = list_gen.get("elements", [])

            for elem in elements:
                gen_elem: ArgoAppSetGeneratorElement = ArgoAppSetGeneratorElement(
                    name=elem.get("name", ""),
                    chart_name=elem.get("origin", ""),
                    chart_version=elem.get("version", ""),
                    values_file=elem.get("valuesFile", ""),
                    namespace=namespace,
                    wave=elem.get("wave", "0"),
                    depends_on=elem.get("dependsOn"),
                    extra_fields=elem,
                )
                generator_elements.append(gen_elem)

    template: dict[str, Any] = spec.get("template", {})
    template_spec: dict[str, Any] = template.get("spec", {})

    destination: dict[str, Any] = template_spec.get("destination", {})
    dest_server: str = destination.get("server", "https://kubernetes.default.svc")
    dest_namespace: str = destination.get("namespace", "default")
    sources: list[dict[str, Any]] = template_spec.get("sources", [])
    chart_repo: str = ""
    values_overlay: dict[str, Any] | None = None

    for source in sources:
        if "chart" in source:
            chart_repo: Any = source.get("repoURL", "")
            helm_config: dict[str, Any] = source.get("helm", {})
            values_overlay: Any = helm_config.get("valuesObject")
            break

    return ArgoAppSetConfig(
        name=name,
        namespace=namespace,
        chart_repo=chart_repo,
        destination_server=dest_server,
        destination_namespace=dest_namespace,
        generator_elements=generator_elements,
        template_spec=template_spec,
        source_file=source_file,
        values_overlay=values_overlay,
    )


def resolve_template_variables(template_str: str, variables: dict[str, Any]) -> str:
    """Resolve ApplicationSet template variables in a string.

    Handles the escaped Helm template syntax: {{`{{`}}name{{`}}`}} -> {{name}}
    Then resolves {{name}} -> actual value from variables.
    """
    unescaped: str = re.sub(
        r"\{\{\s*`\{\{`\s*\}\}(.+?)\{\{\s*`\}\}`\s*\}\}", r"{{\1}}", template_str
    )

    def replace_var(match: re.Match[str]) -> str:
        var_name: str = match.group(1).strip()
        return str(variables.get(var_name, match.group(0)))

    return re.sub(r"\{\{(.+?)\}\}", replace_var, unescaped)


def _find_chart_source(spec: ArgoApplicationSpec) -> ArgoSource | None:
    """Find the chart or kustomize source in an Application spec.

    Returns the first source that has either a 'chart' (Helm) or 'path' (Kustomize) field.
    """
    sources: list[ArgoSource] = spec.get("sources", [])
    source: ArgoSource | None = spec.get("source", None)

    if source and not sources:
        sources: list[ArgoSource] = [source]

    if not sources:
        return None

    for src in sources:
        if "chart" in src:
            return src

    for src in sources:
        if "path" in src:
            return src

    return None


def _extract_values_files(helm_config: ArgoHelmConfig) -> list[str]:
    raw_value_files: list[str] = helm_config.get("valueFiles", [])
    values_files: list[str] = []

    for vf in raw_value_files:
        if vf.startswith("$values/"):
            values_files.append(vf.replace("$values/", ""))
        else:
            values_files.append(vf)

    return values_files


def _is_kustomize_directory(path: str) -> bool:
    """Check if a directory contains a kustomization file."""

    dir_path = Path(path)

    if not dir_path.is_absolute() and not dir_path.exists():
        try:
            result: CompletedProcess[str] = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            )
            repo_root = Path(result.stdout.strip())
            dir_path: Path = repo_root / path
        except Exception:
            dir_path: Path = Path.cwd() / path

    if not dir_path.exists():
        return False

    kustomize_files: list[str] = [
        "kustomization.yaml",
        "kustomization.yml",
        "Kustomization",
    ]
    return any((dir_path / f).exists() for f in kustomize_files)


def _extract_local_chart_name(chart_name: str) -> str:
    if "/" in chart_name:
        return chart_name.split("/")[-1]
    return chart_name


def list_argocd_applications(
    apps_paths: list[Path], chart_path_resolver: Callable[[str], Path]
) -> list[ArgoAppConfig]:
    apps: list[ArgoAppConfig] = []

    for apps_path in apps_paths:
        if not apps_path.exists():
            continue

        for yaml_file in apps_path.glob("*.yaml"):
            if yaml_file.is_dir():
                continue
            app: ArgoAppConfig | None = parse_argocd_application(
                yaml_file, chart_path_resolver
            )
            if app:
                apps.append(app)

    return sorted(apps, key=lambda x: x.name)
