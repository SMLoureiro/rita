from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from rita.argocd import ArgoAppConfig, parse_argocd_application


class TestParseArgoCDWithKustomize:
    def test_parse_pure_kustomize_application(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        app_yaml = tmp_path / "kustomize-app.yaml"

        kustomize_dir = tmp_path / "manifests" / "overlays" / "dev"
        kustomize_dir.mkdir(parents=True)
        (kustomize_dir / "kustomization.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "kustomize.config.k8s.io/v1beta1",
                    "kind": "Kustomization",
                    "resources": ["../../base"],
                }
            )
        )

        app_yaml.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    "metadata": {"name": "rabbitmq-operator"},
                    "spec": {
                        "source": {
                            "repoURL": "https://github.com/example/repo",
                            "path": "manifests/overlays/dev",
                            "targetRevision": "main",
                        },
                        "destination": {
                            "server": "https://kubernetes.default.svc",
                            "namespace": "rabbitmq-system",
                        },
                    },
                }
            )
        )

        def mock_resolver(chart_name: str) -> Path:
            return tmp_path / "charts" / chart_name

        config: ArgoAppConfig | None = parse_argocd_application(app_yaml, mock_resolver)

        assert config is not None
        assert config.name == "rabbitmq-operator"
        assert config.is_kustomize is True
        assert config.kustomize_path == "manifests/overlays/dev"
        assert config.chart_name == ""
        assert config.plain_manifests_path is None

    def test_parse_helm_plus_kustomize_application(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        app_yaml: Path = tmp_path / "combined-app.yaml"

        kustomize_dir: Path = tmp_path / "overlays" / "dev"
        kustomize_dir.mkdir(parents=True)
        (kustomize_dir / "kustomization.yaml").write_text(
            "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization"
        )

        app_yaml.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    "metadata": {"name": "combined-app"},
                    "spec": {
                        "sources": [
                            {
                                "repoURL": "https://charts.example.com",
                                "chart": "my-chart",
                                "targetRevision": "1.0.0",
                                "helm": {
                                    "releaseName": "my-release",
                                    "valueFiles": ["values.yaml"],
                                },
                            },
                            {
                                "repoURL": "https://github.com/example/repo",
                                "path": "overlays/dev",
                                "targetRevision": "main",
                            },
                        ],
                        "destination": {
                            "server": "https://kubernetes.default.svc",
                            "namespace": "default",
                        },
                    },
                }
            )
        )

        def mock_resolver(chart_name: str) -> Path:
            return tmp_path / "charts" / chart_name

        config = parse_argocd_application(app_yaml, mock_resolver)

        assert config is not None
        assert config.name == "combined-app"
        assert config.chart_name == "my-chart"
        assert config.is_kustomize is True
        assert config.kustomize_path == "overlays/dev"
        assert config.plain_manifests_path is None


class TestParseArgoCDWithPlainYAML:
    def test_parse_helm_plus_plain_yaml_application(self, tmp_path: Path):
        app_yaml: Path = tmp_path / "kargo-app.yaml"

        manifests_dir: Path = tmp_path / "kargo" / "base"
        manifests_dir.mkdir(parents=True)

        (manifests_dir / "project.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "kargo.akuity.io/v1alpha1",
                    "kind": "Project",
                    "metadata": {"name": "my-project"},
                }
            )
        )

        app_yaml.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    "metadata": {"name": "kargo"},
                    "spec": {
                        "sources": [
                            {
                                "repoURL": "https://charts.example.com",
                                "chart": "kargo",
                                "targetRevision": "0.8.0",
                                "helm": {"releaseName": "kargo"},
                            },
                            {
                                "repoURL": "https://github.com/example/repo",
                                "path": "kargo/base",
                                "targetRevision": "main",
                            },
                        ],
                        "destination": {
                            "server": "https://kubernetes.default.svc",
                            "namespace": "kargo",
                        },
                    },
                }
            )
        )

        def mock_resolver(chart_name: str) -> Path:
            return tmp_path / "charts" / chart_name

        config: ArgoAppConfig | None = parse_argocd_application(app_yaml, mock_resolver)

        assert config is not None
        assert config.name == "kargo"
        assert config.chart_name == "kargo"
        assert config.is_kustomize is False
        assert config.kustomize_path is None
        assert config.plain_manifests_path == "kargo/base"

    def test_parse_pure_plain_yaml_application(self, tmp_path: Path):
        app_yaml: Path = tmp_path / "plain-app.yaml"

        manifests_dir: Path = tmp_path / "manifests"
        manifests_dir.mkdir()
        (manifests_dir / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": "my-config"},
                }
            )
        )

        app_yaml.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    "metadata": {"name": "plain-manifests"},
                    "spec": {
                        "source": {
                            "repoURL": "https://github.com/example/repo",
                            "path": "manifests",
                            "targetRevision": "main",
                        },
                        "destination": {
                            "server": "https://kubernetes.default.svc",
                            "namespace": "default",
                        },
                    },
                }
            )
        )

        def mock_resolver(chart_name: str) -> Path:
            return tmp_path / "charts" / chart_name

        config: ArgoAppConfig | None = parse_argocd_application(app_yaml, mock_resolver)

        assert config is not None
        assert config.name == "plain-manifests"
        assert config.chart_name == ""
        assert config.is_kustomize is False
        assert config.kustomize_path is None
        assert config.plain_manifests_path == "manifests"

    def test_distinguish_kustomize_from_plain_yaml(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        app_yaml_kustomize: Path = tmp_path / "kustomize-app.yaml"
        app_yaml_plain: Path = tmp_path / "plain-app.yaml"

        kustomize_dir: Path = tmp_path / "kustomize-dir"
        kustomize_dir.mkdir()
        (kustomize_dir / "kustomization.yaml").write_text(
            "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization"
        )

        plain_dir: Path = tmp_path / "plain-dir"
        plain_dir.mkdir()
        (plain_dir / "deployment.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment"
        )

        app_yaml_kustomize.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    "metadata": {"name": "kustomize-test"},
                    "spec": {
                        "source": {
                            "path": "kustomize-dir",
                            "repoURL": "https://github.com/example/repo",
                        },
                        "destination": {"namespace": "default"},
                    },
                }
            )
        )

        app_yaml_plain.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    "metadata": {"name": "plain-test"},
                    "spec": {
                        "source": {
                            "path": "plain-dir",
                            "repoURL": "https://github.com/example/repo",
                        },
                        "destination": {"namespace": "default"},
                    },
                }
            )
        )

        def mock_resolver(chart_name: str) -> Path:
            return tmp_path / "charts" / chart_name

        kustomize_config: ArgoAppConfig | None = parse_argocd_application(
            app_yaml_kustomize, mock_resolver
        )
        assert kustomize_config is not None
        assert kustomize_config.is_kustomize is True
        assert kustomize_config.kustomize_path == "kustomize-dir"
        assert kustomize_config.plain_manifests_path is None

        plain_config: ArgoAppConfig | None = parse_argocd_application(
            app_yaml_plain, mock_resolver
        )
        assert plain_config is not None
        assert plain_config.is_kustomize is False
        assert plain_config.kustomize_path is None
        assert plain_config.plain_manifests_path == "plain-dir"


class TestParseArgoCDBackwardsCompatibility:
    def test_parse_helm_only_application_unchanged(self, tmp_path: Path):
        app_yaml: Path = tmp_path / "helm-app.yaml"

        app_yaml.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    "metadata": {"name": "patient-app-stack"},
                    "spec": {
                        "source": {
                            "repoURL": "https://charts.example.com",
                            "chart": "patient-app-stack",
                            "targetRevision": "1.0.0",
                            "helm": {
                                "releaseName": "patient-app",
                                "valueFiles": ["values-dev.yaml"],
                            },
                        },
                        "destination": {
                            "server": "https://kubernetes.default.svc",
                            "namespace": "patient-app",
                        },
                    },
                }
            )
        )

        def mock_resolver(chart_name: str) -> Path:
            return tmp_path / "charts" / chart_name

        config: ArgoAppConfig | None = parse_argocd_application(app_yaml, mock_resolver)

        assert config is not None
        assert config.name == "patient-app-stack"
        assert config.chart_name == "patient-app-stack"
        assert config.is_kustomize is False
        assert config.kustomize_path is None
        assert config.plain_manifests_path is None
        assert config.values_files == ["values-dev.yaml"]
