"""Authentication commands for OCI registries."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import rich_click as click


@click.group()
def auth() -> None:
    """Manage authentication for OCI registries."""
    pass


def _get_gh_token() -> tuple[str | None, str | None]:
    """Get username and token from GitHub CLI if available."""
    try:
        token_result: CompletedProcess[str] = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
        )
        token: str = token_result.stdout.strip()

        user_result: CompletedProcess[str] = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            check=True,
        )
        username = user_result.stdout.strip()

        return username, token
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None, None


def _refresh_gh_scopes() -> bool:
    """Refresh GitHub CLI auth to add read:packages scope."""
    click.echo("Refreshing GitHub CLI scopes to include read:packages...")
    try:
        subprocess.run(
            ["gh", "auth", "refresh", "-s", "read:packages"],
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


@auth.command("refresh-scopes")
def auth_refresh_scopes() -> None:
    """Refresh GitHub CLI scopes to include read:packages."""
    if _refresh_gh_scopes():
        click.echo("✓ Scopes refreshed. Now run: rita auth login --use-gh")
    else:
        click.echo("Error: Failed to refresh scopes.", err=True)
        click.echo("  Try: gh auth refresh -s read:packages", err=True)
        raise SystemExit(1)


@auth.command("login")
@click.option("--registry", "-r", default="ghcr.io", help="OCI registry to log in to.")
@click.option("--username", "-u", envvar="GITHUB_USERNAME", help="Username.")
@click.option("--password", "-p", envvar="GITHUB_TOKEN", help="Password/token.")
@click.option("--use-gh", is_flag=True, help="Use credentials from GitHub CLI.")
def auth_login(
    registry: str, username: str | None, password: str | None, use_gh: bool
) -> None:
    """Log in to an OCI registry for pulling charts."""
    if use_gh or (not username and not password):
        gh_username, gh_token = _get_gh_token()
        if gh_username and gh_token:
            click.echo(f"Using credentials from GitHub CLI (user: {gh_username})")
            username = gh_username
            password = gh_token
        elif use_gh:
            click.echo(
                "Error: GitHub CLI not available or not authenticated.", err=True
            )
            click.echo("  Run: gh auth login", err=True)
            raise SystemExit(1)

    if not username:
        username: Any = click.prompt("Username")

    if not password:
        password: Any = click.prompt("Password/Token", hide_input=True)

    cmd = [
        "helm",
        "registry",
        "login",
        registry,
        "--username",
        username,
        "--password-stdin",
    ]

    try:
        subprocess.run(cmd, input=password, capture_output=True, text=True, check=True)
        click.echo(f"✓ Successfully logged in to {registry}")
    except subprocess.CalledProcessError as e:
        click.echo(f"Error: Failed to log in: {e.stderr}", err=True)
        raise SystemExit(1) from None


@auth.command("logout")
@click.option(
    "--registry", "-r", default="ghcr.io", help="OCI registry to log out from."
)
def auth_logout(registry: str) -> None:
    """Log out from an OCI registry."""
    cmd = ["helm", "registry", "logout", registry]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        click.echo(f"✓ Logged out from {registry}")
    except subprocess.CalledProcessError as e:
        click.echo(f"Error: {e.stderr}", err=True)
        raise SystemExit(1) from None


@auth.command("status")
@click.option("--registry", "-r", default="ghcr.io", help="OCI registry to check.")
def auth_status(registry: str) -> None:
    """Check authentication status for an OCI registry."""
    docker_config: Path = Path.home() / ".docker" / "config.json"

    if not docker_config.exists():
        click.echo("✗ Not authenticated (no Docker config found)")
        return

    try:
        with docker_config.open(encoding="utf-8") as f:
            config: Any = json.load(f)

        auths: Any = config.get("auths", {})

        if registry in auths:
            click.echo(f"✓ Authenticated to {registry}")
        else:
            click.echo(f"✗ Not authenticated to {registry}")
            click.echo("  Run: rita auth login")
    except Exception as e:
        click.echo(f"Error checking auth status: {e}", err=True)


@auth.command("ecr")
@click.option("--region", "-r", envvar="AWS_REGION", help="AWS region.")
@click.option("--profile", "-p", envvar="AWS_PROFILE", help="AWS profile to use.")
@click.option("--account-id", envvar="AWS_ACCOUNT_ID", help="AWS account ID.")
def auth_ecr(region: str | None, profile: str | None, account_id: str | None) -> None:
    """Authenticate with AWS ECR."""
    aws_cmd = ["aws"]
    if profile:
        aws_cmd.extend(["--profile", profile])
    if region:
        aws_cmd.extend(["--region", region])

    if not account_id:
        try:
            result: CompletedProcess[str] = subprocess.run(
                [
                    *aws_cmd,
                    "sts",
                    "get-caller-identity",
                    "--query",
                    "Account",
                    "--output",
                    "text",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            account_id: str = result.stdout.strip()
        except subprocess.CalledProcessError as e:
            click.echo("Error: Failed to get AWS account ID.", err=True)
            click.echo(f"  {e.stderr}", err=True)
            raise SystemExit(1) from None
        except FileNotFoundError:
            click.echo("Error: AWS CLI not found.", err=True)
            raise SystemExit(1) from None

    if not region:
        try:
            result: CompletedProcess[str] = subprocess.run(
                [*aws_cmd, "configure", "get", "region"],
                capture_output=True,
                text=True,
                check=True,
            )
            region: str = result.stdout.strip()
        except subprocess.CalledProcessError:
            click.echo("Error: AWS region not specified.", err=True)
            raise SystemExit(1) from None

    registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    click.echo(f"Authenticating to ECR: {registry}")

    try:
        result = subprocess.run(
            [*aws_cmd, "ecr", "get-login-password"],
            capture_output=True,
            text=True,
            check=True,
        )
        password: str = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        click.echo(f"Error: Failed to get ECR password: {e.stderr}", err=True)
        raise SystemExit(1) from None

    cmd = [
        "helm",
        "registry",
        "login",
        registry,
        "--username",
        "AWS",
        "--password-stdin",
    ]

    try:
        subprocess.run(cmd, input=password, capture_output=True, text=True, check=True)
        click.echo(f"✓ Successfully logged in to {registry}")
    except subprocess.CalledProcessError as e:
        click.echo(f"Error: Failed to log in: {e.stderr}", err=True)
        raise SystemExit(1) from None


@auth.command("gcp")
@click.option("--project", "-p", envvar="GOOGLE_CLOUD_PROJECT", help="GCP project ID.")
@click.option("--region", "-r", default="us", help="Artifact Registry region.")
@click.option("--repository", help="Repository name.")
def auth_gcp(project: str | None, region: str, repository: str | None) -> None:
    """Authenticate with Google Artifact Registry."""
    try:
        subprocess.run(["gcloud", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo("Error: gcloud CLI not found.", err=True)
        raise SystemExit(1) from None

    if not project:
        try:
            result: CompletedProcess[str] = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                capture_output=True,
                text=True,
                check=True,
            )
            project: str = result.stdout.strip()
            if not project:
                raise ValueError("No project configured")
        except (subprocess.CalledProcessError, ValueError):
            click.echo("Error: GCP project not specified.", err=True)
            raise SystemExit(1) from None

    registry: str = repository if repository else f"{region}-docker.pkg.dev"
    click.echo(f"Authenticating to GCP Artifact Registry: {registry}")

    try:
        result: CompletedProcess[str] = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            check=True,
        )
        token: str = result.stdout.strip()
    except subprocess.CalledProcessError:
        click.echo("Error: Failed to get GCP access token.", err=True)
        raise SystemExit(1) from None

    cmd = [
        "helm",
        "registry",
        "login",
        registry,
        "--username",
        "oauth2accesstoken",
        "--password-stdin",
    ]

    try:
        subprocess.run(cmd, input=token, capture_output=True, text=True, check=True)
        click.echo(f"✓ Successfully logged in to {registry}")
        if not repository:
            click.echo(f"  Full repository URL: {registry}/{project}/REPOSITORY_NAME")
    except subprocess.CalledProcessError as e:
        click.echo(f"Error: Failed to log in: {e.stderr}", err=True)
        raise SystemExit(1) from None


@auth.command("azure")
@click.option("--registry", "-r", required=True, help="ACR registry name.")
@click.option("--use-sp", is_flag=True, help="Use service principal credentials.")
def auth_azure(registry: str, use_sp: bool) -> None:
    """Authenticate with Azure Container Registry."""
    if not registry.endswith(".azurecr.io"):
        registry_url = f"{registry}.azurecr.io"
        registry_name: str = registry
    else:
        registry_url: str = registry
        registry_name: str = registry.replace(".azurecr.io", "")

    click.echo(f"Authenticating to ACR: {registry_url}")

    if use_sp:
        client_id: str | None = os.environ.get("AZURE_CLIENT_ID")
        client_secret: str | None = os.environ.get("AZURE_CLIENT_SECRET")

        if not client_id or not client_secret:
            click.echo("Error: Service principal credentials not found.", err=True)
            raise SystemExit(1)

        username = client_id
        password = client_secret
    else:
        try:
            result: CompletedProcess[str] = subprocess.run(
                [
                    "az",
                    "acr",
                    "login",
                    "--name",
                    registry_name,
                    "--expose-token",
                    "--output",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            token_data: Any = json.loads(result.stdout)
            username = "00000000-0000-0000-0000-000000000000"
            password: Any = token_data.get("accessToken", "")
        except subprocess.CalledProcessError as e:
            click.echo("Error: Failed to get ACR token.", err=True)
            if e.stderr:
                click.echo(f"  {e.stderr}", err=True)
            raise SystemExit(1) from None
        except FileNotFoundError:
            click.echo("Error: Azure CLI (az) not found.", err=True)
            raise SystemExit(1) from None
        except json.JSONDecodeError:
            click.echo("Error: Failed to parse ACR token response.", err=True)
            raise SystemExit(1) from None

    cmd = [
        "helm",
        "registry",
        "login",
        registry_url,
        "--username",
        username,
        "--password-stdin",
    ]

    try:
        subprocess.run(cmd, input=password, capture_output=True, text=True, check=True)
        click.echo(f"✓ Successfully logged in to {registry_url}")
    except subprocess.CalledProcessError as e:
        click.echo(f"Error: Failed to log in: {e.stderr}", err=True)
        raise SystemExit(1) from None
