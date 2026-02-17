"""Tests for the config module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from rita.config import (
    ChartConfig,
    ChartTestConfig,
    EnvironmentConfig,
    RenderConfig,
    RitaConfig,
    StorageConfig,
    find_config_file,
    generate_default_config,
    load_config,
    save_config,
)


class TestStorageConfig:
    """Tests for StorageConfig dataclass."""

    def test_defaults(self):
        """Test default values."""
        config = StorageConfig()
        assert config.type == "local"
        assert config.s3_bucket is None
        assert config.s3_prefix == "rendered-manifests"
        assert config.aws_profile is None
        assert config.aws_region is None

    def test_s3_config(self):
        """Test S3 configuration."""
        config = StorageConfig(
            type="s3",
            s3_bucket="my-bucket",
            s3_prefix="manifests",
            aws_profile="dev",
            aws_region="eu-central-1",
        )
        assert config.type == "s3"
        assert config.s3_bucket == "my-bucket"
        assert config.s3_prefix == "manifests"
        assert config.aws_profile == "dev"
        assert config.aws_region == "eu-central-1"
        assert config.s3_endpoint is None

    def test_s3_endpoint_config(self):
        """Test S3-compatible storage with custom endpoint."""
        config = StorageConfig(
            type="s3",
            s3_bucket="my-bucket",
            s3_prefix="manifests",
            s3_endpoint="http://localhost:3900",
            aws_region="auto",
        )
        assert config.type == "s3"
        assert config.s3_bucket == "my-bucket"
        assert config.s3_endpoint == "http://localhost:3900"
        assert config.aws_region == "auto"
        assert config.aws_profile is None

    def test_s3_endpoint_roundtrip(self):
        """Test s3_endpoint survives to_dict/from_dict roundtrip via RitaConfig."""
        storage = StorageConfig(
            type="s3",
            s3_bucket="garage-bucket",
            s3_prefix="rendered",
            s3_endpoint="http://garage.local:3900",
        )
        config = RitaConfig(
            render=RenderConfig(storage=storage),
        )
        data = config.to_dict()
        restored = RitaConfig.from_dict(data)

        assert restored.render.storage is not None
        assert restored.render.storage.s3_endpoint == "http://garage.local:3900"
        assert restored.render.storage.s3_bucket == "garage-bucket"


class TestRenderConfig:
    """Tests for RenderConfig dataclass."""

    def test_defaults(self):
        """Test default values."""
        config = RenderConfig()
        assert config.output_path == "rendered"
        assert config.local_charts_only is True
        assert config.storage is None
        assert config.compare_branch == "main"

    def test_with_storage(self):
        """Test with storage configuration."""
        storage = StorageConfig(type="s3", s3_bucket="bucket")
        config = RenderConfig(storage=storage, compare_branch="develop")

        assert config.storage is not None
        assert config.storage.type == "s3"
        assert config.compare_branch == "develop"


class TestRitaConfig:
    """Tests for RitaConfig dataclass."""

    def test_get_default(self):
        config: RitaConfig = RitaConfig.get_default()

        assert len(config.environments) == 2
        assert config.environments[0].name == "dev"
        assert config.environments[1].name == "prod"
        assert config.auto_discover is True

    def test_from_dict(self):
        data = {
            "auto_discover": False,
            "environments": [
                {
                    "name": "staging",
                    "paths": ["kubernetes/staging"],
                }
            ],
            "charts": {
                "path": "helm-charts",
                "registry": "ghcr.io/example",
            },
            "render": {
                "output_path": "output",
                "local_charts_only": False,
                "compare_branch": "develop",
                "storage": {
                    "type": "s3",
                    "s3_bucket": "test-bucket",
                    "s3_prefix": "rendered",
                    "aws_profile": "staging",
                    "aws_region": "us-west-2",
                },
            },
        }

        config: RitaConfig = RitaConfig.from_dict(data)

        assert config.auto_discover is False
        assert len(config.environments) == 1
        assert config.environments[0].name == "staging"
        assert config.charts.path == "helm-charts"
        assert config.charts.registry == "ghcr.io/example"
        assert config.render.output_path == "output"
        assert config.render.local_charts_only is False
        assert config.render.compare_branch == "develop"
        assert config.render.storage is not None
        assert config.render.storage.type == "s3"
        assert config.render.storage.s3_bucket == "test-bucket"

    def test_to_dict(self):
        config = RitaConfig(
            auto_discover=True,
            environments=[
                EnvironmentConfig(name="test", paths=["test/path"]),
            ],
            charts=ChartConfig(path="charts", registry="ghcr.io/test"),
            render=RenderConfig(
                output_path="rendered",
                local_charts_only=True,
                compare_branch="main",
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="bucket",
                    aws_profile="profile",
                ),
            ),
            test=ChartTestConfig(),
        )

        data: dict[str, Any] = config.to_dict()

        assert data["auto_discover"] is True
        assert len(data["environments"]) == 1
        assert data["environments"][0]["name"] == "test"
        assert data["charts"]["path"] == "charts"
        assert data["render"]["output_path"] == "rendered"
        assert data["render"]["compare_branch"] == "main"
        assert data["render"]["storage"]["type"] == "s3"
        assert data["render"]["storage"]["s3_bucket"] == "bucket"

    def test_to_dict_without_storage(self):
        config: RitaConfig = RitaConfig.get_default()
        data: dict[str, Any] = config.to_dict()

        assert "storage" not in data["render"]

    def test_roundtrip(self):
        original = RitaConfig(
            auto_discover=False,
            environments=[
                EnvironmentConfig(
                    name="test",
                    paths=["path1", "path2"],
                    include_patterns=["*.yaml"],
                    exclude_patterns=["secrets/*"],
                ),
            ],
            charts=ChartConfig(path="charts", registry="registry"),
            render=RenderConfig(
                output_path="output",
                local_charts_only=False,
                compare_branch="develop",
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="bucket",
                    s3_prefix="prefix",
                    aws_profile="profile",
                    aws_region="region",
                ),
            ),
            test=ChartTestConfig(
                kind_cluster_name="test-cluster",
                timeout_seconds=600,
            ),
        )

        data: dict[str, Any] = original.to_dict()
        restored: RitaConfig = RitaConfig.from_dict(data)

        assert restored.auto_discover == original.auto_discover
        assert len(restored.environments) == len(original.environments)
        assert restored.environments[0].name == original.environments[0].name
        assert restored.render.storage is not None
        assert original.render.storage is not None
        assert restored.render.storage.s3_bucket == original.render.storage.s3_bucket


class ChartTestConfigIO:
    """Tests for config file I/O functions."""

    def test_find_config_file(self, tmp_path: Path):
        nested: Path = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)

        config_file: Path = tmp_path / "a" / ".rita.yaml"
        config_file.write_text("auto_discover: true\n")

        found: Path | None = find_config_file(nested)
        assert found == config_file

    def test_find_config_file_not_found(self, tmp_path: Path):
        """Test when no config file exists."""
        nested: Path = tmp_path / "a" / "b"
        nested.mkdir(parents=True)

        found: Path | None = find_config_file(nested)
        assert found is None

    def test_load_config_from_file(self, tmp_path: Path):
        """Test loading config from a file."""
        config_file: Path = tmp_path / ".rita.yaml"
        config_data = {
            "auto_discover": False,
            "environments": [
                {"name": "staging", "paths": ["staging"]},
            ],
        }
        config_file.write_text(yaml.safe_dump(config_data))

        config: RitaConfig = load_config(config_file)

        assert config.auto_discover is False
        assert len(config.environments) == 1
        assert config.environments[0].name == "staging"

    def test_load_config_defaults(self):
        config: RitaConfig = load_config(Path("/nonexistent/.rita.yaml"))

        assert config.auto_discover is True
        assert len(config.environments) == 2

    def test_save_config(self, tmp_path: Path):
        config_file: Path = tmp_path / ".rita.yaml"
        config = RitaConfig(
            environments=[
                EnvironmentConfig(name="test", paths=["test"]),
            ],
            render=RenderConfig(
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="bucket",
                ),
            ),
        )

        save_config(config, config_file)

        assert config_file.exists()
        loaded: RitaConfig = load_config(config_file)
        assert loaded.environments[0].name == "test"
        assert loaded.render.storage is not None
        assert loaded.render.storage.s3_bucket == "bucket"

    def test_generate_default_config(self):
        yaml_str: str = generate_default_config()

        assert "auto_discover" in yaml_str
        assert "environments" in yaml_str
        assert "dev" in yaml_str
        assert "prod" in yaml_str

        data = yaml.safe_load(yaml_str)
        assert data["auto_discover"] is True


class TestEnvironmentConfig:
    """Tests for EnvironmentConfig dataclass."""

    def test_defaults(self):
        config = EnvironmentConfig(name="test")

        assert config.name == "test"
        assert config.paths == []
        assert "**/*.yaml" in config.include_patterns
        assert "**/secrets/**" in config.exclude_patterns

    def test_with_patterns(self):
        """Test with custom patterns."""
        config = EnvironmentConfig(
            name="prod",
            paths=["kubernetes/prod"],
            include_patterns=["*.yaml"],
            exclude_patterns=["test/*"],
        )

        assert config.include_patterns == ["*.yaml"]
        assert config.exclude_patterns == ["test/*"]


class TestChartConfig:
    """Tests for ChartConfig dataclass."""

    def test_defaults(self):
        config = ChartConfig()

        assert config.path == "charts"
        assert config.registry == "ghcr.io/SMLoureiro"

    def test_custom(self):
        config = ChartConfig(path="helm-charts", registry="docker.io/example")

        assert config.path == "helm-charts"
        assert config.registry == "docker.io/example"


class TestChartTestConfig:
    """Tests for ChartTestConfig dataclass."""

    def test_defaults(self):
        config = ChartTestConfig()

        assert config.kind_cluster_name == "rita-test"
        assert config.timeout_seconds == 300
        assert config.cleanup_on_success is True
        assert config.cleanup_on_failure is False
        assert config.pre_install_manifests == []
