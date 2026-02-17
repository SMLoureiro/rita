"""Tests for the init command module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from click.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

from rita.commands.init_cmd import init
from rita.config import ChartConfig, EnvironmentConfig, RenderConfig, RitaConfig, StorageConfig


class TestInitCommand:
    """Tests for the init command."""

    def test_init_command_exists(self):
        """Test that init command is defined."""
        assert init is not None
        assert init.name == "init"

    def test_init_command_has_force_option(self):
        """Test that init command has --force option."""
        param_names = [p.name for p in init.params]
        assert "force" in param_names

    def test_init_command_has_minimal_option(self):
        """Test that init command has --minimal option."""
        param_names = [p.name for p in init.params]
        assert "minimal" in param_names

    @patch("rita.commands.init_cmd.get_repo_root")
    def test_init_fails_outside_git_repo(self, mock_get_repo_root):
        """Test that init fails when not in a git repository."""
        mock_get_repo_root.side_effect = Exception("Not a git repository")

        runner = CliRunner()
        result = runner.invoke(init)

        assert result.exit_code == 1
        assert "Not in a git repository" in result.output

    @patch("rita.commands.init_cmd.get_repo_root")
    def test_init_fails_if_config_exists_without_force(self, mock_get_repo_root, tmp_path: Path):
        """Test that init fails if config already exists without --force."""
        mock_get_repo_root.return_value = tmp_path

        config_file: Path = tmp_path / ".rita.yaml"
        config_file.write_text("auto_discover: true\n")

        runner = CliRunner()
        result = runner.invoke(init)

        assert result.exit_code == 1
        assert "already exists" in result.output

    @patch("rita.commands.init_cmd.get_repo_root")
    @patch("rita.commands.init_cmd.save_config")
    @patch("rita.commands.init_cmd.Prompt.ask")
    @patch("rita.commands.init_cmd.Confirm.ask")
    def test_init_minimal_mode(
        self, mock_confirm, mock_prompt, mock_save_config, mock_get_repo_root, tmp_path: Path
    ):
        """Test init command in minimal mode."""
        mock_get_repo_root.return_value = tmp_path

        # Mock user inputs
        mock_prompt.side_effect = ["charts", "ghcr.io/myorg"]
        mock_confirm.return_value = True  # Save configuration

        runner = CliRunner()
        result = runner.invoke(init, ["--minimal"])

        assert result.exit_code == 0
        mock_save_config.assert_called_once()

        saved_config = mock_save_config.call_args[0][0]
        assert isinstance(saved_config, RitaConfig)
        assert saved_config.charts.path == "charts"
        assert saved_config.charts.registry == "ghcr.io/myorg"
        assert len(saved_config.environments) == 2
        assert saved_config.environments[0].name == "dev"
        assert saved_config.environments[1].name == "prod"


class TestStorageConfigPrompts:
    """Tests for storage configuration prompt functions."""

    def test_s3_compatible_config_structure(self):
        """Test that S3-compatible config creates correct StorageConfig."""
        storage = StorageConfig(
            type="s3",
            s3_bucket="garage-bucket",
            s3_prefix="rendered",
            s3_endpoint="http://garage.local:3900",
            aws_region="auto",
        )

        assert storage.type == "s3"
        assert storage.s3_bucket == "garage-bucket"
        assert storage.s3_endpoint == "http://garage.local:3900"
        assert storage.aws_region == "auto"
        assert storage.aws_profile is None

    def test_aws_s3_config_structure(self):
        """Test that AWS S3 config creates correct StorageConfig."""
        storage = StorageConfig(
            type="s3",
            s3_bucket="my-bucket",
            s3_prefix="manifests",
            aws_region="eu-central-1",
            aws_profile="dev-profile",
        )

        assert storage.type == "s3"
        assert storage.s3_bucket == "my-bucket"
        assert storage.s3_endpoint is None
        assert storage.aws_region == "eu-central-1"
        assert storage.aws_profile == "dev-profile"


class TestEnvironmentConfigPrompts:
    """Tests for environment configuration."""

    def test_default_environment_config(self):
        """Test default dev/prod environment configuration."""
        dev_env = EnvironmentConfig(
            name="dev",
            paths=["kubernetes/argocd/applications/dev/templates"],
            aliases=["development", "staging"],
        )
        prod_env = EnvironmentConfig(
            name="prod",
            paths=["kubernetes/argocd/applications/prod/templates"],
            aliases=["production"],
        )

        assert dev_env.name == "dev"
        assert "development" in dev_env.aliases
        assert prod_env.name == "prod"
        assert "production" in prod_env.aliases


class TestChartConfigPrompts:
    """Tests for chart configuration."""

    def test_chart_config_structure(self):
        """Test chart config structure."""
        chart_config = ChartConfig(
            path="charts",
            registry="ghcr.io/myorg",
        )

        assert chart_config.path == "charts"
        assert chart_config.registry == "ghcr.io/myorg"


class TestRenderConfigPrompts:
    """Tests for render configuration."""

    def test_render_config_with_storage(self):
        """Test render config with storage backend."""
        storage = StorageConfig(
            type="s3",
            s3_bucket="test-bucket",
        )
        render_config = RenderConfig(
            output_path="rendered",
            local_charts_only=True,
            storage=storage,
            compare_branch="main",
        )

        assert render_config.output_path == "rendered"
        assert render_config.local_charts_only is True
        assert render_config.storage is not None
        assert render_config.storage.type == "s3"
        assert render_config.compare_branch == "main"

    def test_render_config_without_storage(self):
        """Test render config without storage (local filesystem)."""
        render_config = RenderConfig(
            output_path="rendered",
            local_charts_only=True,
            compare_branch="main",
        )

        assert render_config.storage is None
