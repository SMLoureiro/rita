from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from rita.testing import (
    ChartTestResult,
    KindClusterManager,
    check_helm_installed,
    check_kind_installed,
    check_kubectl_installed,
    cluster_exists,
)


class TestChartTestResultDataclass:
    def test_success_result(self):
        result = ChartTestResult(
            chart_name="my-chart",
            success=True,
            message="Test passed successfully",
            duration_seconds=5.2,
        )

        assert result.chart_name == "my-chart"
        assert result.success is True
        assert result.message == "Test passed successfully"
        assert result.duration_seconds == 5.2
        assert result.details is None

    def test_failure_result(self):
        result = ChartTestResult(
            chart_name="failing-chart",
            success=False,
            message="Deployment failed",
            duration_seconds=10.0,
            details={"error": "ImagePullBackOff"},
        )

        assert result.success is False
        assert "failed" in result.message.lower()
        assert result.details is not None

    def test_result_with_details(self):
        result = ChartTestResult(
            chart_name="test-chart",
            success=True,
            message="Quick test",
            duration_seconds=0.5,
            details={"pods": 3, "services": 1},
        )

        assert result.details is not None
        assert result.details["pods"] == 3


class TestToolChecks:
    @patch("subprocess.run")
    def test_check_kind_installed_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        result = check_kind_installed()

        assert result is True
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_check_kind_installed_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()

        result = check_kind_installed()

        assert result is False

    @patch("subprocess.run")
    def test_check_kubectl_installed_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        result: bool = check_kubectl_installed()

        assert result is True

    @patch("subprocess.run")
    def test_check_kubectl_installed_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()

        result: bool = check_kubectl_installed()

        assert result is False

    @patch("subprocess.run")
    def test_check_helm_installed_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        result: bool = check_helm_installed()

        assert result is True

    @patch("subprocess.run")
    def test_check_helm_installed_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()

        result: bool = check_helm_installed()

        assert result is False


class TestClusterExists:
    @patch("subprocess.run")
    def test_cluster_exists_true(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="my-cluster\nother-cluster\n",
        )

        result: bool = cluster_exists("my-cluster")

        assert result is True

    @patch("subprocess.run")
    def test_cluster_exists_false(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="other-cluster\n",
        )

        result: bool = cluster_exists("my-cluster")

        assert result is False

    @patch("subprocess.run")
    def test_cluster_exists_command_fails(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "kind")

        result: bool = cluster_exists("any-cluster")

        assert result is False


class TestKindClusterManager:
    def test_manager_initialization(self):
        manager = KindClusterManager(cluster_name="test-cluster")

        assert manager.cluster_name == "test-cluster"
        assert manager.cleanup_on_success is True
        assert manager.cleanup_on_failure is False

    def test_manager_initialization_with_cleanup_options(self):
        manager = KindClusterManager(
            cluster_name="persistent-cluster",
            cleanup_on_success=False,
            cleanup_on_failure=True,
        )

        assert manager.cleanup_on_success is False
        assert manager.cleanup_on_failure is True

    @patch("rita.testing.cluster_exists")
    @patch("rita.testing.create_kind_cluster")
    @patch("rita.testing.set_kubectl_context")
    @patch("click.echo")
    def test_manager_enter_creates_cluster(
        self,
        _mock_echo,
        mock_set_context,
        mock_create,
        mock_exists,
    ):
        mock_exists.return_value = False
        mock_create.return_value = (True, "Cluster created")
        mock_set_context.return_value = (True, "Context set")

        manager = KindClusterManager(cluster_name="new-cluster")
        result: KindClusterManager = manager.__enter__()

        assert result is manager
        mock_create.assert_called_once()

    @patch("rita.testing.cluster_exists")
    @patch("rita.testing.create_kind_cluster")
    @patch("rita.testing.set_kubectl_context")
    @patch("click.echo")
    def test_manager_enter_reuses_existing(
        self,
        _mock_echo,
        mock_set_context,
        mock_create,
        mock_exists,
    ):
        mock_exists.return_value = True
        mock_set_context.return_value = (True, "Context set")

        manager = KindClusterManager(cluster_name="existing-cluster")
        manager.__enter__()

        mock_create.assert_not_called()


class TestIntegrationScenarios:
    def test_test_result_serialization(self):
        result = ChartTestResult(
            chart_name="my-chart",
            success=True,
            message="All pods ready",
            duration_seconds=15.5,
            details={"pods": 3},
        )

        result_dict = {
            "chart_name": result.chart_name,
            "success": result.success,
            "message": result.message,
            "duration_seconds": result.duration_seconds,
            "details": result.details,
        }

        details_value = result_dict.get("details")
        restored = ChartTestResult(
            chart_name=str(result_dict["chart_name"]),
            success=bool(result_dict["success"]),
            message=str(result_dict["message"]),
            duration_seconds=float(result_dict["duration_seconds"]),
            details=details_value if isinstance(details_value, dict) else None,
        )

        assert restored.success == result.success
        assert restored.message == result.message
        assert restored.chart_name == result.chart_name

    @patch("subprocess.run")
    def test_all_tools_check_in_sequence(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        tools_available = {
            "kind": check_kind_installed(),
            "kubectl": check_kubectl_installed(),
            "helm": check_helm_installed(),
        }

        assert all(tools_available.values())

    def test_manager_handles_creation_failure(self):
        with patch("rita.testing.cluster_exists", return_value=False), patch("rita.testing.create_kind_cluster") as mock_create:
            mock_create.return_value = (False, "Failed to create cluster")

            manager = KindClusterManager(cluster_name="failing-cluster")

            with pytest.raises(RuntimeError):
                manager.__enter__()
