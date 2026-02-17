"""Base types for standard Helm charts with common Kubernetes patterns.

This module provides reusable Pydantic models for common Helm chart configurations.
These types are inherited by specific chart value schemas to ensure consistency
and reduce duplication.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rita.charts.utils.kubernetes import ContainerImage, ServiceAccount


class ServiceConfig(BaseModel):
    """Kubernetes Service configuration.

    Defines how the application is exposed within the cluster. Services provide
    stable network endpoints for pods, enabling service discovery and load balancing.
    """

    model_config = ConfigDict(extra="allow")

    type: str = Field(
        default="ClusterIP",
        description=(
            "Kubernetes Service type that determines how the service is exposed. "
            "'ClusterIP' (default): Internal cluster IP only, accessible within the cluster. "
            "'NodePort': Exposes on each node's IP at a static port (30000-32767). "
            "'LoadBalancer': Provisions an external load balancer (AWS NLB/ALB in EKS). "
            "For most microservices, use 'ClusterIP' and expose via Ingress/Gateway."
        ),
    )
    port: int = Field(
        default=8000,
        description=(
            "The port the Service exposes. This is the port other services use to connect. "
            "By convention: 80/443 for HTTP/HTTPS frontends, 8000-9000 for backend APIs, "
            "5432 for PostgreSQL, 6379 for Redis. The targetPort (container port) is typically "
            "the same unless port remapping is needed."
        ),
    )


class IngressHostPath(BaseModel):
    """Ingress host path configuration.

    Defines URL path routing rules for an Ingress host. Multiple paths can route
    traffic to different backend services based on the URL path.
    """

    model_config = ConfigDict(extra="allow")

    path: str = Field(
        default="/",
        description=(
            "URL path to match for routing. Use '/' for the root path (catches all if using Prefix type). "
            "Examples: '/api' routes API calls, '/static' routes static assets. Path matching behavior "
            "depends on the pathType setting. Paths are matched in order of specificity."
        ),
    )
    pathType: str = Field(
        default="ImplementationSpecific",
        description=(
            "How the path should be matched. 'Prefix': Matches based on URL path prefix (e.g., '/api' matches '/api/users'). "
            "'Exact': Only matches the exact path. 'ImplementationSpecific': Interpretation depends on the IngressClass. "
            "For most use cases, 'Prefix' is recommended for flexibility."
        ),
    )


class IngressHost(BaseModel):
    """Ingress host configuration.

    Defines routing rules for a specific hostname. Each host can have multiple
    path rules routing to different backend services.
    """

    model_config = ConfigDict(extra="allow")

    host: str = Field(
        default="chart-example.local",
        description=(
            "Hostname for this Ingress rule (e.g., 'app.example.com'). "
            "Must be a valid DNS name. Leave empty for a default backend that handles "
            "requests without a Host header. For production, use real domain names "
            "registered with ExternalDNS for automatic DNS record creation."
        ),
    )
    paths: list[IngressHostPath] = Field(
        default_factory=lambda: [IngressHostPath()],
        description=(
            "List of path rules for this host. Each path routes to a backend service. "
            "Paths are evaluated in order; more specific paths should come first. "
            "At minimum, include a root path ('/') to catch all requests."
        ),
    )


class IngressConfig(BaseModel):
    """Ingress configuration.

    Ingress resources configure external HTTP/HTTPS access to services in the cluster.
    They provide load balancing, SSL termination, and name-based virtual hosting.
    Note: For Envoy Gateway deployments, prefer HTTPRoute over Ingress.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=False,
        description=(
            "Enable Ingress resource creation. Set to 'true' to expose the service externally via HTTP/HTTPS. "
            "When using the patient-app-stack umbrella chart with Envoy Gateway, this is typically 'false' "
            "as routing is handled by HTTPRoutes instead. Enable for standalone deployments or nginx-ingress."
        ),
    )
    className: str = Field(
        default="",
        description=(
            "IngressClass to use for this Ingress. Common values: 'nginx' for NGINX Ingress Controller, "
            "'alb' for AWS ALB Ingress Controller, empty string to use the cluster default. "
            "The IngressClass determines which controller processes this Ingress resource."
        ),
    )
    annotations: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Annotations for controller-specific configuration. Examples: "
            "{'kubernetes.io/ingress.class': 'nginx'} for legacy class specification, "
            "{'nginx.ingress.kubernetes.io/rewrite-target': '/'} for path rewriting, "
            "{'alb.ingress.kubernetes.io/scheme': 'internet-facing'} for AWS ALB settings, "
            "{'cert-manager.io/cluster-issuer': 'letsencrypt-prod'} for automatic TLS certificates."
        ),
    )
    hosts: list[IngressHost] = Field(
        default_factory=list,
        description=(
            "List of host rules for this Ingress. Each entry defines routing for a specific hostname. "
            "Multiple hosts allow serving different domains from the same Ingress. "
            "Example: [{'host': 'app.example.com', 'paths': [{'path': '/', 'pathType': 'Prefix'}]}]"
        ),
    )
    tls: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "TLS configuration for HTTPS. Each entry specifies hosts and the secret containing the TLS certificate. "
            "Example: [{'secretName': 'app-tls', 'hosts': ['app.example.com']}]. "
            "When using cert-manager, certificates are automatically provisioned based on Ingress annotations. "
            "TLS secrets must contain 'tls.crt' and 'tls.key' keys."
        ),
    )


class HttpProbe(BaseModel):
    """HTTP probe configuration.

    Defines an HTTP endpoint for health checking. Used by liveness, readiness,
    and startup probes to determine container health.
    """

    model_config = ConfigDict(extra="allow")

    path: str = Field(
        default="/alive",
        description=(
            "HTTP path to probe for health checks. Common patterns: '/alive' or '/healthz' for liveness, "
            "'/ready' for readiness, '/health' for combined checks. The endpoint should return 2xx/3xx "
            "for healthy, 4xx/5xx for unhealthy. Keep health check endpoints lightweight and fast."
        ),
    )
    port: str = Field(
        default="http",
        description=(
            "Port to probe, either as a number (e.g., '8000') or a named port (e.g., 'http'). "
            "Using named ports is preferred as they automatically adapt if the container port changes. "
            "The port must match a containerPort defined in the pod spec."
        ),
    )


class ProbeConfig(BaseModel):
    """Kubernetes probe configuration.

    Probes determine container health and readiness. Liveness probes restart unhealthy containers;
    readiness probes control traffic routing; startup probes delay other probes during initialization.
    """

    model_config = ConfigDict(extra="allow")

    httpGet: HttpProbe = Field(
        default_factory=HttpProbe,
        description=(
            "HTTP GET probe configuration. The kubelet sends an HTTP GET request to the specified "
            "path and port. A response code between 200-399 indicates success. This is the most "
            "common probe type for web applications and APIs."
        ),
    )


class AutoscalingConfig(BaseModel):
    """Horizontal Pod Autoscaler (HPA) configuration.

    Configures automatic scaling based on CPU/memory utilization or custom metrics.
    HPA adjusts the number of pod replicas to match demand, optimizing resource usage and costs.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=False,
        description=(
            "Enable Horizontal Pod Autoscaler for this deployment. When enabled, Kubernetes automatically "
            "adjusts the number of replicas based on observed metrics. Requires the metrics-server to be "
            "installed in the cluster. Disable for stateful workloads or when manual scaling is preferred."
        ),
    )
    minReplicas: int = Field(
        default=1,
        description=(
            "Minimum number of replicas to maintain. The HPA will never scale below this value, ensuring "
            "baseline availability. For production services, set to at least 2 for high availability. "
            "Consider your SLA requirements and cold-start times when setting this value."
        ),
    )
    maxReplicas: int = Field(
        default=100,
        description=(
            "Maximum number of replicas allowed. This caps scaling to prevent runaway costs and resource "
            "exhaustion. Set based on your cluster capacity, budget, and the service's maximum expected load. "
            "Include headroom for traffic spikes. Monitor and adjust based on actual scaling patterns."
        ),
    )
    targetCPUUtilizationPercentage: int = Field(
        default=80,
        description=(
            "Target average CPU utilization across all pods (as a percentage of requested CPU). "
            "When average utilization exceeds this, HPA scales up; when below, it scales down. "
            "80% is a common target balancing responsiveness with efficiency. CPU-bound workloads may need lower targets (60-70%)."
        ),
    )
    targetMemoryUtilizationPercentage: int | None = Field(
        default=None,
        description=(
            "Target average memory utilization across all pods (as a percentage of requested memory). "
            "Optional: leave null to scale only on CPU. Memory-based scaling is useful for memory-intensive "
            "workloads but be cautious as memory usage often doesn't decrease after load spikes. "
            "Consider using custom metrics for more precise control."
        ),
    )


class StoreRefConfig(BaseModel):
    """External secret store reference.

    References a SecretStore or ClusterSecretStore used by External Secrets Operator
    to access external secret management systems like AWS Secrets Manager.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(
        default="default",
        description=(
            "Name of the SecretStore or ClusterSecretStore to use. The 'default' store is typically "
            "pre-configured in each namespace for AWS Secrets Manager access. Custom stores can be "
            "created for different AWS accounts, regions, or secret providers."
        ),
    )
    kind: str = Field(
        default="ClusterSecretStore",
        description=(
            "Kind of the secret store resource. 'ClusterSecretStore': Cluster-wide, can be used by any namespace. "
            "'SecretStore': Namespace-scoped, only usable within its namespace. ClusterSecretStore is preferred "
            "for shared configurations; SecretStore for namespace-isolated secrets."
        ),
    )


class EnvFromExternalSecretsConfig(BaseModel):
    """External secrets configuration for environment variables.

    Configures the External Secrets Operator to sync secrets from AWS Secrets Manager
    (or other providers) into Kubernetes Secrets, which are then injected as environment
    variables into the application pods.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=True,
        description=(
            "Enable External Secrets integration for this component. When enabled, ExternalSecret resources "
            "are created to sync secrets from the external provider (AWS Secrets Manager) into Kubernetes Secrets. "
            "The synced secrets are automatically mounted as environment variables in the pod."
        ),
    )
    refreshInterval: str = Field(
        default="10m",
        description=(
            "How often to refresh secrets from the external provider. Format: Go duration (e.g., '10m', '1h', '30s'). "
            "Shorter intervals propagate secret rotations faster but increase API calls. For most applications, "
            "'10m' balances security with API efficiency. Critical security secrets may warrant '1m' intervals."
        ),
    )
    storeRef: StoreRefConfig = Field(
        default_factory=StoreRefConfig,
        description=(
            "Reference to the SecretStore or ClusterSecretStore that provides access to the external secret provider. "
            "The default configuration uses the cluster-wide 'default' ClusterSecretStore which is pre-configured "
            "for AWS Secrets Manager access in our EKS clusters."
        ),
    )
    externalSecretNames: list[str] = Field(
        default_factory=list,
        description=(
            "List of secret names in AWS Secrets Manager to sync. Each secret becomes a Kubernetes Secret "
            "with all its key-value pairs available as environment variables. Common secrets: "
            "'general-application-config' (shared config), 'database-credentials' (DB access), "
            "'api-keys' (external service credentials). Secrets must exist in the same AWS region as the cluster."
        ),
    )


class BaseChartValues(BaseModel):
    """Base Helm chart values with standard Kubernetes patterns.

    This base class provides common fields used in most Helm charts for deploying
    containerized applications. It includes container configuration, service exposure,
    resource management, health checking, and pod scheduling options.
    """

    model_config = ConfigDict(extra="allow")

    replicaCount: int = Field(
        default=1,
        description=(
            "Number of pod replicas to deploy. For high availability in production, use at least 2 replicas "
            "with pod anti-affinity to spread across nodes. For development/staging, 1 replica is often sufficient. "
            "This value is overridden when autoscaling is enabled."
        ),
    )
    image: ContainerImage = Field(
        default_factory=ContainerImage,
        description=(
            "Container image configuration including repository, tag, and pull policy. "
            "Specifies which Docker/OCI image to deploy and how to retrieve it from the registry."
        ),
    )
    imagePullSecrets: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "References to Kubernetes Secrets containing Docker registry credentials. Required for private registries. "
            "Format: [{'name': 'my-registry-secret'}]. For ECR with IRSA, this is typically not needed as nodes "
            "authenticate via IAM. Only needed for external private registries like Docker Hub private repos."
        ),
    )
    nameOverride: str = Field(
        default="",
        description=(
            "Override the chart name used in resource names. By default, resource names are generated from "
            "the chart name. Use this to customize names while keeping the release name prefix. "
            "Example: Setting 'myapp' results in names like 'release-myapp' instead of 'release-chartname'."
        ),
    )
    fullnameOverride: str = Field(
        default="",
        description=(
            "Completely override the generated resource names. When set, this value is used directly for all "
            "resource names, ignoring both the chart name and release name. Use with caution as it may cause "
            "naming conflicts if deploying multiple releases. Useful for migration scenarios."
        ),
    )
    serviceAccount: ServiceAccount = Field(
        default_factory=ServiceAccount,
        description=(
            "Kubernetes ServiceAccount configuration. ServiceAccounts provide pod identity for RBAC and "
            "IRSA (IAM Roles for Service Accounts). Each application should have its own ServiceAccount "
            "for proper security isolation and AWS credential management."
        ),
    )
    podAnnotations: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Annotations to add to pod metadata. Common uses: Prometheus scraping configuration "
            "({'prometheus.io/scrape': 'true', 'prometheus.io/port': '8000'}), Istio sidecar injection control, "
            "Vault agent injection, and Datadog APM configuration. Annotations are inherited by all pods in the deployment."
        ),
    )
    podLabels: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Additional labels to add to pod metadata. Labels are used for selection and organization. "
            "The chart automatically adds standard labels (app, version, etc.). Add custom labels for "
            "additional categorization (team, cost-center, tier) or for use with PodDisruptionBudgets and NetworkPolicies."
        ),
    )
    podSecurityContext: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Pod-level security settings applied to all containers in the pod. Common settings: "
            "{'runAsNonRoot': true, 'runAsUser': 1000, 'fsGroup': 1000}. These enforce security best practices "
            "like running as non-root and setting filesystem permissions. Required for PSP/PSA compliance."
        ),
    )
    securityContext: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Container-level security settings. Common settings: "
            "{'allowPrivilegeEscalation': false, 'readOnlyRootFilesystem': true, 'capabilities': {'drop': ['ALL']}}. "
            "These harden individual containers beyond pod-level settings. Best practice: drop all capabilities "
            "and only add what's needed."
        ),
    )
    service: ServiceConfig = Field(
        default_factory=ServiceConfig,
        description=(
            "Kubernetes Service configuration for exposing the application. Services provide stable network "
            "endpoints for pod access within the cluster and, depending on type, external access."
        ),
    )
    ingress: IngressConfig = Field(
        default_factory=IngressConfig,
        description=(
            "Ingress configuration for external HTTP/HTTPS access. Configure this to expose the service "
            "outside the cluster via a hostname. For Envoy Gateway deployments, HTTPRoutes are preferred over Ingress."
        ),
    )
    resources: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "CPU and memory resource requests and limits. Format: {'requests': {'cpu': '100m', 'memory': '128Mi'}, "
            "'limits': {'cpu': '1', 'memory': '512Mi'}}. Requests are guaranteed; limits cap usage. "
            "Always set for production to ensure QoS and prevent resource starvation. "
            "Size based on actual application requirements and load testing results."
        ),
    )
    livenessProbe: ProbeConfig = Field(
        default_factory=ProbeConfig,
        description=(
            "Liveness probe configuration. Kubernetes uses this to detect and restart unhealthy containers. "
            "If the probe fails consecutively (failureThreshold times), the container is killed and restarted. "
            "Use a lightweight endpoint that verifies the application process is alive and responsive."
        ),
    )
    readinessProbe: ProbeConfig = Field(
        default_factory=ProbeConfig,
        description=(
            "Readiness probe configuration. Kubernetes uses this to determine when a pod is ready to receive traffic. "
            "Pods failing readiness are removed from Service endpoints. Use an endpoint that verifies all dependencies "
            "(database connections, cache, external services) are available. More thorough than liveness."
        ),
    )
    autoscaling: AutoscalingConfig = Field(
        default_factory=AutoscalingConfig,
        description=(
            "Horizontal Pod Autoscaler configuration for automatic scaling based on metrics. "
            "When enabled, replicaCount becomes the initial replica count and HPA manages scaling within min/max bounds."
        ),
    )
    volumes: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Additional volumes to attach to pods. Volumes provide storage that persists beyond container restarts. "
            "Common types: 'configMap' for configuration, 'secret' for credentials, 'emptyDir' for scratch space, "
            "'persistentVolumeClaim' for persistent data. Example: [{'name': 'config', 'configMap': {'name': 'app-config'}}]"
        ),
    )
    volumeMounts: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Volume mounts to add to the main container. Each mount connects a volume to a path in the container. "
            "Example: [{'name': 'config', 'mountPath': '/etc/app', 'readOnly': true}]. "
            "Ensure mount paths don't conflict with paths the container image expects to write to."
        ),
    )
    nodeSelector: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Node labels for pod scheduling. Pods are only scheduled on nodes matching ALL specified labels. "
            "Common uses: {'node-type': 'compute'} for compute nodes, {'kubernetes.io/arch': 'amd64'} for architecture. "
            "For more complex scheduling, use affinity rules instead."
        ),
    )
    tolerations: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Pod tolerations allow scheduling on nodes with matching taints. Required for dedicated node pools. "
            "Example: [{'key': 'dedicated', 'operator': 'Equal', 'value': 'compute', 'effect': 'NoSchedule'}]. "
            "Use with nodeSelector or affinity to target specific tainted nodes."
        ),
    )
    affinity: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Advanced pod scheduling rules for node and pod affinity/anti-affinity. "
            "Use nodeAffinity for complex node selection (replaces nodeSelector for advanced cases). "
            "Use podAntiAffinity to spread replicas across nodes/zones for high availability. "
            "Use podAffinity to co-locate related pods for performance (e.g., app with its cache)."
        ),
    )
    extraObjects: list[Any] = Field(
        default_factory=list,
        description=(
            "Extra Kubernetes manifests to deploy alongside the chart resources. Use for custom resources, "
            "additional ConfigMaps, Secrets, or any Kubernetes object not covered by chart parameters. "
            "Objects are templated with the chart's values context. Format: YAML strings or parsed objects."
        ),
    )
