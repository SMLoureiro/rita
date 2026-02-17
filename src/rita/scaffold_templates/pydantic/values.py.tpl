"""{{ title }} Helm chart values schema."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContainerImage(BaseModel):
    """Container image configuration."""

    repository: str = Field(default="", description="Image repository")
    tag: str = Field(default="latest", description="Image tag")
    pullPolicy: str = Field(default="IfNotPresent", description="Image pull policy")


class ServiceAccount(BaseModel):
    """ServiceAccount configuration."""

    create: bool = Field(default=True, description="Create service account")
    automount: bool = Field(default=True, description="Automount API credentials")
    annotations: dict[str, str] = Field(default_factory=dict, description="Annotations")
    name: str = Field(default="", description="Service account name override")


class ServiceConfig(BaseModel):
    """Service configuration."""

    type: str = Field(default="ClusterIP", description="Service type")
    port: int = Field(default=80, description="Service port")


class IngressHost(BaseModel):
    """Ingress host configuration."""

    host: str = Field(description="Hostname")
    paths: list[dict[str, Any]] = Field(default_factory=list, description="Paths")


class IngressConfig(BaseModel):
    """Ingress configuration."""

    enabled: bool = Field(default=False, description="Enable ingress")
    className: str = Field(default="", description="Ingress class name")
    annotations: dict[str, str] = Field(default_factory=dict, description="Annotations")
    hosts: list[IngressHost] = Field(default_factory=list, description="Ingress hosts")
    tls: list[dict[str, Any]] = Field(default_factory=list, description="TLS configuration")


class AutoscalingConfig(BaseModel):
    """Autoscaling configuration."""

    enabled: bool = Field(default=False, description="Enable autoscaling")
    minReplicas: int = Field(default=1, description="Minimum replicas")
    maxReplicas: int = Field(default=10, description="Maximum replicas")
    targetCPUUtilizationPercentage: int = Field(default=80, description="Target CPU %")


class {{ class_name }}(BaseModel):
    """{{ title }} Helm chart values.

    TODO: Add description for your chart.
    """

    model_config = ConfigDict(extra="allow")

    replicaCount: int = Field(default=1, description="Number of replicas")
    image: ContainerImage = Field(
        default_factory=ContainerImage,
        description="Container image",
    )
    imagePullSecrets: list[dict[str, str]] = Field(
        default_factory=list, description="Image pull secrets"
    )
    nameOverride: str = Field(default="", description="Name override")
    fullnameOverride: str = Field(default="", description="Full name override")
    serviceAccount: ServiceAccount = Field(
        default_factory=ServiceAccount, description="ServiceAccount"
    )
    podAnnotations: dict[str, str] = Field(
        default_factory=dict, description="Pod annotations"
    )
    podLabels: dict[str, str] = Field(default_factory=dict, description="Pod labels")
    podSecurityContext: dict[str, Any] = Field(
        default_factory=dict, description="Pod security context"
    )
    securityContext: dict[str, Any] = Field(
        default_factory=dict, description="Container security context"
    )
    service: ServiceConfig = Field(default_factory=ServiceConfig, description="Service")
    ingress: IngressConfig = Field(default_factory=IngressConfig, description="Ingress")
    resources: dict[str, Any] = Field(
        default_factory=dict, description="Resource requests/limits"
    )
    livenessProbe: dict[str, Any] = Field(
        default_factory=dict, description="Liveness probe"
    )
    readinessProbe: dict[str, Any] = Field(
        default_factory=dict, description="Readiness probe"
    )
    autoscaling: AutoscalingConfig = Field(
        default_factory=AutoscalingConfig, description="Autoscaling"
    )
    nodeSelector: dict[str, str] = Field(default_factory=dict, description="Node selector")
    tolerations: list[dict[str, Any]] = Field(default_factory=list, description="Tolerations")
    affinity: dict[str, Any] = Field(default_factory=dict, description="Affinity")
