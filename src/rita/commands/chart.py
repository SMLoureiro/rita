"""Chart and schema management commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import rich_click as click
import yaml
from pydantic import BaseModel, ValidationError

from rita import console as con
from rita.charts.registry import CHART_REGISTRY
from rita.repository import get_chart_path, get_config, get_repo_root

if TYPE_CHECKING:
    from pathlib import Path

    from rita.config import RitaConfig
from rita.scaffolding import (
    scaffold_helm_chart,
    scaffold_pydantic_schema,
    to_class_name,
    to_module_name,
)


def _get_type_label(prop: dict[str, Any]) -> str:
    """Generate a human-readable type label from a JSON schema property.

    Uses square brackets for clear visibility in VSCode hover tooltips:
    [boolean] - clearly indicates the expected type.
    """
    if "$ref" in prop:
        # Reference to another definition - extract the name
        ref = prop["$ref"]
        if ref.startswith("#/$defs/"):
            return f"[{ref.split('/')[-1]}]"
        return "[object]"

    prop_type = prop.get("type")

    if prop_type == "array":
        items = prop.get("items", {})
        if "$ref" in items:
            item_type = items["$ref"].split("/")[-1]
            return f"[array<{item_type}>]"
        item_type = items.get("type", "any")
        return f"[array<{item_type}>]"

    if prop_type == "object":
        return "[object]"

    if prop_type == "string":
        if "enum" in prop:
            enum_vals = " | ".join(f'"{e}"' for e in prop["enum"])
            return f"[{enum_vals}]"
        if "format" in prop:
            return f"[string, {prop['format']}]"
        return "[string]"

    if prop_type == "integer":
        return "[integer]"

    if prop_type == "number":
        return "[number]"

    if prop_type == "boolean":
        return "[boolean]"

    if prop_type is None and "anyOf" in prop:
        # Union types
        types = []
        for opt in prop["anyOf"]:
            if opt.get("type") == "null":
                continue
            if "$ref" in opt:
                types.append(opt["$ref"].split("/")[-1])
            elif opt.get("type"):
                types.append(opt["type"])
        if types:
            return f"[{' | '.join(types)}]"

    return ""


def _enhance_schema_with_types(schema: dict[str, Any]) -> dict[str, Any]:
    """Post-process a JSON schema to add type information to descriptions."""

    def enhance_properties(properties: dict[str, Any]) -> None:
        for _prop_name, prop in properties.items():
            if not isinstance(prop, dict):
                continue

            type_label = _get_type_label(prop)
            if type_label and "description" in prop:
                desc = prop["description"]
                # Only add if not already prefixed with type (parentheses or brackets)
                if not desc.startswith("(") and not desc.startswith("["):
                    prop["description"] = f"{type_label} {desc}"

            # Recurse into nested properties
            if "properties" in prop:
                enhance_properties(prop["properties"])

    # Enhance top-level properties
    if "properties" in schema:
        enhance_properties(schema["properties"])

    # Enhance definitions ($defs)
    if "$defs" in schema:
        for _def_name, definition in schema["$defs"].items():
            if isinstance(definition, dict) and "properties" in definition:
                enhance_properties(definition["properties"])

    return schema


@click.group()
def chart() -> None:
    """Manage Helm charts."""
    pass


@chart.command("new")
@click.argument("name")
@click.option(
    "--description",
    "-d",
    default="A Helm chart for Kubernetes",
    help="Chart description.",
)
@click.option("--maintainer-name", "-m", default="developer", help="Maintainer name.")
@click.option(
    "--maintainer-email",
    "-e",
    default="developer@example.com",
    help="Maintainer email.",
)
@click.option(
    "--skip-schema", is_flag=True, help="Skip creating Pydantic schema files."
)
def chart_new(
    name: str,
    description: str,
    maintainer_name: str,
    maintainer_email: str,
    skip_schema: bool,
) -> None:
    """Create a new Helm chart with Pydantic schema boilerplate."""
    repo_root: Path = get_repo_root()
    config: RitaConfig = get_config()
    charts_dir: Path = repo_root / config.charts.path
    schemas_dir: Path = repo_root / "rita" / "charts"

    chart_path: Path = charts_dir / name
    if chart_path.exists():
        con.print_error(f"Chart '{name}' already exists at {chart_path}")
        raise SystemExit(1)

    con.print_header(f"Creating chart: {name}")

    con.print_subheader("Helm Chart Files")
    chart_files: list[str] = scaffold_helm_chart(
        charts_dir=charts_dir,
        chart_name=name,
        description=description,
        maintainer_name=maintainer_name,
        maintainer_email=maintainer_email,
    )
    for f in chart_files:
        con.print_success(f"Created: charts/{name}/{f}")

    if not skip_schema:
        con.print_subheader("Pydantic Schema Files")
        schema_files = scaffold_pydantic_schema(
            schemas_dir=schemas_dir, chart_name=name
        )
        for f in schema_files:
            con.print_success(f"Created: rita/charts/{f}")

        con.console.print()
        con.print_info("To enable schema validation, add to rita/charts/registry.py:")
        con.console.print()

        class_name: str = to_class_name(name)
        module_name: str = to_module_name(name)

        con.console.print(
            f"  [cyan]from rita.charts.{module_name} import {class_name}[/cyan]"
        )
        con.console.print()
        con.console.print("  [yellow]CHART_REGISTRY[/yellow] = {")
        con.console.print("      ...")
        con.console.print(f'      [green]"{name}": {class_name},[/green]')
        con.console.print("  }")

    con.console.print()
    con.print_success(f"Chart '{name}' created successfully!")
    con.print_hint(f"Edit charts/{name}/values.yaml to customize default values")
    if not skip_schema:
        con.print_hint(
            f"Edit rita/charts/{to_module_name(name)}/values.py to define the schema"
        )


@click.group()
def schema() -> None:
    """Generate values.schema.json files from Pydantic models."""
    pass


@schema.command("list")
def list_charts() -> None:
    """List all available charts with schema definitions."""
    con.print_header("Charts with Pydantic Schema Definitions")

    charts = [
        (chart_name, get_chart_path(chart_name).exists())
        for chart_name in sorted(CHART_REGISTRY.keys())
    ]
    con.print_chart_list(charts)


@schema.command("show")
@click.option(
    "--chart", "-c", "chart_name", help="Name of the chart to show schema for."
)
def show_schema(chart_name: str | None) -> None:
    """Display the JSON schema on the console."""
    if chart_name:
        if chart_name not in CHART_REGISTRY:
            con.print_error(f"Chart '{chart_name}' not found in registry")
            con.print_info(f"Available charts: {', '.join(CHART_REGISTRY.keys())}")
            raise SystemExit(1)
        charts_to_show = {chart_name: CHART_REGISTRY[chart_name]}
    else:
        charts_to_show: dict[str, type[BaseModel]] = CHART_REGISTRY

    for name, model_cls in charts_to_show.items():
        schema_json: str = json.dumps(model_cls.model_json_schema(), indent=2)
        con.print_json(schema_json, title=f"{name} Helm Values Schema")
        con.console.print()


@schema.command("apply")
@click.option(
    "--chart", "-c", "chart_name", help="Name of the chart to generate schema for."
)
@click.option(
    "--dry-run", is_flag=True, help="Print what would be done without writing files."
)
@click.option(
    "--no-types",
    is_flag=True,
    help="Skip adding type prefixes to descriptions.",
)
def apply_schema(chart_name: str | None, dry_run: bool, no_types: bool) -> None:
    """Generate values.schema.json files for charts.

    By default, type information is prepended to each field description
    to make it visible in VSCode hover tooltips (e.g., '[string] Description...').
    Use --no-types to disable this behavior.
    """
    if chart_name:
        if chart_name not in CHART_REGISTRY:
            con.print_error(f"Chart '{chart_name}' not found in registry")
            con.print_info(f"Available charts: {', '.join(CHART_REGISTRY.keys())}")
            raise SystemExit(1)
        charts_to_apply = {chart_name: CHART_REGISTRY[chart_name]}
    else:
        charts_to_apply: dict[str, type[BaseModel]] = CHART_REGISTRY

    for name, model_cls in charts_to_apply.items():
        chart_path: Path = get_chart_path(name)
        schema_path: Path = chart_path / "values.schema.json"

        if not chart_path.exists():
            con.print_warning(f"Chart directory not found: {chart_path}")
            continue

        # Generate schema and optionally enhance with type prefixes
        schema_dict = model_cls.model_json_schema()
        if not no_types:
            schema_dict = _enhance_schema_with_types(schema_dict)

        schema_content: str = json.dumps(schema_dict, indent=2)

        if dry_run:
            con.print_info(
                f"Would write schema to: {con.format_path(str(schema_path))}"
            )
            con.print_key_value("Schema size", f"{len(schema_content)} bytes", indent=1)
        else:
            with schema_path.open("w", encoding="utf-8") as f:
                f.write(schema_content)
                f.write("\n")
            con.print_success(f"Generated: {con.format_path(str(schema_path))}")


@schema.command("validate")
@click.option(
    "--chart",
    "-c",
    "chart_name",
    required=True,
    help="Name of the chart to validate against.",
)
@click.argument("values_file", type=click.Path(exists=True))
def validate(chart_name: str, values_file: str) -> None:
    """Validate a values file against the schema."""
    if chart_name not in CHART_REGISTRY:
        con.print_error(f"Chart '{chart_name}' not found in registry")
        raise SystemExit(1)

    model_cls: type[BaseModel] = CHART_REGISTRY[chart_name]
    values_path = values_file if hasattr(values_file, 'open') else __import__('pathlib').Path(values_file)

    with values_path.open(encoding="utf-8") as f:
        values = yaml.safe_load(f)

    try:
        model_cls.model_validate(values)
        con.print_success(f"{values_file} is valid for chart '{chart_name}'")
    except ValidationError as e:
        con.print_error(f"Validation errors in {values_file}:")
        for error in e.errors():
            loc = ".".join(str(x) for x in error["loc"])
            con.print_bullet(f"[bold]{loc}[/bold]: {error['msg']}")
        raise SystemExit(1) from None
