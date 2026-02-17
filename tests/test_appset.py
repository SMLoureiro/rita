from pathlib import Path

from rita.argocd import (
    ArgoAppSetConfig,
    ArgoAppSetGeneratorElement,
    is_applicationset_chart,
    parse_applicationset_from_manifest,
)
from rita.helm import is_appset_producing_app
from rita.models import ArgoAppConfig


class TestApplicationSetDetection:
    def test_feature_deployment_is_appset_chart(self):
        assert is_applicationset_chart("feature-deployment") is True
        assert is_applicationset_chart("helm-charts/feature-deployment") is True

    def test_pharma_feature_deployment_is_appset_chart(self):
        assert is_applicationset_chart("pharma-feature-deployment") is True

    def test_regular_chart_not_appset(self):
        assert is_applicationset_chart("test-chart") is False
        assert is_applicationset_chart("dagster") is False

    def test_is_appset_producing_app(self):
        app = ArgoAppConfig(
            name="feature-patient-app",
            chart_repo="ghcr.io/SMLoureiro",
            chart_name="feature-deployment",
            chart_version="0.2.6",
            values_files=["feature-deployments/test-chart-1.yaml"],
            namespace="argocd",
            release_name="feature-patient-stack",
        )
        assert is_appset_producing_app(app) is True

    def test_regular_app_not_appset(self):
        app = ArgoAppConfig(
            name="test-chart",
            chart_repo="ghcr.io/SMLoureiro",
            chart_name="test-chart",
            chart_version="0.2.20",
            values_files=["kubernetes/test-chart/dev-values.yaml"],
            namespace="test-chart",
            release_name="test-chart",
        )
        assert is_appset_producing_app(app) is False


class TestApplicationSetParsing:
    def test_parse_applicationset_from_manifest(self):
        manifest = """
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: test-appset
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - name: app-config
            origin: patient-app-config
            version: "0.1.11"
            wave: "1"
            valuesFile: feature-values.yaml
          - name: app-stack
            origin: test-chart
            version: "0.2.14"
            wave: "2"
            valuesFile: feature-values.yaml
            dependsOn: app-config
  template:
    metadata:
      name: '{{name}}'
    spec:
      project: feature-deployments
      destination:
        server: https://kubernetes.default.svc
        namespace: test-namespace
      sources:
        - repoURL: ghcr.io/SMLoureiro
          chart: 'helm-charts/{{origin}}'
          targetRevision: '{{version}}'
          helm:
            valueFiles:
              - "$values/kubernetes/{{origin}}/{{valuesFile}}"
            valuesObject:
              global:
                featureBranch:
                  enabled: true
"""
        appset: ArgoAppSetConfig | None = parse_applicationset_from_manifest(manifest)

        assert appset is not None
        assert appset.name == "test-appset"
        assert appset.namespace == "argocd"
        assert len(appset.generator_elements) == 2

        # Check first element
        elem1: ArgoAppSetGeneratorElement = appset.generator_elements[0]
        assert elem1.name == "app-config"
        assert elem1.chart_name == "patient-app-config"
        assert elem1.chart_version == "0.1.11"
        assert elem1.wave == "1"

        # Check second element
        elem2: ArgoAppSetGeneratorElement = appset.generator_elements[1]
        assert elem2.name == "app-stack"
        assert elem2.chart_name == "test-chart"
        assert elem2.chart_version == "0.2.14"
        assert elem2.depends_on == "app-config"

    def test_parse_non_applicationset_returns_none(self):
        manifest = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-deployment
"""
        appset: ArgoAppSetConfig | None = parse_applicationset_from_manifest(manifest)
        assert appset is None

    def test_parse_empty_manifest_returns_none(self):
        assert parse_applicationset_from_manifest("") is None
        assert parse_applicationset_from_manifest("---") is None


class TestApplicationSetToAppConfigs:
    def test_to_app_configs(self):
        manifest = """
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: test-appset
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - name: test-app
            origin: test-chart
            version: "0.2.14"
            wave: "1"
            valuesFile: feature-values.yaml
  template:
    metadata:
      name: '{{name}}'
    spec:
      destination:
        server: https://kubernetes.default.svc
        namespace: test-feature-namespace
      sources:
        - repoURL: ghcr.io/SMLoureiro
          chart: 'helm-charts/{{origin}}'
          targetRevision: '{{version}}'
"""
        appset: ArgoAppSetConfig | None = parse_applicationset_from_manifest(manifest)
        assert appset is not None

        def mock_resolver(name: str) -> Path:
            return Path("/fake/charts") / name

        apps: list[ArgoAppConfig] = appset.to_app_configs(
            mock_resolver, Path("/fake/repo")
        )

        assert len(apps) == 1
        app: ArgoAppConfig = apps[0]
        assert app.name == "test-app"
        assert app.chart_name == "test-chart"
        assert app.chart_version == "0.2.14"
        assert app.namespace == "test-feature-namespace"
