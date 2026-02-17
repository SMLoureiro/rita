"""Domain models for RITA."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class ArgoAppConfig:
    """Parsed ArgoCD Application configuration."""

    name: str
    chart_repo: str
    chart_name: str
    chart_version: str
    values_files: list[str]
    namespace: str
    release_name: str
    is_local_chart: bool = False
    source_file: Path | None = None
    oci_chart_name: str | None = None
    values_object: dict | None = None
    """Inline values from valuesObject in the Application spec."""
    is_kustomize: bool = False
    """Whether this is a Kustomize application (uses path instead of chart)."""
    kustomize_path: str | None = None
    """Path to the kustomization directory for Kustomize applications."""
    plain_manifests_path: str | None = None
    """Path to plain YAML manifests directory (no kustomization.yaml)."""

    def __post_init__(self) -> None:
        if self.oci_chart_name is None:
            self.oci_chart_name = self.chart_name

    def __repr__(self) -> str:
        if self.is_kustomize:
            return f"ArgoAppConfig(name={self.name}, kustomize={self.kustomize_path})"
        return f"ArgoAppConfig(name={self.name}, chart={self.chart_name}@{self.chart_version})"


@dataclass
class ArgoAppSetGeneratorElement:
    """A single element from an ApplicationSet generator."""

    name: str
    chart_name: str
    chart_version: str
    values_file: str
    namespace: str
    wave: str = "0"
    depends_on: str | None = None
    extra_fields: dict = field(default_factory=dict)
    """Additional fields from the generator element."""


@dataclass
class ArgoAppSetConfig:
    """Parsed ArgoCD ApplicationSet configuration."""

    name: str
    namespace: str
    chart_repo: str
    destination_server: str
    destination_namespace: str
    generator_elements: list[ArgoAppSetGeneratorElement]
    template_spec: dict
    """The template.spec from the ApplicationSet for values overlay."""
    source_file: Path | None = None
    values_overlay: dict | None = None
    """The valuesObject overlay from the ApplicationSet template."""

    def __repr__(self) -> str:
        return f"ArgoAppSetConfig(name={self.name}, elements={len(self.generator_elements)})"

    def to_app_configs(
        self, chart_path_resolver, values_root: Path  # noqa: ARG002
    ) -> list[ArgoAppConfig]:
        """Convert generator elements to ArgoAppConfig objects for rendering."""
        apps = []
        for elem in self.generator_elements:
            origin = elem.extra_fields.get("origin", elem.chart_name)
            local_chart_path = chart_path_resolver(origin)
            is_local = local_chart_path.exists()

            values_files = []
            if elem.values_file:
                values_path = f"kubernetes/{origin}/{elem.values_file}"
                values_files.append(values_path)

            oci_chart_name = f"helm-charts/{origin}"

            app = ArgoAppConfig(
                name=elem.name,
                chart_repo=self.chart_repo,
                chart_name=origin,
                chart_version=elem.chart_version,
                values_files=values_files,
                namespace=self.destination_namespace,
                release_name=elem.name,
                is_local_chart=is_local,
                source_file=self.source_file,
                oci_chart_name=oci_chart_name,
                values_object=self.values_overlay,
            )
            apps.append(app)

        return apps


@dataclass
class RenderResult:
    """Result of a single render operation."""

    env: str
    app_name: str
    success: bool
    message: str
    duration_seconds: float = 0.0


@dataclass
class DiffResult:
    """Result of a single diff operation."""

    env: str
    app_name: str
    success: bool
    has_diff: bool
    diff_output: str
    error: str | None = None
    duration_seconds: float = 0.0
    values_files: list[str] = field(default_factory=list)


@dataclass
class TestResult:
    """Result of a chart test."""

    chart_name: str
    success: bool
    message: str
    duration_seconds: float
    details: dict | None = None
