"""Tests for Helm schema generation.

These tests validate that:
1. Pydantic models are correctly defined and can generate JSON schemas
2. The generated schemas are valid JSON Schema
3. Default values files validate against the generated schemas
4. Models can parse and validate real values files
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rita import cli
from rita.charts.feature_deployment import FeatureDeploymentValues
from rita.charts.patient_app_stack import PatientAppStackValues
from rita.charts.registry import CHART_REGISTRY, get_chart_model, list_registered_charts
from rita.charts.utils import (
    AutoscalingConfig,
    ContainerImage,
    IngressConfig,
    ProbeConfig,
    PullPolicy,
    ServiceAccount,
    ServiceConfig,
)
from rita.commands.chart import apply_schema, list_charts, show_schema


def get_repo_root() -> Path:
    return Path(__file__).parent.parent.parent


# =============================================================================
# Registry Tests
# =============================================================================


class TestChartRegistry:
    def test_registry_not_empty(self) -> None:
        assert len(CHART_REGISTRY) > 0

    def test_registry_contains_expected_charts(self) -> None:
        expected_charts = [
            "feature-deployment",
            "patient-app-stack",
            "patient-backend",
            "patient-frontend-cdn",
            "patient-frontend-container",
            "patient-health-report",
            "patient-multiagent",
        ]
        for chart in expected_charts:
            assert chart in CHART_REGISTRY, f"Expected {chart} in registry"

    def test_list_registered_charts(self) -> None:
        charts: list[str] = list_registered_charts()
        assert isinstance(charts, list)
        assert len(charts) > 0
        assert charts == sorted(charts)

    def test_get_chart_model_exists(self) -> None:
        for chart_name in list_registered_charts():
            model = get_chart_model(chart_name)
            assert model is not None, f"Model for {chart_name} should exist"

    def test_get_chart_model_not_exists(self) -> None:
        model = get_chart_model("non-existent-chart")
        assert model is None


# =============================================================================
# Schema Generation Tests
# =============================================================================


class TestSchemaGeneration:
    @pytest.mark.parametrize("chart_name", list_registered_charts())
    def test_can_generate_schema(self, chart_name: str) -> None:
        model = CHART_REGISTRY[chart_name]
        schema = model.model_json_schema()

        assert isinstance(schema, dict)
        assert "properties" in schema or "$defs" in schema or "type" in schema

    @pytest.mark.parametrize("chart_name", list_registered_charts())
    def test_schema_is_valid_json(self, chart_name: str) -> None:
        model = CHART_REGISTRY[chart_name]
        schema = model.model_json_schema()

        # Should not raise
        json_str = json.dumps(schema, indent=2)
        assert len(json_str) > 0

        # Should round-trip
        parsed = json.loads(json_str)
        assert parsed == schema

    @pytest.mark.parametrize("chart_name", list_registered_charts())
    def test_schema_has_title(self, chart_name: str) -> None:
        model = CHART_REGISTRY[chart_name]
        schema = model.model_json_schema()
        assert "title" in schema

    @pytest.mark.parametrize("chart_name", list_registered_charts())
    def test_schema_has_properties(self, chart_name: str) -> None:
        model = CHART_REGISTRY[chart_name]
        schema = model.model_json_schema()
        assert "properties" in schema
        assert len(schema["properties"]) > 0

    @pytest.mark.parametrize("chart_name", list_registered_charts())
    def test_schema_properties_have_descriptions(self, chart_name: str) -> None:
        model = CHART_REGISTRY[chart_name]
        schema = model.model_json_schema()

        properties = schema.get("properties", {})
        described: int = sum(1 for p in properties.values() if "description" in p)
        assert described > 0, (
            f"Schema for {chart_name} should have property descriptions"
        )


# =============================================================================
# Model Instantiation Tests
# =============================================================================


class TestModelInstantiation:
    @pytest.mark.parametrize("chart_name", list_registered_charts())
    def test_can_instantiate_with_defaults(self, chart_name: str) -> None:
        model = CHART_REGISTRY[chart_name]
        instance = model()
        assert instance is not None

    @pytest.mark.parametrize("chart_name", list_registered_charts())
    def test_can_parse_empty_dict(self, chart_name: str) -> None:
        model = CHART_REGISTRY[chart_name]
        instance = model.model_validate({})
        assert instance is not None

    @pytest.mark.parametrize("chart_name", list_registered_charts())
    def test_allows_extra_fields(self, chart_name: str) -> None:
        model = CHART_REGISTRY[chart_name]
        instance = model.model_validate({"unknownField": "test", "anotherField": 123})
        assert instance is not None


# =============================================================================
# Patient App Stack Specific Tests
# =============================================================================


class TestPatientAppStackSchema:
    def test_patient_app_stack_in_registry(self) -> None:
        assert "patient-app-stack" in CHART_REGISTRY

    def test_global_alias(self) -> None:
        schema = PatientAppStackValues.model_json_schema()
        properties = schema.get("properties", {})

        # Should have 'global' in properties (the alias)
        assert "global" in properties

    def test_multiagent_config(self) -> None:
        instance = PatientAppStackValues()
        assert instance.multiagent is not None
        assert hasattr(instance.multiagent, "enabled")
        assert instance.multiagent.enabled is True

    def test_gateway_config(self) -> None:
        instance = PatientAppStackValues()
        assert instance.gateway is not None

    def test_can_parse_with_custom_values(self) -> None:
        values = {
            "multiagent": {"enabled": False, "replicaCount": 5},
            "gateway": {"enabled": True},
        }
        instance = PatientAppStackValues.model_validate(values)
        assert instance.multiagent.enabled is False


# =============================================================================
# Feature Deployment Tests
# =============================================================================


class TestFeatureDeploymentSchema:
    def test_in_registry(self) -> None:
        assert "feature-deployment" in CHART_REGISTRY

    def test_has_branch_id(self) -> None:
        instance = FeatureDeploymentValues()
        assert hasattr(instance, "branchId")
        assert instance.branchId == "test-1"

    def test_has_versions_config(self) -> None:
        instance = FeatureDeploymentValues()
        assert hasattr(instance, "versions")
        assert hasattr(instance.versions, "config")
        assert hasattr(instance.versions, "stack")

    def test_has_images_config(self) -> None:
        instance = FeatureDeploymentValues()
        assert hasattr(instance, "images")
        assert hasattr(instance.images, "multiagent")
        assert hasattr(instance.images, "frontend")


# =============================================================================
# Values File Validation Tests
# =============================================================================


class TestValuesFileValidation:
    @pytest.mark.parametrize("chart_name", list_registered_charts())
    def test_default_values_file_validates(self, chart_name: str) -> None:
        repo_root: Path = get_repo_root()
        values_path: Path = repo_root / "charts" / chart_name / "values.yaml"

        if not values_path.exists():
            pytest.skip(f"values.yaml not found for {chart_name}")

        model = CHART_REGISTRY[chart_name]

        with values_path.open(encoding="utf-8") as f:
            values = yaml.safe_load(f)

        # Should not raise ValidationError
        instance = model.model_validate(values)
        assert instance is not None


# =============================================================================
# Utility Type Tests
# =============================================================================


class TestKubernetesTypes:
    def test_container_image_defaults(self) -> None:
        image = ContainerImage(repository="nginx")
        assert image.repository == "nginx"
        assert image.tag == "latest"

    def test_container_image_with_pull_policy(self) -> None:
        image = ContainerImage(
            repository="nginx", tag="1.21", pullPolicy=PullPolicy.ALWAYS
        )
        assert image.repository == "nginx"
        assert image.tag == "1.21"
        assert image.pullPolicy == PullPolicy.ALWAYS

    def test_service_account_config(self) -> None:
        sa = ServiceAccount(
            create=True,
            name="my-sa",
            annotations={"eks.amazonaws.com/role-arn": "arn:aws:iam::123:role/test"},
        )
        assert sa.create is True
        assert sa.name == "my-sa"
        assert "eks.amazonaws.com/role-arn" in sa.annotations

    def test_service_config(self) -> None:
        svc = ServiceConfig()
        assert svc.type == "ClusterIP"
        assert svc.port == 8000

    def test_service_config_custom_port(self) -> None:
        svc = ServiceConfig(port=4000)
        assert svc.port == 4000

    def test_autoscaling_config(self) -> None:
        hpa = AutoscalingConfig()
        assert hpa.enabled is False
        assert hpa.minReplicas == 1
        assert hpa.maxReplicas == 100

    def test_ingress_config(self) -> None:
        ing = IngressConfig()
        assert ing.enabled is False
        assert ing.className == ""

    def test_probe_config(self) -> None:
        probe = ProbeConfig()
        assert probe.httpGet is not None
        assert probe.httpGet.path == "/alive"
        assert probe.httpGet.port == "http"


# =============================================================================
# CLI Tests
# =============================================================================


class TestCLI:
    def test_cli_module_imports(self) -> None:
        assert hasattr(cli, "main")
        assert hasattr(cli, "schema")

    def test_cli_has_list_command(self) -> None:
        assert callable(list_charts)

    def test_cli_has_show_command(self) -> None:
        assert callable(show_schema)

    def test_cli_has_apply_command(self) -> None:
        assert callable(apply_schema)
