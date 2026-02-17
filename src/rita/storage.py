"""Storage backends for rendered manifests.

Supports both local filesystem and S3 storage for rendered Helm manifests.
S3 storage enables:
- Concurrent users to diff against shared baseline
- CI/CD pipelines to compare PRs against main branch baselines
- Centralized storage without committing rendered files to git
"""

from __future__ import annotations

import configparser
import json
import os
import subprocess
import tarfile
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import CompletedProcess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rita.config import RitaConfig, StorageConfig


@dataclass
class ManifestRef:
    """Reference to a stored manifest."""

    env: str
    """Environment name (e.g., 'dev', 'prod')."""

    app_name: str
    """Application name."""

    git_ref: str | None = None
    """Git reference (branch, tag, commit) - used for versioning."""

    @property
    def key(self) -> str:
        """Get the storage key for this manifest."""
        if self.git_ref:
            return f"{self.env}/{self.app_name}/{self.git_ref}/_all.yaml"
        return f"{self.env}/{self.app_name}/_all.yaml"


@dataclass
class ChartRef:
    """Reference to a cached chart in S3."""

    chart_name: str
    """Chart name (e.g., 'patient-app-stack')."""

    version: str
    """Chart version (e.g., '1.2.3')."""

    @property
    def key(self) -> str:
        """Get the storage key for this chart archive."""
        return f"_chart_cache/{self.chart_name}/{self.version}.tgz"


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def exists(self, ref: ManifestRef) -> bool:
        """Check if a manifest exists."""
        pass

    @abstractmethod
    def read(self, ref: ManifestRef) -> str | None:
        """Read a manifest. Returns None if not found."""
        pass

    @abstractmethod
    def write(self, ref: ManifestRef, content: str) -> None:
        """Write a manifest."""
        pass

    @abstractmethod
    def delete(self, ref: ManifestRef) -> None:
        """Delete a manifest."""
        pass

    @abstractmethod
    def list_manifests(self, env: str | None = None) -> list[ManifestRef]:
        """List all manifests, optionally filtered by environment."""
        pass


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage backend."""

    def __init__(self, base_path: Path):
        self.base_path: Path = base_path

    def _get_path(self, ref: ManifestRef) -> Path:
        return self.base_path / ref.key

    def exists(self, ref: ManifestRef) -> bool:
        return self._get_path(ref).exists()

    def read(self, ref: ManifestRef) -> str | None:
        path: Path = self._get_path(ref)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def write(self, ref: ManifestRef, content: str) -> None:
        path: Path = self._get_path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete(self, ref: ManifestRef) -> None:
        path: Path = self._get_path(ref)
        if path.exists():
            path.unlink()

    def list_manifests(self, env: str | None = None) -> list[ManifestRef]:
        refs: list[ManifestRef] = []
        search_path: Path = self.base_path / env if env else self.base_path

        if not search_path.exists():
            return refs

        for yaml_file in search_path.rglob("_all.yaml"):
            rel_path: Path = yaml_file.relative_to(self.base_path)
            parts: tuple[str, ...] = rel_path.parts

            if len(parts) >= 2:
                env_name: str = parts[0]
                app_name: str = parts[1]
                git_ref: str | None = parts[2] if len(parts) > 3 else None
                refs.append(
                    ManifestRef(env=env_name, app_name=app_name, git_ref=git_ref)
                )

        return refs


class S3StorageBackend(StorageBackend):
    """S3 storage backend for rendered manifests.

    Supports multiple authentication modes:
    1. AWS SSO Profile (for local development)
    2. Environment credentials (for CI/CD with OIDC)
    3. S3-compatible storage (Garage, MinIO, etc.) via custom endpoint
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "rendered-manifests",
        profile: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
    ):
        self.bucket: str = bucket
        self.prefix: str = prefix.rstrip("/")
        self.profile: str | None = profile
        self.region: str | None = region
        self.endpoint_url: str | None = endpoint_url
        self._client = None

    @property
    def client(self):
        """Lazy-load boto3 client."""
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ImportError(
                    "boto3 is required for S3 storage. "
                    "Install it with: pip install boto3"
                ) from exc

            session_kwargs = {}
            if self.profile:
                session_kwargs["profile_name"] = self.profile
            if self.region:
                session_kwargs["region_name"] = self.region

            session = boto3.Session(**session_kwargs)

            # Support custom S3-compatible endpoints (Garage, MinIO, etc.)
            client_kwargs = {}
            endpoint = self.endpoint_url or os.environ.get("AWS_ENDPOINT_URL")
            if endpoint:
                client_kwargs["endpoint_url"] = endpoint

            self._client = session.client("s3", **client_kwargs)

        return self._client

    def _get_key(self, ref: ManifestRef) -> str:
        return f"{self.prefix}/{ref.key}"

    def exists(self, ref: ManifestRef) -> bool:
        import botocore.exceptions

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._get_key(ref))
            return True
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def read(self, ref: ManifestRef) -> str | None:
        import botocore.exceptions

        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=self._get_key(ref)
            )
            return response["Body"].read().decode("utf-8")
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    def write(self, ref: ManifestRef, content: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._get_key(ref),
            Body=content.encode("utf-8"),
            ContentType="text/yaml",
        )

    def delete(self, ref: ManifestRef) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._get_key(ref))

    def list_manifests(self, env: str | None = None) -> list[ManifestRef]:
        refs: list[ManifestRef] = []
        prefix: str = f"{self.prefix}/{env}/" if env else f"{self.prefix}/"

        paginator = self.client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                if key.endswith("/_all.yaml"):
                    rel_key: str = key[len(self.prefix) + 1 :]
                    parts: list[str] = rel_key.split("/")

                    if len(parts) >= 3:
                        env_name: str = parts[0]
                        app_name: str = parts[1]
                        refs.append(
                            ManifestRef(
                                env=env_name,
                                app_name=app_name,
                                git_ref=parts[2] if len(parts) > 3 else None,
                            )
                        )

        return refs

    def get_presigned_url(self, ref: ManifestRef, expires_in: int = 3600) -> str:
        """Get a presigned URL for downloading a manifest."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._get_key(ref)},
            ExpiresIn=expires_in,
        )

    def upload_manifest(self, s3_key: str, content: str) -> None:
        """Upload a manifest to S3 using a raw key path.

        This is a lower-level method for pushing rendered manifests
        with custom key paths (e.g., branch-based paths).
        """
        self.client.put_object(
            Bucket=self.bucket,
            Key=f"{self.prefix}/{s3_key}",
            Body=content.encode("utf-8"),
            ContentType="text/yaml",
        )

    def download_manifest(self, s3_key: str) -> str | None:
        """Download a manifest from S3 using a raw key path.

        Returns None if not found.
        """
        import botocore.exceptions

        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=f"{self.prefix}/{s3_key}",
            )
            return response["Body"].read().decode("utf-8")
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    def list_manifest_keys(self, prefix: str) -> list[str]:
        """List all manifest keys under a given prefix.

        Returns the full S3 keys (without the storage prefix).
        """
        full_prefix = f"{self.prefix}/{prefix}"
        keys = []

        paginator = self.client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".yaml") or key.endswith(".yml"):
                    # Remove the storage prefix to return relative keys
                    rel_key = key[len(self.prefix) + 1 :]
                    keys.append(rel_key)

        return keys

    def _get_metadata_key(self, git_ref: str) -> str:
        """Get the S3 key for metadata file."""
        return f"{self.prefix}/_metadata/{git_ref}.json"

    def read_metadata(self, git_ref: str) -> dict[str, Any] | None:
        """Read metadata for a git ref (timestamp, commit, etc.)."""
        import botocore.exceptions

        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=self._get_metadata_key(git_ref),
            )
            return json.loads(response["Body"].read().decode("utf-8"))
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    def write_metadata(self, git_ref: str, metadata: dict[str, Any]) -> None:
        """Write metadata for a git ref."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._get_metadata_key(git_ref),
            Body=json.dumps(metadata, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

    def get_baseline_info(self, git_ref: str) -> dict[str, Any] | None:
        """Get information about the baseline for a git ref.

        Returns metadata including timestamp, commit SHA, and age.
        """
        metadata: dict[str, Any] | None = self.read_metadata(git_ref)
        if metadata is None:
            return None

        if "timestamp" in metadata:
            try:
                pushed_at: datetime = datetime.fromisoformat(metadata["timestamp"])
                age: timedelta = datetime.now(UTC) - pushed_at
                metadata["age_seconds"] = int(age.total_seconds())
                metadata["age_human"] = format_timedelta(age)
            except (ValueError, TypeError):
                pass

        return metadata

    def _get_chart_key(self, ref: ChartRef) -> str:
        """Get the S3 key for a chart archive."""
        return f"{self.prefix}/{ref.key}"

    def chart_exists(self, ref: ChartRef) -> bool:
        """Check if a chart is cached in S3."""
        import botocore.exceptions

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._get_chart_key(ref))
            return True
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def download_chart(self, ref: ChartRef, dest_path: Path) -> bool:
        """Download a cached chart from S3.

        Args:
            ref: Chart reference
            dest_path: Path to save the .tgz file

        Returns:
            True if successful, False if chart not found.
        """
        import botocore.exceptions

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(
                Bucket=self.bucket,
                Key=self._get_chart_key(ref),
                Filename=str(dest_path),
            )
            return True
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def upload_chart(self, ref: ChartRef, source_path: Path) -> None:
        """Upload a chart to S3 cache.

        Args:
            ref: Chart reference
            source_path: Path to the .tgz file to upload
        """
        self.client.upload_file(
            Filename=str(source_path),
            Bucket=self.bucket,
            Key=self._get_chart_key(ref),
            ExtraArgs={"ContentType": "application/gzip"},
        )

    def list_cached_charts(self) -> list[ChartRef]:
        """List all cached charts."""
        refs = []
        prefix = f"{self.prefix}/_chart_cache/"

        paginator = self.client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".tgz"):
                    rel_key = key[len(prefix) :]
                    parts = rel_key.rsplit("/", 1)

                    if len(parts) == 2:
                        chart_name = parts[0]
                        version = parts[1][:-4]
                        refs.append(ChartRef(chart_name=chart_name, version=version))

        return refs


def format_timedelta(delta) -> str:
    """Format a timedelta as a human-readable string."""
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds}s ago"
    elif total_seconds < 3600:
        minutes: int = total_seconds // 60
        return f"{minutes}m ago"
    elif total_seconds < 86400:
        hours: int = total_seconds // 3600
        return f"{hours}h ago"
    else:
        days: int = total_seconds // 86400
        return f"{days}d ago"


def get_current_git_commit() -> str | None:
    """Get the current git commit SHA."""
    try:
        result: CompletedProcess[str] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_current_git_ref() -> str | None:
    """Get the current git reference (branch name or commit SHA)."""
    try:
        result: CompletedProcess[str] = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        branch: str = result.stdout.strip()

        if branch == "HEAD":
            result: CompletedProcess[str] = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()

        return branch
    except subprocess.CalledProcessError:
        return None


def get_default_branch() -> str:
    """Get the default branch name (usually 'main' or 'master')."""
    try:
        result: CompletedProcess[str] = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )

        return result.stdout.strip().split("/")[-1]
    except subprocess.CalledProcessError:
        return "main"


def create_storage_backend(config: RitaConfig) -> StorageBackend:
    """Create a storage backend based on configuration.

    Priority:
    1. If S3 is configured, use S3
    2. Fall back to local storage
    """
    storage_config: StorageConfig | None = config.render.storage

    if storage_config and storage_config.type == "s3":
        bucket: str | None = os.environ.get("RITA_S3_BUCKET", storage_config.s3_bucket)
        prefix: str = os.environ.get(
            "RITA_S3_PREFIX", storage_config.s3_prefix or "rendered-manifests"
        )
        region: str | None = os.environ.get("AWS_REGION", storage_config.aws_region)

        profile = None
        if not os.environ.get("CI") and not os.environ.get("GITHUB_ACTIONS"):
            profile: str | None = storage_config.aws_profile

        if not bucket:
            raise ValueError(
                "S3 bucket not configured. Run 'rita config setup' or set RITA_S3_BUCKET environment variable."
            )

        # Get endpoint URL for S3-compatible storage
        endpoint_url: str | None = os.environ.get(
            "AWS_ENDPOINT_URL", storage_config.s3_endpoint
        )

        return S3StorageBackend(
            bucket=bucket,
            prefix=prefix,
            profile=profile,
            region=region,
            endpoint_url=endpoint_url,
        )

    from rita.repository import get_repo_root

    return LocalStorageBackend(get_repo_root() / config.render.output_path)


def check_aws_credentials(profile: str | None = None) -> tuple[bool, str]:
    """Check if AWS credentials are available and valid.

    Returns (success, message).
    """
    try:
        import boto3
        import botocore.exceptions
    except ImportError:
        return False, "boto3 is not installed. Run: pip install boto3"

    try:
        session_kwargs = {}
        if profile:
            session_kwargs["profile_name"] = profile

        session = boto3.Session(**session_kwargs)
        sts = session.client("sts")
        identity = sts.get_caller_identity()

        account = identity["Account"]
        arn = identity["Arn"]

        return True, f"Authenticated as {arn} (Account: {account})"
    except botocore.exceptions.NoCredentialsError:
        if profile:
            return (
                False,
                f"No credentials found for profile '{profile}'. Run: aws sso login --profile {profile}",
            )
        return (
            False,
            "No AWS credentials found. Configure credentials or specify a profile.",
        )
    except botocore.exceptions.ClientError as e:
        return False, f"AWS authentication failed: {e}"
    except Exception as e:
        return False, f"Error checking credentials: {e}"


def list_aws_profiles() -> list[str]:
    """List available AWS CLI profiles."""
    profiles = []

    config_path: Path = Path.home() / ".aws" / "config"
    if config_path.exists():
        config = configparser.ConfigParser()
        config.read(config_path)

        for section in config.sections():
            if section.startswith("profile "):
                profiles.append(section[8:])
            elif section == "default":
                profiles.append("default")

    creds_path: Path = Path.home() / ".aws" / "credentials"
    if creds_path.exists():
        creds = configparser.ConfigParser()
        creds.read(creds_path)

        for section in creds.sections():
            if section not in profiles:
                profiles.append(section)

    return sorted(set(profiles))


def get_chart_cache(config: RitaConfig) -> S3StorageBackend | None:
    """Get the S3 storage backend for chart caching.

    Returns None if S3 storage is not configured.
    """
    storage_config: StorageConfig | None = config.render.storage

    if not storage_config or storage_config.type != "s3":
        return None

    try:
        backend: StorageBackend = create_storage_backend(config)
        if isinstance(backend, S3StorageBackend):
            return backend
    except Exception:
        pass

    return None


class AWSTokenExpiredError(Exception):
    """Raised when AWS SSO token has expired."""

    def __init__(self, profile: str | None = None):
        self.profile: str | None = profile
        if profile:
            msg = f"AWS SSO token has expired. Run: aws sso login --profile {profile}"
        else:
            msg = "AWS SSO token has expired. Run: aws sso login"
        super().__init__(msg)


def _is_token_expired_error(error: Exception) -> bool:
    """Check if an error is due to expired AWS SSO token."""
    error_str: str = str(error).lower()
    error_type: str = type(error).__name__

    return (
        "token" in error_str
        and ("expired" in error_str or "refresh failed" in error_str)
    ) or error_type == "TokenRetrievalError"


def download_cached_chart(
    cache: S3StorageBackend,
    chart_name: str,
    version: str,
    dest_dir: Path,
) -> tuple[bool, str, Path | None]:
    """Try to download a chart from S3 cache.

    Args:
        cache: S3 storage backend
        chart_name: Name of the chart
        version: Chart version
        dest_dir: Directory to extract the chart to

    Returns:
        (success, message, chart_path) - chart_path is None if not found/error
    """
    ref = ChartRef(chart_name=chart_name, version=version)

    try:
        if not cache.chart_exists(ref):
            return False, "Chart not found in cache", None
    except Exception as e:
        if _is_token_expired_error(e):
            raise AWSTokenExpiredError(cache.profile) from e
        return False, f"Cache check failed: {e}", None

    tgz_path: Path = dest_dir / f"{chart_name}-{version}.tgz"

    try:
        success: bool = cache.download_chart(ref, tgz_path)
        if not success:
            return False, "Failed to download from cache", None

        with tarfile.open(tgz_path, "r:gz") as tar:
            tar.extractall(path=dest_dir)

        chart_dir: Path = dest_dir / chart_name
        if chart_dir.exists():
            return True, f"Chart loaded from S3 cache (v{version})", chart_dir

        subdirs = [d for d in dest_dir.iterdir() if d.is_dir()]
        if subdirs:
            return True, f"Chart loaded from S3 cache (v{version})", subdirs[0]

        return False, "Chart extracted but directory not found", None

    except Exception as e:
        if _is_token_expired_error(e):
            raise AWSTokenExpiredError(cache.profile) from e
        return False, f"Error loading from cache: {e}", None


def upload_chart_to_cache(
    cache: S3StorageBackend,
    chart_name: str,
    version: str,
    chart_dir: Path,
) -> bool:
    """Upload a chart directory to S3 cache.

    Creates a .tgz archive and uploads it.

    Args:
        cache: S3 storage backend
        chart_name: Name of the chart
        version: Chart version
        chart_dir: Path to the chart directory

    Returns:
        True if successful
    """
    ref = ChartRef(chart_name=chart_name, version=version)

    if cache.chart_exists(ref):
        return True

    try:
        with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as tmp:
            tgz_path = Path(tmp.name)

        with tarfile.open(tgz_path, "w:gz") as tar:
            tar.add(chart_dir, arcname=chart_name)

        cache.upload_chart(ref, tgz_path)

        tgz_path.unlink()

        return True

    except Exception:
        return False
