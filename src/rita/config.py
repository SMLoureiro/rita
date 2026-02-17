"""Configuration management for rita.

This module handles loading and managing configuration from a YAML file,
with support for auto-discovery of ArgoCD applications.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    import boto3
    from botocore.exceptions import ClientError

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[misc,assignment]

CONFIG_FILE_NAME = ".rita.yaml"


@dataclass
class EnvironmentConfig:
    """Configuration for a single environment."""

    name: str
    """Name of the environment (e.g., 'dev', 'prod')."""

    paths: list[str] = field(default_factory=list)
    """Paths to search for ArgoCD applications (relative to repo root)."""

    aliases: list[str] = field(default_factory=list)
    """Aliases for this environment (e.g., ['development'] for 'dev')."""

    include_patterns: list[str] = field(
        default_factory=lambda: ["**/*.yaml", "**/*.yml"]
    )
    """Glob patterns to include when searching for applications."""

    exclude_patterns: list[str] = field(
        default_factory=lambda: ["**/secrets/**", "**/kustomization.yaml"]
    )
    """Glob patterns to exclude when searching for applications."""


@dataclass
class ChartConfig:
    """Configuration for charts."""

    path: str = "charts"
    """Path to the charts directory (relative to repo root)."""

    registry: str = "ghcr.io/SMLoureiro"
    """Default OCI registry for charts."""


@dataclass
class StorageConfig:
    """Configuration for manifest storage backend."""

    type: str = "local"
    """Storage type: 'local' or 's3'."""

    s3_bucket: str | None = None
    """S3 bucket name for storing rendered manifests."""

    s3_prefix: str = "rendered-manifests"
    """S3 key prefix for manifests."""

    aws_profile: str | None = None
    """AWS SSO profile name for local development."""

    aws_region: str | None = None
    """AWS region for S3 bucket."""

    s3_endpoint: str | None = None
    """Custom S3 endpoint URL for S3-compatible storage (Garage, MinIO, etc.)."""


@dataclass
class RenderConfig:
    """Configuration for manifest rendering."""

    output_path: str = "rendered"
    """Path to output rendered manifests (for local storage)."""

    local_charts_only: bool = True
    """Only render applications using local charts by default."""

    storage: StorageConfig | None = None
    """Storage backend configuration."""

    compare_branch: str = "main"
    """Default branch to compare against when diffing."""


@dataclass
class RegistryConfig:
    """Configuration for an OCI registry authentication."""

    url: str
    """Registry URL (e.g., 'docker.io', 'ghcr.io')."""

    username: str | None = None
    """Username for registry auth. Can be env var reference like '$DOCKER_USERNAME'."""

    password: str | None = None
    """Password/token for registry auth. Can be env var reference like '$DOCKER_PASSWORD'."""

    aws_secret_name: str | None = None
    """AWS Secrets Manager secret name containing credentials (JSON with 'username' and 'password' keys)."""


@dataclass
class ChartTestConfig:
    """Configuration for ephemeral cluster testing."""

    kind_cluster_name: str = "rita-test"
    """Name of the kind cluster to create for testing."""

    timeout_seconds: int = 300
    """Timeout for deployments in seconds."""

    cleanup_on_success: bool = True
    """Whether to delete the cluster after successful tests."""

    cleanup_on_failure: bool = False
    """Whether to delete the cluster after failed tests (for debugging)."""

    pre_install_manifests: list[str] = field(default_factory=list)
    """Manifests to install before testing (e.g., CRDs)."""


@dataclass
class RitaConfig:
    """Main configuration for rita."""

    environments: list[EnvironmentConfig] = field(default_factory=list)
    """List of environments to manage."""

    charts: ChartConfig = field(default_factory=ChartConfig)
    """Chart configuration."""

    render: RenderConfig = field(default_factory=RenderConfig)
    """Render configuration."""

    test: ChartTestConfig = field(default_factory=ChartTestConfig)
    """Test configuration."""

    registries: list[RegistryConfig] = field(default_factory=list)
    """OCI registry authentication configs. Credentials can use env var refs like '$VAR'."""

    auto_discover: bool = True
    """Whether to auto-discover ArgoCD applications in configured paths."""

    @classmethod
    def get_default(cls) -> RitaConfig:
        """Get default configuration with standard paths."""
        return cls(
            environments=[
                EnvironmentConfig(
                    name="dev",
                    paths=["kubernetes/argocd/applications/dev/templates"],
                ),
                EnvironmentConfig(
                    name="prod",
                    paths=["kubernetes/argocd/applications/prod/templates"],
                ),
            ],
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RitaConfig:
        """Create config from a dictionary."""
        environments = []
        for env_data in data.get("environments", []):
            environments.append(
                EnvironmentConfig(
                    name=env_data.get("name", "default"),
                    paths=env_data.get("paths", []),
                    aliases=env_data.get("aliases", []),
                    include_patterns=env_data.get(
                        "include_patterns", ["**/*.yaml", "**/*.yml"]
                    ),
                    exclude_patterns=env_data.get(
                        "exclude_patterns", ["**/secrets/**"]
                    ),
                )
            )

        charts_data = data.get("charts", {})
        charts = ChartConfig(
            path=charts_data.get("path", "charts"),
            registry=charts_data.get("registry", "ghcr.io/SMLoureiro"),
        )

        render_data = data.get("render", {})
        storage_data = render_data.get("storage", {})
        storage = None
        if storage_data:
            storage = StorageConfig(
                type=storage_data.get("type", "local"),
                s3_bucket=storage_data.get("s3_bucket"),
                s3_prefix=storage_data.get("s3_prefix", "rendered-manifests"),
                aws_profile=storage_data.get("aws_profile"),
                aws_region=storage_data.get("aws_region"),
                s3_endpoint=storage_data.get("s3_endpoint"),
            )

        render = RenderConfig(
            output_path=render_data.get("output_path", "rendered"),
            local_charts_only=render_data.get("local_charts_only", True),
            storage=storage,
            compare_branch=render_data.get("compare_branch", "main"),
        )

        test_data = data.get("test", {})
        test = ChartTestConfig(
            kind_cluster_name=test_data.get("kind_cluster_name", "rita-test"),
            timeout_seconds=test_data.get("timeout_seconds", 300),
            cleanup_on_success=test_data.get("cleanup_on_success", True),
            cleanup_on_failure=test_data.get("cleanup_on_failure", False),
            pre_install_manifests=test_data.get("pre_install_manifests", []),
        )

        registries = []
        for reg_data in data.get("registries", []):
            registries.append(
                RegistryConfig(
                    url=reg_data.get("url", ""),
                    username=reg_data.get("username"),
                    password=reg_data.get("password"),
                    aws_secret_name=reg_data.get("aws_secret_name"),
                )
            )

        return cls(
            environments=environments,
            charts=charts,
            render=render,
            test=test,
            registries=registries,
            auto_discover=data.get("auto_discover", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert config to a dictionary."""
        render_dict: dict[str, Any] = {
            "output_path": self.render.output_path,
            "local_charts_only": self.render.local_charts_only,
            "compare_branch": self.render.compare_branch,
        }

        if self.render.storage:
            storage_dict: dict[str, Any] = {
                "type": self.render.storage.type,
            }
            if self.render.storage.s3_bucket:
                storage_dict["s3_bucket"] = self.render.storage.s3_bucket
            # Always include s3_prefix when s3 storage is configured
            if self.render.storage.type == "s3":
                storage_dict["s3_prefix"] = self.render.storage.s3_prefix
            if self.render.storage.aws_profile:
                storage_dict["aws_profile"] = self.render.storage.aws_profile
            if self.render.storage.aws_region:
                storage_dict["aws_region"] = self.render.storage.aws_region
            if self.render.storage.s3_endpoint:
                storage_dict["s3_endpoint"] = self.render.storage.s3_endpoint
            render_dict["storage"] = storage_dict

        return {
            "auto_discover": self.auto_discover,
            "environments": [
                {
                    "name": env.name,
                    "paths": env.paths,
                    "aliases": env.aliases,
                    "include_patterns": env.include_patterns,
                    "exclude_patterns": env.exclude_patterns,
                }
                for env in self.environments
            ],
            "charts": {
                "path": self.charts.path,
                "registry": self.charts.registry,
            },
            "render": render_dict,
            "test": {
                "kind_cluster_name": self.test.kind_cluster_name,
                "timeout_seconds": self.test.timeout_seconds,
                "cleanup_on_success": self.test.cleanup_on_success,
                "cleanup_on_failure": self.test.cleanup_on_failure,
                "pre_install_manifests": self.test.pre_install_manifests,
            },
            "registries": [
                {
                    k: v
                    for k, v in {
                        "url": reg.url,
                        "username": reg.username,
                        "password": reg.password,
                        "aws_secret_name": reg.aws_secret_name,
                    }.items()
                    if v is not None
                }
                for reg in self.registries
            ]
            if self.registries
            else [],
        }


def find_config_file(start_path: Path | None = None) -> Path | None:
    """Find the config file by walking up the directory tree.

    Starts from start_path (or cwd) and walks up looking for .rita.yaml.
    """
    if start_path is None:
        start_path: Path = Path.cwd()

    current: Path = start_path
    while current != current.parent:
        config_path: Path = current / CONFIG_FILE_NAME
        if config_path.exists():
            return config_path
        current: Path = current.parent

    return None


def load_config(config_path: Path | None = None) -> RitaConfig:
    """Load configuration from file or return defaults.

    If config_path is None, searches for .rita.yaml in the directory tree.
    If no config file is found, returns default configuration.
    """
    if config_path is None:
        config_path: Path | None = find_config_file()

    if config_path is None or not config_path.exists():
        return RitaConfig.get_default()

    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return RitaConfig.from_dict(data)


def save_config(config: RitaConfig, config_path: Path) -> None:
    """Save configuration to a file."""
    with config_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config.to_dict(), f, default_flow_style=False, sort_keys=False)


def generate_default_config() -> str:
    """Generate default configuration as YAML string."""
    config: RitaConfig = RitaConfig.get_default()
    return yaml.safe_dump(config.to_dict(), default_flow_style=False, sort_keys=False)


def resolve_environment(config: RitaConfig, env_name: str) -> EnvironmentConfig | None:
    """Resolve an environment name or alias to its configuration.

    Matches against both the environment name and any configured aliases.
    Returns None if no match is found.
    """
    env_name_lower: str = env_name.lower()

    for env in config.environments:
        if env.name.lower() == env_name_lower:
            return env

        for alias in env.aliases:
            if alias.lower() == env_name_lower:
                return env

    return None


def get_canonical_env_name(config: RitaConfig, env_name: str) -> str:
    """Get the canonical environment name for an alias.

    If the name is an alias, returns the main environment name.
    Otherwise returns the input name unchanged.
    """
    env: EnvironmentConfig | None = resolve_environment(config, env_name)
    if env:
        return env.name
    return env_name


def resolve_env_var(value: str | None) -> str | None:
    """Resolve environment variable references in a string.

    Supports:
    - $VAR_NAME -> os.environ.get("VAR_NAME")
    - ${VAR_NAME} -> os.environ.get("VAR_NAME")
    - Plain values returned as-is

    Returns None if the value is None or if the env var is not set.
    """
    if value is None:
        return None

    if value.startswith("$"):
        var_name: str = value[1:]
        if var_name.startswith("{") and var_name.endswith("}"):
            var_name: str = var_name[1:-1]
        return os.environ.get(var_name)

    return value


def fetch_secret_from_aws(
    secret_name: str, region: str | None = None, profile: str | None = None
) -> dict[str, str] | None:
    """Fetch a secret from AWS Secrets Manager.

    Returns the secret as a dictionary, or None if fetch fails.
    NEVER logs the secret values.
    """
    if not HAS_BOTO3:
        return None

    try:
        session_kwargs: dict[str, str] = {}
        if (
            profile
            and not os.environ.get("CI")
            and not os.environ.get("GITHUB_ACTIONS")
        ):
            session_kwargs["profile_name"] = profile
        if region:
            session_kwargs["region_name"] = region

        session = boto3.Session(**session_kwargs)
        client = session.client("secretsmanager")

        response = client.get_secret_value(SecretId=secret_name)
        secret_string = response.get("SecretString")
        if secret_string:
            return json.loads(secret_string)
    except (ClientError, json.JSONDecodeError, Exception):
        pass

    return None


def get_registry_credentials(
    config: RitaConfig, registry_url: str
) -> tuple[str | None, str | None]:
    """Get credentials for a registry from config.

    Supports:
    1. AWS Secrets Manager (aws_secret_name) - fetches from Secrets Manager
    2. Environment variables ($VAR_NAME)
    3. Direct values (not recommended for passwords)

    Returns (username, password) with credentials resolved.
    Returns (None, None) if no matching registry is configured.
    NEVER logs credential values.
    """
    for reg in config.registries:
        config_url: str = reg.url.lower().replace("https://", "").replace("http://", "")
        target_url: str = (
            registry_url.lower().replace("https://", "").replace("http://", "")
        )
        docker_domains = ["docker.io", "registry-1.docker.io", "index.docker.io"]
        config_is_docker: bool = any(d in config_url for d in docker_domains)
        target_is_docker: bool = any(d in target_url for d in docker_domains)

        if (
            (config_is_docker and target_is_docker)
            or config_url in target_url
            or target_url in config_url
        ):
            if reg.aws_secret_name:
                region = None
                profile = None
                if config.render.storage:
                    region: str | None = config.render.storage.aws_region
                    profile: str | None = config.render.storage.aws_profile

                secret: dict[str, str] | None = fetch_secret_from_aws(
                    reg.aws_secret_name, region, profile
                )
                if secret:
                    username: str | None = secret.get("username")
                    password: str | None = secret.get("password") or secret.get(
                        "accessToken"
                    )
                    return username, password

            username: str | None = resolve_env_var(reg.username)
            password: str | None = resolve_env_var(reg.password)
            return username, password

    return None, None
