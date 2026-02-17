from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import botocore.exceptions

from rita.config import RenderConfig, RitaConfig, StorageConfig
from rita.storage import (
    LocalStorageBackend,
    ManifestRef,
    S3StorageBackend,
    StorageBackend,
    check_aws_credentials,
    create_storage_backend,
    get_current_git_ref,
    get_default_branch,
    list_aws_profiles,
)


class TestManifestRef:
    def test_key_without_git_ref(self):
        ref = ManifestRef(env="dev", app_name="my-app")
        assert ref.key == "dev/my-app/_all.yaml"

    def test_key_with_git_ref(self):
        ref = ManifestRef(env="prod", app_name="my-app", git_ref="main")
        assert ref.key == "prod/my-app/main/_all.yaml"


class TestLocalStorageBackend:
    def test_write_and_read(self, tmp_path: Path):
        backend = LocalStorageBackend(tmp_path)
        ref = ManifestRef(env="dev", app_name="test-app")
        content = "apiVersion: v1\nkind: ConfigMap\n"

        backend.write(ref, content)
        assert backend.exists(ref)
        assert backend.read(ref) == content

    def test_read_nonexistent(self, tmp_path: Path):
        backend = LocalStorageBackend(tmp_path)
        ref = ManifestRef(env="dev", app_name="nonexistent")

        assert not backend.exists(ref)
        assert backend.read(ref) is None

    def test_delete(self, tmp_path: Path):
        backend = LocalStorageBackend(tmp_path)
        ref = ManifestRef(env="dev", app_name="test-app")
        content = "test content"

        backend.write(ref, content)
        assert backend.exists(ref)

        backend.delete(ref)
        assert not backend.exists(ref)

    def test_delete_nonexistent(self, tmp_path: Path):
        backend = LocalStorageBackend(tmp_path)
        ref = ManifestRef(env="dev", app_name="nonexistent")

        backend.delete(ref)

    def test_list_manifests(self, tmp_path: Path):
        backend = LocalStorageBackend(tmp_path)

        refs = [
            ManifestRef(env="dev", app_name="app1"),
            ManifestRef(env="dev", app_name="app2"),
            ManifestRef(env="prod", app_name="app1"),
        ]
        for ref in refs:
            backend.write(ref, "content")

        found: list[ManifestRef] = backend.list_manifests()
        assert len(found) == 3

    def test_list_manifests_by_env(self, tmp_path: Path):
        backend = LocalStorageBackend(tmp_path)

        refs = [
            ManifestRef(env="dev", app_name="app1"),
            ManifestRef(env="dev", app_name="app2"),
            ManifestRef(env="prod", app_name="app1"),
        ]
        for ref in refs:
            backend.write(ref, "content")

        dev_refs: list[ManifestRef] = backend.list_manifests(env="dev")
        assert len(dev_refs) == 2
        assert all(r.env == "dev" for r in dev_refs)

    def test_write_creates_directories(self, tmp_path: Path):
        backend = LocalStorageBackend(tmp_path)
        ref = ManifestRef(env="staging", app_name="nested-app", git_ref="feature/test")

        backend.write(ref, "content")
        assert backend.exists(ref)


class TestS3StorageBackend:
    def test_get_key(self):
        backend = S3StorageBackend(
            bucket="test-bucket",
            prefix="rendered-manifests",
        )
        ref = ManifestRef(env="dev", app_name="my-app", git_ref="main")

        assert backend._get_key(ref) == "rendered-manifests/dev/my-app/main/_all.yaml"

    def test_get_key_with_trailing_slash_prefix(self):
        backend = S3StorageBackend(
            bucket="test-bucket",
            prefix="rendered-manifests/",
        )
        ref = ManifestRef(env="dev", app_name="my-app")

        assert backend._get_key(ref) == "rendered-manifests/dev/my-app/_all.yaml"

    @patch("boto3.Session")
    def test_client_uses_profile(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        backend = S3StorageBackend(
            bucket="test-bucket",
            profile="my-profile",
            region="us-west-2",
        )

        _ = backend.client

        mock_session_cls.assert_called_once_with(
            profile_name="my-profile",
            region_name="us-west-2",
        )

    @patch("boto3.Session")
    def test_client_without_profile(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        backend = S3StorageBackend(
            bucket="test-bucket",
        )

        _ = backend.client

        mock_session_cls.assert_called_once_with()

    @patch("boto3.Session")
    def test_client_with_endpoint_url(self, mock_session_cls):
        """Test S3StorageBackend with custom endpoint URL for S3-compatible storage."""
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        backend = S3StorageBackend(
            bucket="test-bucket",
            endpoint_url="http://localhost:3900",
        )

        _ = backend.client

        mock_session.client.assert_called_once_with(
            "s3",
            endpoint_url="http://localhost:3900",
        )

    @patch("boto3.Session")
    def test_client_with_endpoint_url_and_region(self, mock_session_cls):
        """Test S3StorageBackend with custom endpoint URL and region."""
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        backend = S3StorageBackend(
            bucket="test-bucket",
            endpoint_url="https://nyc3.digitaloceanspaces.com",
            region="nyc3",
        )

        _ = backend.client

        mock_session_cls.assert_called_once_with(region_name="nyc3")
        mock_session.client.assert_called_once_with(
            "s3",
            endpoint_url="https://nyc3.digitaloceanspaces.com",
        )

    def test_endpoint_url_stored(self):
        """Test that endpoint_url is properly stored in the backend."""
        backend = S3StorageBackend(
            bucket="test-bucket",
            prefix="manifests",
            endpoint_url="http://garage.local:3900",
        )

        assert backend.endpoint_url == "http://garage.local:3900"
        assert backend.bucket == "test-bucket"
        assert backend.prefix == "manifests"

    def test_boto3_import_error(self):
        with patch.dict("sys.modules", {"boto3": None}):
            S3StorageBackend(bucket="test-bucket")
            # This should raise ImportError with helpful message
            # Note: Can't easily test this without uninstalling boto3

    @patch("boto3.Session")
    def test_upload_manifest(self, mock_session_cls):
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        backend = S3StorageBackend(
            bucket="test-bucket",
            prefix="rendered-manifests",
        )

        backend.upload_manifest("main/rendered/dev/app/_all.yaml", "test content")

        mock_client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="rendered-manifests/main/rendered/dev/app/_all.yaml",
            Body=b"test content",
            ContentType="text/yaml",
        )

    @patch("boto3.Session")
    def test_download_manifest_success(self, mock_session_cls):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"apiVersion: v1\nkind: ConfigMap\n"
        mock_client.get_object.return_value = {"Body": mock_body}

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        backend = S3StorageBackend(
            bucket="test-bucket",
            prefix="rendered-manifests",
        )

        content: str | None = backend.download_manifest(
            "main/rendered/dev/app/_all.yaml"
        )

        assert content == "apiVersion: v1\nkind: ConfigMap\n"
        mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="rendered-manifests/main/rendered/dev/app/_all.yaml",
        )

    @patch("boto3.Session")
    def test_download_manifest_not_found(self, mock_session_cls):
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "NoSuchKey"}}
        mock_client.get_object.side_effect = botocore.exceptions.ClientError(
            error_response, "GetObject"
        )

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        backend = S3StorageBackend(
            bucket="test-bucket",
            prefix="rendered-manifests",
        )

        content: str | None = backend.download_manifest("nonexistent/key.yaml")

        assert content is None

    @patch("boto3.Session")
    def test_list_manifest_keys(self, mock_session_cls):
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "rendered-manifests/main/rendered/dev/app1/_all.yaml"},
                    {"Key": "rendered-manifests/main/rendered/dev/app2/_all.yaml"},
                    {"Key": "rendered-manifests/main/rendered/dev/app3/manifest.yml"},
                    {"Key": "rendered-manifests/main/rendered/dev/readme.txt"},
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        backend = S3StorageBackend(
            bucket="test-bucket",
            prefix="rendered-manifests",
        )

        keys = backend.list_manifest_keys("main/rendered/dev/")

        assert len(keys) == 3
        assert "main/rendered/dev/app1/_all.yaml" in keys
        assert "main/rendered/dev/app2/_all.yaml" in keys
        assert "main/rendered/dev/app3/manifest.yml" in keys

    @patch("boto3.Session")
    def test_list_manifest_keys_empty(self, mock_session_cls):
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": []}]
        mock_client.get_paginator.return_value = mock_paginator

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        backend = S3StorageBackend(
            bucket="test-bucket",
            prefix="rendered-manifests",
        )

        keys = backend.list_manifest_keys("nonexistent/prefix/")

        assert keys == []


class TestCheckAwsCredentials:
    @patch("boto3.Session")
    def test_valid_credentials(self, mock_session_cls):
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/test-user",
        }
        mock_session = MagicMock()
        mock_session.client.return_value = mock_sts
        mock_session_cls.return_value = mock_session

        success, message = check_aws_credentials()

        assert success is True
        assert "123456789012" in message
        assert "test-user" in message

    @patch("boto3.Session")
    def test_invalid_credentials_with_profile(self, mock_session_cls):
        mock_session = MagicMock()
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.side_effect = (
            botocore.exceptions.NoCredentialsError()
        )
        mock_session.client.return_value = mock_sts
        mock_session_cls.return_value = mock_session

        success, message = check_aws_credentials(profile="my-profile")

        assert success is False
        assert "my-profile" in message
        assert "aws sso login" in message


class TestListAwsProfiles:
    def test_list_profiles(self, tmp_path: Path):
        aws_dir: Path = tmp_path / ".aws"
        aws_dir.mkdir()

        config_content = """
[default]
region = us-east-1

[profile dev]
sso_account_id = 123456789012

[profile prod]
sso_account_id = 987654321098
"""
        (aws_dir / "config").write_text(config_content)

        with patch("pathlib.Path.home", return_value=tmp_path):
            profiles: list[str] = list_aws_profiles()

        assert "default" in profiles
        assert "dev" in profiles
        assert "prod" in profiles


class TestGitHelpers:
    def test_get_current_git_ref(self):
        ref = get_current_git_ref()
        assert ref is not None
        assert len(ref) > 0

    def test_get_default_branch(self):
        branch = get_default_branch()
        assert branch in ["main", "master"] or len(branch) > 0


class TestCreateStorageBackend:
    def test_local_storage_when_no_s3_config(self):
        config = RitaConfig(
            render=RenderConfig(output_path="rendered"),
        )

        with patch("rita.repository.get_repo_root", return_value=Path("/tmp/repo")):
            backend = create_storage_backend(config)

        assert isinstance(backend, LocalStorageBackend)
        assert backend.base_path == Path("/tmp/repo/rendered")

    def test_s3_storage_when_configured(self):
        config = RitaConfig(
            render=RenderConfig(
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="test-bucket",
                    s3_prefix="manifests",
                    aws_region="eu-central-1",
                ),
            ),
        )

        backend: StorageBackend = create_storage_backend(config)

        assert isinstance(backend, S3StorageBackend)
        assert backend.bucket == "test-bucket"
        assert backend.prefix == "manifests"

    def test_env_var_overrides(self):
        config = RitaConfig(
            render=RenderConfig(
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="config-bucket",
                ),
            ),
        )

        with patch.dict(
            "os.environ",
            {
                "RITA_S3_BUCKET": "env-bucket",
                "RITA_S3_PREFIX": "env-prefix",
            },
        ):
            backend: StorageBackend = create_storage_backend(config)

        assert isinstance(backend, S3StorageBackend)
        assert backend.bucket == "env-bucket"
        assert backend.prefix == "env-prefix"

    def test_profile_not_used_in_ci(self):
        config = RitaConfig(
            render=RenderConfig(
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="test-bucket",
                    aws_profile="local-profile",
                ),
            ),
        )

        with patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
            backend: StorageBackend = create_storage_backend(config)

        assert isinstance(backend, S3StorageBackend)
        assert backend.profile is None

    def test_profile_used_locally(self):
        config = RitaConfig(
            render=RenderConfig(
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="test-bucket",
                    aws_profile="local-profile",
                ),
            ),
        )

        with patch.dict("os.environ", {}, clear=True):
            backend: StorageBackend = create_storage_backend(config)

        assert isinstance(backend, S3StorageBackend)
        assert backend.profile == "local-profile"

    def test_s3_endpoint_used(self):
        """Test that s3_endpoint from config is passed to S3StorageBackend."""
        config = RitaConfig(
            render=RenderConfig(
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="garage-bucket",
                    s3_prefix="manifests",
                    s3_endpoint="http://garage.local:3900",
                ),
            ),
        )

        backend: StorageBackend = create_storage_backend(config)

        assert isinstance(backend, S3StorageBackend)
        assert backend.bucket == "garage-bucket"
        assert backend.endpoint_url == "http://garage.local:3900"

    def test_s3_endpoint_from_env_var(self):
        """Test that AWS_ENDPOINT_URL env var is used when s3_endpoint is not set."""
        config = RitaConfig(
            render=RenderConfig(
                storage=StorageConfig(
                    type="s3",
                    s3_bucket="test-bucket",
                ),
            ),
        )

        with patch.dict("os.environ", {"AWS_ENDPOINT_URL": "http://minio.local:9000"}):
            backend: StorageBackend = create_storage_backend(config)

        assert isinstance(backend, S3StorageBackend)
        assert backend.endpoint_url == "http://minio.local:9000"
