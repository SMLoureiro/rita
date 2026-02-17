from __future__ import annotations

from typing import TYPE_CHECKING

from rita.scaffolding import (
    get_registry_addition,
    get_templates_dir,
    render_template,
    scaffold_helm_chart,
    scaffold_pydantic_schema,
    to_class_name,
    to_module_name,
    to_title,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestNameConversions:
    def test_to_class_name_simple(self):
        assert to_class_name("my-chart") == "MyChartValues"
        assert to_class_name("patient-backend") == "PatientBackendValues"

    def test_to_class_name_single_word(self):
        assert to_class_name("frontend") == "FrontendValues"

    def test_to_class_name_multiple_parts(self):
        assert to_class_name("my-awesome-chart") == "MyAwesomeChartValues"
        assert to_class_name("a-b-c-d") == "ABCDValues"

    def test_to_module_name_simple(self):
        assert to_module_name("my-chart") == "my_chart"
        assert to_module_name("patient-backend") == "patient_backend"

    def test_to_module_name_single_word(self):
        assert to_module_name("frontend") == "frontend"

    def test_to_module_name_multiple_parts(self):
        assert to_module_name("my-awesome-chart") == "my_awesome_chart"

    def test_to_title_simple(self):
        assert to_title("my-chart") == "My Chart"
        assert to_title("patient-backend") == "Patient Backend"

    def test_to_title_single_word(self):
        assert to_title("frontend") == "Frontend"


class TestRenderTemplate:
    def test_render_name_placeholder(self):
        template = "name: {{ name }}"
        result: str = render_template(template, name="my-chart")
        assert result == "name: my-chart"

    def test_render_class_name(self):
        template = "class {{ class_name }}:"
        result: str = render_template(template, name="my-chart")
        assert result == "class MyChartValues:"

    def test_render_module_name(self):
        template = "from rita.charts.{{ module_name }} import Values"
        result: str = render_template(template, name="my-chart")
        assert result == "from rita.charts.my_chart import Values"

    def test_render_title(self):
        template = "# {{ title }}"
        result: str = render_template(template, name="my-chart")
        assert result == "# My Chart"

    def test_render_description(self):
        template = "description: {{ description }}"
        result: str = render_template(
            template, name="chart", description="My description"
        )
        assert result == "description: My description"

    def test_render_maintainer(self):
        template = "name: {{ maintainer_name }}\nemail: {{ maintainer_email }}"
        result: str = render_template(
            template,
            name="chart",
            maintainer_name="John Doe",
            maintainer_email="john@example.com",
        )
        assert "name: John Doe" in result
        assert "email: john@example.com" in result

    def test_render_helm_placeholder(self):
        template = "name: helm-scaffold-example"
        result = render_template(template, name="my-app")
        assert result == "name: my-app"

    def test_render_multiple_placeholders(self):
        template = """
name: {{ name }}
class: {{ class_name }}
module: {{ module_name }}
"""
        result = render_template(template, name="my-chart")
        assert "name: my-chart" in result
        assert "class: MyChartValues" in result
        assert "module: my_chart" in result


class TestGetTemplatesDir:
    def test_templates_dir_exists(self):
        templates_dir: Path = get_templates_dir()
        assert templates_dir.exists()
        assert templates_dir.is_dir()

    def test_helm_templates_exist(self):
        helm_dir: Path = get_templates_dir() / "helm"
        assert helm_dir.exists()

    def test_pydantic_templates_exist(self):
        pydantic_dir: Path = get_templates_dir() / "pydantic"
        assert pydantic_dir.exists()


class TestScaffoldHelmChart:
    def test_creates_chart_directory(self, tmp_path: Path):
        scaffold_helm_chart(tmp_path, "test-chart")

        chart_dir: Path = tmp_path / "test-chart"
        assert chart_dir.exists()
        assert chart_dir.is_dir()

    def test_creates_chart_yaml(self, tmp_path: Path):
        scaffold_helm_chart(tmp_path, "my-service")

        chart_yaml: Path = tmp_path / "my-service" / "Chart.yaml"
        assert chart_yaml.exists()

        content: str = chart_yaml.read_text()
        assert "name: my-service" in content

    def test_creates_values_yaml(self, tmp_path: Path):
        scaffold_helm_chart(tmp_path, "my-chart")

        values_yaml: Path = tmp_path / "my-chart" / "values.yaml"
        assert values_yaml.exists()

    def test_creates_templates_directory(self, tmp_path: Path):
        scaffold_helm_chart(tmp_path, "my-chart")

        templates_dir: Path = tmp_path / "my-chart" / "templates"
        assert templates_dir.exists()
        assert templates_dir.is_dir()

    def test_returns_created_files_list(self, tmp_path: Path):
        created_files: list[str] = scaffold_helm_chart(tmp_path, "my-chart")

        assert isinstance(created_files, list)
        assert len(created_files) > 0
        assert any("Chart.yaml" in f for f in created_files)

    def test_idempotent_creation(self, tmp_path: Path):
        scaffold_helm_chart(tmp_path, "my-chart")
        scaffold_helm_chart(tmp_path, "my-chart")

        chart_dir: Path = tmp_path / "my-chart"
        assert chart_dir.exists()


class TestScaffoldPydanticSchema:
    def test_creates_module_directory(self, tmp_path: Path):
        scaffold_pydantic_schema(tmp_path, "my-chart")

        module_dir: Path = tmp_path / "my_chart"
        assert module_dir.exists()
        assert module_dir.is_dir()

    def test_creates_init_file(self, tmp_path: Path):
        scaffold_pydantic_schema(tmp_path, "my-chart")

        init_file: Path = tmp_path / "my_chart" / "__init__.py"
        assert init_file.exists()

    def test_creates_values_file(self, tmp_path: Path):
        scaffold_pydantic_schema(tmp_path, "my-chart")

        values_file: Path = tmp_path / "my_chart" / "values.py"
        assert values_file.exists()

    def test_values_file_has_correct_class(self, tmp_path: Path):
        scaffold_pydantic_schema(tmp_path, "my-chart")

        values_file: Path = tmp_path / "my_chart" / "values.py"
        content: str = values_file.read_text()

        assert "MyChartValues" in content

    def test_returns_created_files_list(self, tmp_path: Path):
        created_files: list[str] = scaffold_pydantic_schema(tmp_path, "my-chart")

        assert isinstance(created_files, list)
        assert len(created_files) > 0
        assert any("values.py" in f for f in created_files)


class TestGetRegistryAddition:
    def test_generates_import_statement(self):
        code: str = get_registry_addition("my-chart")

        assert "from rita.charts.my_chart import MyChartValues" in code

    def test_generates_registry_entry(self):
        code: str = get_registry_addition("my-chart")

        assert '"my-chart": MyChartValues' in code

    def test_handles_complex_names(self):
        code: str = get_registry_addition("patient-health-report")

        assert (
            "from rita.charts.patient_health_report import PatientHealthReportValues"
            in code
        )
        assert '"patient-health-report": PatientHealthReportValues' in code
