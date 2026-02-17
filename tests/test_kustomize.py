from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rita.kustomize import render_kustomize, render_plain_manifests


class TestRenderPlainManifests:
    def test_render_plain_manifests_success(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()

        (manifests_dir / "deployment.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": "my-app"},
                    "spec": {"replicas": 3},
                }
            )
        )

        (manifests_dir / "service.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": "my-service"},
                    "spec": {"type": "ClusterIP"},
                }
            )
        )

        output_dir: Path = tmp_path / "output"
        success, _message = render_plain_manifests(manifests_dir, output_dir)

        assert success is True
        assert output_dir.exists()

        all_yaml: Path = output_dir / "_all.yaml"
        assert all_yaml.exists()

        content: str = all_yaml.read_text()
        assert "kind: Deployment" in content
        assert "kind: Service" in content
        assert "my-app" in content
        assert "my-service" in content

    def test_render_plain_manifests_with_yml_extension(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()

        (manifests_dir / "config.yml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": "my-config"},
                }
            )
        )

        output_dir: Path = tmp_path / "output"
        success, _message = render_plain_manifests(manifests_dir, output_dir)

        assert success is True
        all_yaml: Path = output_dir / "_all.yaml"
        content: str = all_yaml.read_text()
        assert "kind: ConfigMap" in content

    def test_render_plain_manifests_multiple_documents(self, tmp_path: Path):
        manifests_dir: Path = tmp_path / "manifests"
        manifests_dir.mkdir()

        (manifests_dir / "resources.yaml").write_text("""
apiVersion: v1
kind: Namespace
metadata:
  name: my-namespace
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-sa
  namespace: my-namespace
""")

        output_dir: Path = tmp_path / "output"
        success, _message = render_plain_manifests(manifests_dir, output_dir)

        assert success is True
        all_yaml: Path = output_dir / "_all.yaml"
        content: str = all_yaml.read_text()
        assert "kind: Namespace" in content
        assert "kind: ServiceAccount" in content

    def test_render_plain_manifests_directory_not_found(self, tmp_path: Path):
        nonexistent: Path = tmp_path / "nonexistent"
        output_dir: Path = tmp_path / "output"

        success, message = render_plain_manifests(nonexistent, output_dir)

        assert success is False
        assert "not found" in message

    def test_render_plain_manifests_not_a_directory(self, tmp_path: Path):
        file_path: Path = tmp_path / "not_a_dir.txt"
        file_path.write_text("some content")

        output_dir: Path = tmp_path / "output"
        success, message = render_plain_manifests(file_path, output_dir)

        assert success is False
        assert "not a directory" in message

    def test_render_plain_manifests_no_yaml_files(self, tmp_path: Path):
        manifests_dir: Path = tmp_path / "manifests"
        manifests_dir.mkdir()

        (manifests_dir / "readme.txt").write_text("This is not YAML")
        (manifests_dir / "config.json").write_text('{"key": "value"}')

        output_dir: Path = tmp_path / "output"
        success, message = render_plain_manifests(manifests_dir, output_dir)

        assert success is False
        assert "No YAML files found" in message

    def test_render_plain_manifests_creates_per_kind_files(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()

        for i in range(2):
            (manifests_dir / f"deployment-{i}.yaml").write_text(
                yaml.safe_dump(
                    {
                        "apiVersion": "apps/v1",
                        "kind": "Deployment",
                        "metadata": {"name": f"app-{i}"},
                    }
                )
            )

        (manifests_dir / "service.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": "my-service"},
                }
            )
        )

        output_dir = tmp_path / "output"
        success, _message = render_plain_manifests(manifests_dir, output_dir)

        assert success is True

        deployment_file = output_dir / "deployment.yaml"
        service_file = output_dir / "service.yaml"

        assert deployment_file.exists()
        assert service_file.exists()

        deployment_content = deployment_file.read_text()
        assert "app-0" in deployment_content
        assert "app-1" in deployment_content


class TestRenderKustomize:
    def test_render_kustomize_missing_kustomization_file(self, tmp_path: Path):
        kustomize_dir: Path = tmp_path / "kustomize"
        kustomize_dir.mkdir()

        output_dir: Path = tmp_path / "output"
        success, message = render_kustomize(kustomize_dir, output_dir)

        assert success is False
        assert "No kustomization.yaml found" in message

    def test_render_kustomize_directory_not_found(self, tmp_path: Path):
        nonexistent: Path = tmp_path / "nonexistent"
        output_dir: Path = tmp_path / "output"

        success, message = render_kustomize(nonexistent, output_dir)

        assert success is False
        assert "does not exist" in message


class TestKustomizeIntegration:
    @pytest.mark.skipif(
        not Path("/usr/bin/kubectl").exists()
        and not Path("/usr/local/bin/kubectl").exists(),
        reason="kubectl not available",
    )
    def test_render_real_kustomize_directory(self, tmp_path: Path):
        kustomize_dir: Path = tmp_path / "kustomize"
        kustomize_dir.mkdir()

        (kustomize_dir / "kustomization.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "kustomize.config.k8s.io/v1beta1",
                    "kind": "Kustomization",
                    "resources": ["deployment.yaml"],
                }
            )
        )

        (kustomize_dir / "deployment.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": "test-app"},
                    "spec": {
                        "replicas": 1,
                        "selector": {"matchLabels": {"app": "test"}},
                        "template": {
                            "metadata": {"labels": {"app": "test"}},
                            "spec": {
                                "containers": [{"name": "test", "image": "nginx"}]
                            },
                        },
                    },
                }
            )
        )

        output_dir: Path = tmp_path / "output"
        success, _message = render_kustomize(kustomize_dir, output_dir)

        if success:
            assert output_dir.exists()
            all_yaml: Path = output_dir / "_all.yaml"
            assert all_yaml.exists()

            content: str = all_yaml.read_text()
            assert "kind: Deployment" in content
            assert "test-app" in content
