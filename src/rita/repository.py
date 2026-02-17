"""Git repository utilities."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path
from subprocess import CompletedProcess

from rita.argocd import list_argocd_applications
from rita.config import RitaConfig, load_config


@lru_cache(maxsize=1)
def get_repo_root() -> Path:
    result: CompletedProcess[str] = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


class ConfigProvider:
    """Provides access to configuration with caching."""

    _instance: ConfigProvider | None = None
    _config: RitaConfig | None = None

    @classmethod
    def get_instance(cls) -> ConfigProvider:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
        cls._config = None

    def get_config(self) -> RitaConfig:
        if self._config is None:
            self._config: RitaConfig = load_config()
        return self._config

    def reload(self) -> RitaConfig:
        self._config: RitaConfig = load_config()
        return self._config


def get_config() -> RitaConfig:
    return ConfigProvider.get_instance().get_config()


def get_chart_path(chart_name: str) -> Path:
    config: RitaConfig = get_config()
    return get_repo_root() / config.charts.path / chart_name


def get_argocd_apps_paths(env: str = "dev") -> list[Path]:
    config: RitaConfig = get_config()
    repo_root: Path = get_repo_root()

    for env_config in config.environments:
        if env_config.name == env:
            return [repo_root / p for p in env_config.paths]

    default_path: Path = (
        repo_root / "kubernetes" / "argocd" / "applications" / env / "templates"
    )
    if default_path.exists():
        return [default_path]
    return []


def get_rendered_manifests_path() -> Path:
    config: RitaConfig = get_config()
    return get_repo_root() / config.render.output_path


def get_rendered_path(env: str, app_name: str) -> Path:
    return get_rendered_manifests_path() / env / app_name


def list_available_envs() -> list[str]:
    config: RitaConfig = get_config()

    if config.environments:
        return [env.name for env in config.environments]

    apps_base: Path = get_repo_root() / "kubernetes" / "argocd" / "applications"
    if not apps_base.exists():
        return []

    envs = []
    for env_dir in apps_base.iterdir():
        if env_dir.is_dir() and (env_dir / "templates").exists():
            envs.append(env_dir.name)
    return sorted(envs)


def get_changed_files_from_git(base_ref: str = "origin/main") -> list[str]:
    try:
        result: CompletedProcess[str] = subprocess.run(
            ["git", "diff", "--name-only", base_ref],
            capture_output=True,
            text=True,
            check=True,
        )
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except subprocess.CalledProcessError:
        return []


def list_apps_for_env(env: str) -> list:
    """List ArgoCD applications for an environment.

    Convenience wrapper that combines get_argocd_apps_paths and get_chart_path.
    """
    apps_paths: list[Path] = get_argocd_apps_paths(env)
    return list_argocd_applications(apps_paths, get_chart_path)
