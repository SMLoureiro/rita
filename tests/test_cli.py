from __future__ import annotations

from pathlib import Path

import yaml

from rita.argocd import ArgoAppConfig, parse_argocd_application
from rita.config import (
    ChartConfig,
    EnvironmentConfig,
    RenderConfig,
    RitaConfig,
    StorageConfig,
    load_config,
    save_config,
)
from rita.helm import get_local_chart_version, has_packaged_dependencies
from rita.repository import get_repo_root
from rita.scaffolding import scaffold_helm_chart, scaffold_pydantic_schema
from rita.storage import LocalStorageBackend, ManifestRef


class TestParseArgoCDApplication:
    def test_parse_invalid_yaml(self, tmp_path: Path):
        app_yaml: Path = tmp_path / "invalid.yaml"
        app_yaml.write_text("this is: not: valid: yaml: [[")

        def mock_resolver(chart_name: str) -> Path:
            return tmp_path / chart_name

        config: ArgoAppConfig | None = parse_argocd_application(app_yaml, mock_resolver)
        assert config is None

    def test_parse_non_application(self, tmp_path: Path):
        app_yaml: Path = tmp_path / "configmap.yaml"
        app_yaml.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": "my-config"},
                    "data": {"key": "value"},
                }
            )
        )

        def mock_resolver(chart_name: str) -> Path:
            return tmp_path / chart_name

        config: ArgoAppConfig | None = parse_argocd_application(app_yaml, mock_resolver)
        assert config is None


class TestHasPackagedDependencies:
    def test_no_charts_directory(self, tmp_path: Path):
        chart_path: Path = tmp_path / "my-chart"
        chart_path.mkdir()

        result: bool = has_packaged_dependencies(chart_path)
        assert result is False

    def test_empty_charts_directory(self, tmp_path: Path):
        chart_path: Path = tmp_path / "my-chart"
        (chart_path / "charts").mkdir(parents=True)

        result: bool = has_packaged_dependencies(chart_path)
        assert result is False

    def test_with_tgz_files(self, tmp_path: Path):
        chart_path: Path = tmp_path / "my-chart"
        charts_dir: Path = chart_path / "charts"
        charts_dir.mkdir(parents=True)

        (charts_dir / "dependency-1.0.0.tgz").write_text("fake archive")

        result: bool = has_packaged_dependencies(chart_path)
        assert result is True


class TestGetLocalChartVersion:
    def test_chart_exists(self, tmp_path: Path):
        chart_path: Path = tmp_path / "my-chart"
        chart_path.mkdir()

        (chart_path / "Chart.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "v2",
                    "name": "my-chart",
                    "version": "1.2.3",
                }
            )
        )

        version: str | None = get_local_chart_version(chart_path)
        assert version == "1.2.3"

    def test_chart_not_found(self, tmp_path: Path):
        nonexistent: Path = tmp_path / "nonexistent"

        version: str | None = get_local_chart_version(nonexistent)
        assert version is None


class TestGetRepoRoot:
    def test_returns_path(self):
        root: Path = get_repo_root()

        assert isinstance(root, Path)
        assert root.exists()

        assert (root / "pyproject.toml").exists() or (root / ".git").exists()


class TestEndToEndScenarios:
    def test_chart_scaffolding_to_validation(self, tmp_path: Path):
        charts_dir: Path = tmp_path / "charts"
        charts_dir.mkdir()

        scaffold_helm_chart(
            charts_dir,
            "test-service",
            description="Test service for e2e testing",
        )

        chart_path: Path = charts_dir / "test-service"
        assert (chart_path / "Chart.yaml").exists()
        assert (chart_path / "values.yaml").exists()
        assert (chart_path / "templates").exists()

        chart_yaml = yaml.safe_load((chart_path / "Chart.yaml").read_text())
        assert chart_yaml["name"] == "test-service"

        schemas_dir: Path = tmp_path / "schemas"
        schemas_dir.mkdir()

        scaffold_pydantic_schema(schemas_dir, "test-service")

        schema_path: Path = schemas_dir / "test_service"
        assert (schema_path / "__init__.py").exists()
        assert (schema_path / "values.py").exists()

        values_content: str = (schema_path / "values.py").read_text()
        compile(values_content, "values.py", "exec")

    def test_config_roundtrip_with_storage(self, tmp_path: Path):
        config_file: Path = tmp_path / ".rita.yaml"

        original = RitaConfig(
            auto_discover=False,
            environments=[
                EnvironmentConfig(
                    name="dev",
                    paths=["kubernetes/dev"],
                ),
                EnvironmentConfig(
                    name="prod",
                    paths=["kubernetes/prod"],
                ),
            ],
            charts=ChartConfig(
                path="charts",
                registry="ghcr.io/example/charts",
            ),
            render=RenderConfig(
                output_path="rendered-manifests",
                local_charts_only=True,
                compare_branch="main",
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="my-manifests-bucket",
                    s3_prefix="rendered",
                    aws_profile="dev-profile",
                    aws_region="eu-west-1",
                ),
            ),
        )

        save_config(original, config_file)

        loaded: RitaConfig = load_config(config_file)

        assert loaded.auto_discover == original.auto_discover
        assert len(loaded.environments) == 2
        assert loaded.environments[0].name == "dev"
        assert loaded.charts.registry == "ghcr.io/example/charts"
        assert loaded.render.storage is not None
        assert loaded.render.storage.type == "s3"
        assert loaded.render.storage.s3_bucket == "my-manifests-bucket"
        assert loaded.render.storage.aws_profile == "dev-profile"

    def test_local_storage_manifest_lifecycle(self, tmp_path: Path):
        storage = LocalStorageBackend(tmp_path)

        dev_app = ManifestRef(env="dev", app_name="my-app")
        prod_app = ManifestRef(env="prod", app_name="my-app")

        manifest_content = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
"""

        storage.write(dev_app, manifest_content)
        storage.write(prod_app, manifest_content.replace("replicas: 3", "replicas: 5"))
        assert storage.exists(dev_app)
        assert storage.exists(prod_app)

        dev_content: str | None = storage.read(dev_app)
        assert dev_content is not None
        assert "replicas: 3" in dev_content

        prod_content: str | None = storage.read(prod_app)
        assert prod_content is not None
        assert "replicas: 5" in prod_content

        all_refs: list[ManifestRef] = storage.list_manifests()
        assert len(all_refs) == 2

        dev_refs: list[ManifestRef] = storage.list_manifests(env="dev")
        assert len(dev_refs) == 1
        assert dev_refs[0].env == "dev"

        storage.delete(dev_app)
        assert not storage.exists(dev_app)
        assert storage.exists(prod_app)  # prod still exists

        remaining: list[ManifestRef] = storage.list_manifests()
        assert len(remaining) == 1
