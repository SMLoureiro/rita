"""Common Kubernetes types used across Helm chart schemas.

These types model common Kubernetes primitives that are reused across
multiple chart value definitions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PullPolicy(StrEnum):
    """Container image pull policy.

    Defines when the kubelet should attempt to pull (download) the specified image.
    """

    ALWAYS = "Always"
    IF_NOT_PRESENT = "IfNotPresent"
    NEVER = "Never"


class ContainerImage(BaseModel):
    """Container image configuration.

    Defines the container image to use for a workload, including the repository,
    tag, pull policy, and optional digest for immutable deployments.
    """

    model_config = ConfigDict(extra="allow")

    repository: str = Field(
        description=(
            "Container image repository path. This is the full path to the image excluding the tag. "
            "Can be a Docker Hub image (e.g., 'nginx', 'redis:alpine'), a fully qualified ECR path "
            "(e.g., '616427543840.dkr.ecr.eu-central-1.amazonaws.com/k8s/multiagent'), or any other "
            "OCI-compliant registry. For ECR images, ensure the EKS nodes have appropriate IAM permissions."
        )
    )
    tag: str = Field(
        default="latest",
        description=(
            "Container image tag to pull. Tags identify specific versions of an image. "
            "Use semantic versions (e.g., 'v1.2.3') for production, 'latest' for development, "
            "or git commit SHAs for CI/CD traceability. Note: 'latest' is mutable and may cause "
            "unexpected changes between deployments."
        ),
    )
    pullPolicy: PullPolicy = Field(
        default=PullPolicy.IF_NOT_PRESENT,
        description=(
            "Image pull policy that determines when Kubernetes pulls the image. "
            "'Always' forces a pull on every pod start (required for mutable tags like 'latest'). "
            "'IfNotPresent' only pulls if the image isn't cached locally (good for immutable tags). "
            "'Never' assumes the image exists locally and never attempts to pull."
        ),
    )
    digest: str | None = Field(
        default=None,
        description=(
            "Container image digest for immutable, cryptographically-verified image references. "
            "When specified, this takes precedence over the tag field. Format: 'sha256:abc123...'. "
            "Using digests ensures the exact same image is deployed every time, preventing "
            "supply chain attacks and ensuring reproducibility. Recommended for production workloads."
        ),
    )


class ResourceRequirements(BaseModel):
    """Kubernetes resource requirements (requests/limits).

    Defines CPU and memory constraints for a container. Requests are guaranteed
    resources, while limits define the maximum a container can consume.
    """

    model_config = ConfigDict(extra="allow")

    cpu: str | None = Field(
        default=None,
        description=(
            "CPU resource quantity using Kubernetes resource notation. Examples: '100m' (100 millicores = 0.1 CPU), "
            "'500m' (half a CPU), '1' or '1000m' (one full CPU), '2.5' (2.5 CPUs). For requests, this is the "
            "minimum CPU guaranteed to the container. For limits, this is the maximum CPU the container can use "
            "before being throttled."
        ),
    )
    memory: str | None = Field(
        default=None,
        description=(
            "Memory resource quantity using Kubernetes resource notation. Examples: '128Mi' (128 mebibytes), "
            "'1Gi' (1 gibibyte), '512M' (512 megabytes). For requests, this is the minimum memory guaranteed. "
            "For limits, exceeding this causes the container to be OOMKilled. Always set memory limits to "
            "prevent runaway containers from affecting other workloads."
        ),
    )


class PodResources(BaseModel):
    """Pod resource requests and limits.

    Configures resource management for containers. Proper resource configuration
    ensures efficient cluster utilization and prevents resource starvation.
    """

    model_config = ConfigDict(extra="allow")

    requests: ResourceRequirements | None = Field(
        default=None,
        description=(
            "Resource requests define the minimum resources guaranteed to the container. The Kubernetes scheduler "
            "uses requests to find a node with sufficient capacity. Setting requests too low may cause performance "
            "issues; setting them too high wastes cluster resources. A good practice is to set requests based on "
            "observed average resource usage."
        ),
    )
    limits: ResourceRequirements | None = Field(
        default=None,
        description=(
            "Resource limits define the maximum resources a container can consume. CPU limits cause throttling "
            "when exceeded; memory limits cause OOMKill when exceeded. Limits prevent runaway containers from "
            "affecting other workloads. Best practice: set memory limits always, consider CPU limits based on "
            "application characteristics (some apps handle throttling poorly)."
        ),
    )


class ServiceAccount(BaseModel):
    """ServiceAccount configuration.

    ServiceAccounts provide an identity for pods running in the cluster and are
    used for authentication with the Kubernetes API and external services (via IRSA).
    """

    model_config = ConfigDict(extra="allow")

    create: bool = Field(
        default=True,
        description=(
            "Whether to create a new ServiceAccount for this release. Set to 'true' for new deployments. "
            "Set to 'false' if you want to use an existing ServiceAccount (specify its name in the 'name' field). "
            "Each application should typically have its own ServiceAccount for proper RBAC isolation."
        ),
    )
    name: str = Field(
        default="",
        description=(
            "The name of the ServiceAccount to use. If 'create' is true and this is empty, a name is generated "
            "using the fullname template. If 'create' is false, this must specify an existing ServiceAccount name. "
            "The name is used for RBAC bindings and IRSA (IAM Roles for Service Accounts) configurations."
        ),
    )
    automount: bool = Field(
        default=True,
        description=(
            "Whether to automatically mount the ServiceAccount's API credentials (token) into pods. "
            "Set to 'true' if the application needs to interact with the Kubernetes API. "
            "Set to 'false' for security-hardened deployments where API access is not needed, "
            "reducing the attack surface if a pod is compromised."
        ),
    )
    annotations: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Annotations to add to the ServiceAccount. Commonly used for AWS IRSA configuration: "
            "{'eks.amazonaws.com/role-arn': 'arn:aws:iam::123456789:role/my-role'}. "
            "IRSA allows pods to assume IAM roles without storing credentials, enabling secure "
            "access to AWS services like S3, Secrets Manager, and DynamoDB."
        ),
    )


class SecretRef(BaseModel):
    """Reference to a Kubernetes Secret.

    Used to reference secrets for environment variables, volumes, or other
    configurations that need sensitive data.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(
        description=(
            "Name of the Kubernetes Secret to reference. The secret must exist in the same namespace "
            "as the pod using it. Secrets are base64-encoded and can contain multiple key-value pairs."
        )
    )
    key: str | None = Field(
        default=None,
        description=(
            "Specific key within the Secret to use. If not specified, the entire Secret may be mounted "
            "or all keys may be used depending on context. For environment variables, this typically "
            "specifies which key's value to use."
        ),
    )


class EnvVar(BaseModel):
    """Environment variable configuration.

    Defines an environment variable to inject into containers. Supports both
    direct values and references to Secrets/ConfigMaps.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(
        description=(
            "Name of the environment variable. By convention, use UPPER_SNAKE_CASE (e.g., DATABASE_URL, "
            "API_KEY). The name must consist of alphanumeric characters, underscores, or hyphens, "
            "and must not start with a digit."
        )
    )
    value: str | None = Field(
        default=None,
        description=(
            "Direct value for the environment variable. Use this for non-sensitive configuration. "
            "For sensitive values (passwords, API keys), use 'valueFrom' with a Secret reference instead. "
            "Note: Values are visible in pod specs, so avoid secrets here."
        ),
    )
    valueFrom: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Reference to get the value from a Secret, ConfigMap, or field. Common patterns: "
            "{'secretKeyRef': {'name': 'my-secret', 'key': 'password'}} for secrets, "
            "{'configMapKeyRef': {'name': 'my-config', 'key': 'setting'}} for config maps, "
            "{'fieldRef': {'fieldPath': 'metadata.name'}} for pod metadata."
        ),
    )


class ExternalSecret(BaseModel):
    """ExternalSecret configuration for External Secrets Operator.

    Defines an external secret that syncs credentials from external secret
    managers (AWS Secrets Manager, HashiCorp Vault, etc.) into Kubernetes Secrets.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(
        description=(
            "Name of the ExternalSecret resource. This is also typically the name of the Kubernetes "
            "Secret that will be created. Must be unique within the namespace and follow Kubernetes "
            "naming conventions (lowercase, alphanumeric, hyphens)."
        )
    )
    refreshInterval: str = Field(
        default="10m",
        description=(
            "How often to sync the secret from the external provider. Format: Go duration string "
            "(e.g., '10m' for 10 minutes, '1h' for 1 hour, '30s' for 30 seconds). Shorter intervals "
            "mean faster secret rotation propagation but more API calls to the secret provider. "
            "Balance between security requirements and API rate limits."
        ),
    )


class ExternalSecretConfig(BaseModel):
    """Configuration for External Secrets integration.

    External Secrets Operator synchronizes secrets from external secret management
    systems (AWS Secrets Manager, HashiCorp Vault, Azure Key Vault, etc.) into
    Kubernetes Secrets, enabling secure, centralized secret management.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=False,
        description=(
            "Enable External Secrets integration. When enabled, the chart creates ExternalSecret "
            "resources that sync secrets from the configured external provider into Kubernetes Secrets. "
            "Requires the External Secrets Operator to be installed in the cluster."
        ),
    )
    refreshInterval: str = Field(
        default="10m",
        description=(
            "Default refresh interval for syncing secrets from the external provider. Applies to all "
            "ExternalSecrets unless overridden individually. Shorter intervals (e.g., '1m') are better "
            "for frequently rotated secrets; longer intervals (e.g., '1h') reduce API costs for stable secrets."
        ),
    )
    storeRef: dict[str, str] = Field(
        default_factory=lambda: {"name": "default", "kind": "ClusterSecretStore"},
        description=(
            "Reference to the SecretStore or ClusterSecretStore that provides access to the external "
            "secret provider. 'name' is the store name, 'kind' is either 'SecretStore' (namespace-scoped) "
            "or 'ClusterSecretStore' (cluster-wide). The default ClusterSecretStore is pre-configured "
            "for AWS Secrets Manager in our EKS clusters."
        ),
    )
    externalSecretNames: list[str] = Field(
        default_factory=list,
        description=(
            "List of secret names in the external provider to sync. For AWS Secrets Manager, these are "
            "the secret names (e.g., 'prod/patient-app/database-credentials'). Each name results in a "
            "Kubernetes Secret with the same name (sanitized for K8s naming). All key-value pairs in "
            "the external secret become keys in the Kubernetes Secret."
        ),
    )


class VolumeMount(BaseModel):
    """Volume mount configuration.

    Defines how a volume is mounted into a container's filesystem.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(
        description=(
            "Name of the volume to mount. Must match the name of a volume defined in the pod's 'volumes' "
            "list. This creates the connection between the volume definition and where it appears in "
            "the container's filesystem."
        )
    )
    mountPath: str = Field(
        description=(
            "Absolute path within the container where the volume will be mounted. Examples: '/data' for "
            "persistent data, '/config' for configuration files, '/secrets' for sensitive files. "
            "The container process must have appropriate permissions to read/write this path."
        )
    )
    readOnly: bool = Field(
        default=False,
        description=(
            "Mount the volume as read-only. Set to 'true' for configuration files and secrets that "
            "should not be modified by the container. This provides an additional security layer "
            "and prevents accidental modifications to shared data."
        ),
    )
    subPath: str | None = Field(
        default=None,
        description=(
            "Path within the volume to mount instead of the volume root. Useful when multiple containers "
            "need different parts of the same volume, or when mounting a single file from a ConfigMap. "
            "Example: 'config.yaml' to mount only that file from a ConfigMap."
        ),
    )


# Type aliases for common dict-based types
Labels = dict[str, str]
"""Kubernetes labels - key-value pairs for object metadata.

Labels are used for organizing and selecting Kubernetes objects. Common labels include:
- app.kubernetes.io/name: Application name
- app.kubernetes.io/instance: Instance identifier
- app.kubernetes.io/version: Application version
- app.kubernetes.io/component: Component within the application
- app.kubernetes.io/part-of: Higher-level application this is part of
"""

Annotations = dict[str, str]
"""Kubernetes annotations - key-value pairs for non-identifying metadata.

Annotations store arbitrary metadata that tools and libraries can use:
- Build/release information
- Contact/owner information
- Ingress controller configurations
- Prometheus scrape configurations
- AWS load balancer settings
"""

NodeSelector = dict[str, str]
"""Node selector - key-value pairs for node selection.

Simple node selection mechanism using node labels. Pods will only be scheduled
on nodes that have ALL the specified labels. Common uses:
- {'kubernetes.io/os': 'linux'} for Linux-only workloads
- {'node-type': 'compute'} for compute-optimized nodes
- {'topology.kubernetes.io/zone': 'eu-central-1a'} for zone affinity
"""

Tolerations = list[dict[str, Any]]
"""Pod tolerations - list of toleration specifications.

Tolerations allow pods to be scheduled on nodes with matching taints. Used for:
- Dedicated node pools (GPU nodes, high-memory nodes)
- Spot/preemptible instances
- Node maintenance windows
Example: [{'key': 'dedicated', 'operator': 'Equal', 'value': 'gpu', 'effect': 'NoSchedule'}]
"""

Affinity = dict[str, Any]
"""Pod affinity/anti-affinity rules.

Advanced scheduling constraints for pod placement:
- nodeAffinity: Select nodes based on labels (soft/hard constraints)
- podAffinity: Co-locate with other pods (e.g., same zone as database)
- podAntiAffinity: Spread pods apart (e.g., one per node for HA)
Used for high availability, performance optimization, and cost management.
"""
