from __future__ import annotations

from pathlib import Path

import yaml

from oh_no_my_claudecode.models import ProjectConfig

CONFIG_FILE_NAME = "config.yaml"


def default_config(repo_root: Path) -> ProjectConfig:
    return ProjectConfig(repo_root=repo_root.as_posix())


def config_path(repo_root: Path) -> Path:
    return repo_root / ".onmc" / CONFIG_FILE_NAME


def database_path(config: ProjectConfig, repo_root: Path) -> Path:
    return repo_root / config.storage.database_path


def state_dir(config: ProjectConfig, repo_root: Path) -> Path:
    return repo_root / config.storage.state_dir


def compiled_dir(config: ProjectConfig, repo_root: Path) -> Path:
    return repo_root / config.storage.compiled_dir


def logs_dir(config: ProjectConfig, repo_root: Path) -> Path:
    return repo_root / config.storage.logs_dir


def create_state_dirs(config: ProjectConfig, repo_root: Path) -> None:
    state_dir(config, repo_root).mkdir(parents=True, exist_ok=True)
    compiled_dir(config, repo_root).mkdir(parents=True, exist_ok=True)
    logs_dir(config, repo_root).mkdir(parents=True, exist_ok=True)


def write_config(config: ProjectConfig, repo_root: Path) -> Path:
    target = config_path(repo_root)
    create_state_dirs(config, repo_root)
    target.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return target


def load_config(repo_root: Path) -> ProjectConfig:
    target = config_path(repo_root)
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return ProjectConfig.model_validate(payload)


def config_exists(repo_root: Path) -> bool:
    return config_path(repo_root).exists()
