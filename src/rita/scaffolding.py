"""Chart scaffolding utilities for creating new Helm charts with Pydantic schemas.

Templates are stored in rita/scaffold_templates/ and copied/rendered when creating new charts.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

HELM_PLACEHOLDER_NAME = "helm-scaffold-example"


def get_templates_dir() -> Path:
    """Get the path to the scaffold_templates directory."""
    return Path(__file__).parent / "scaffold_templates"


class ChartScaffoldResult(NamedTuple):
    """Result of chart scaffolding."""

    chart_path: Path
    schema_path: Path | None
    files_created: list[str]


def to_class_name(chart_name: str) -> str:
    """Convert chart-name to ChartNameValues class name.

    Examples:
        my-chart -> MyChartValues
        patient-backend -> PatientBackendValues
    """
    parts: list[str] = chart_name.split("-")
    return "".join(part.capitalize() for part in parts) + "Values"


def to_module_name(chart_name: str) -> str:
    """Convert chart-name to module_name.

    Examples:
        my-chart -> my_chart
        patient-backend -> patient_backend
    """
    return chart_name.replace("-", "_")


def to_title(chart_name: str) -> str:
    """Convert chart-name to Title Case.

    Examples:
        my-chart -> My Chart
        patient-backend -> Patient Backend
    """
    return chart_name.replace("-", " ").title()


def render_template(
    template_content: str,
    *,
    name: str,
    description: str = "A Helm chart for Kubernetes",
    maintainer_name: str = "developer",
    maintainer_email: str = "developer@example.com",
) -> str:
    """Render a template by replacing placeholders.

    Supports both:
    - Helm-style placeholder: helm-scaffold-example
    - Jinja-style placeholders: {{ name }}, {{ class_name }}, etc.
    """

    content: str = template_content.replace(HELM_PLACEHOLDER_NAME, name)

    replacements = {
        "{{ name }}": name,
        "{{ description }}": description,
        "{{ maintainer_name }}": maintainer_name,
        "{{ maintainer_email }}": maintainer_email,
        "{{ class_name }}": to_class_name(name),
        "{{ module_name }}": to_module_name(name),
        "{{ title }}": to_title(name),
    }

    for placeholder, value in replacements.items():
        content: str = content.replace(placeholder, value)

    return content


def scaffold_helm_chart(
    charts_dir: Path,
    chart_name: str,
    description: str = "A Helm chart for Kubernetes",
    maintainer_name: str = "developer",
    maintainer_email: str = "developer@example.com",
) -> list[str]:
    """Create a new Helm chart directory from templates.

    Copies the template files from rita/scaffold_templates/helm/ and replaces
    the placeholder chart name with the actual chart name.

    Args:
        charts_dir: Path to the charts directory
        chart_name: Name of the chart (e.g., "my-service")
        description: Chart description
        maintainer_name: Maintainer name
        maintainer_email: Maintainer email

    Returns:
        List of created file paths (relative to chart directory)
    """
    templates_dir: Path = get_templates_dir() / "helm"
    chart_path: Path = charts_dir / chart_name
    chart_path.mkdir(parents=True, exist_ok=True)

    created_files = []

    for template_file in templates_dir.rglob("*.tpl"):
        if template_file.is_dir():
            continue

        rel_path: Path = template_file.relative_to(templates_dir)
        dest_path_str = str(rel_path)

        is_helm_template: bool = dest_path_str.startswith(
            "templates/"
        ) or dest_path_str.startswith("templates\\")

        if dest_path_str.endswith(".tpl"):
            if is_helm_template and dest_path_str.endswith(".yaml.tpl"):
                pass
            else:
                dest_path_str: str = dest_path_str[:-4]

        dest_file: Path = chart_path / dest_path_str
        rel_path = Path(dest_path_str)

        dest_file.parent.mkdir(parents=True, exist_ok=True)

        template_content: str = template_file.read_text(encoding="utf-8")

        rendered_content: str = render_template(
            template_content,
            name=chart_name,
            description=description,
            maintainer_name=maintainer_name,
            maintainer_email=maintainer_email,
        )

        dest_file.write_text(rendered_content, encoding="utf-8")
        created_files.append(str(rel_path))

    return sorted(created_files)


def scaffold_pydantic_schema(
    schemas_dir: Path,
    chart_name: str,
) -> list[str]:
    """Create a new Pydantic schema package from templates.

    Copies the template files from rita/scaffold_templates/pydantic/ and renders
    them with chart-specific values.

    Args:
        schemas_dir: Path to the rita/charts directory
        chart_name: Name of the chart (e.g., "my-service")

    Returns:
        List of created file paths (relative to schemas_dir)
    """
    templates_dir: Path = get_templates_dir() / "pydantic"
    module_name: str = to_module_name(chart_name)
    schema_path: Path = schemas_dir / module_name
    schema_path.mkdir(parents=True, exist_ok=True)

    created_files = []

    for template_file in templates_dir.glob("*.tpl"):
        dest_filename: str = template_file.stem
        dest_file: Path = schema_path / dest_filename

        template_content: str = template_file.read_text(encoding="utf-8")
        rendered_content: str = render_template(template_content, name=chart_name)

        dest_file.write_text(rendered_content, encoding="utf-8")
        created_files.append(f"{module_name}/{dest_filename}")

    return sorted(created_files)


def get_registry_addition(chart_name: str) -> str:
    """Get the code to add to registry.py for the new chart.

    Args:
        chart_name: Name of the chart

    Returns:
        Code snippet to add to registry.py
    """
    class_name: str = to_class_name(chart_name)
    module_name: str = to_module_name(chart_name)

    return f"""

from rita.charts.{module_name} import {class_name}


    "{chart_name}": {class_name},
"""
