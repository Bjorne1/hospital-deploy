from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Hospital Deploy Tool"
APP_SLUG = "hospital-deploy-tool"
CONFIG_VERSION = 3
DEFAULT_PORT = 22
DEFAULT_BACKUP_ROOT = "/opt/deploy-backups"
DEFAULT_MAX_BACKUPS = 10
SOURCE_TYPE_FILE = "file"
SOURCE_TYPE_DIRECTORY = "directory"
SOURCE_TYPE_ARCHIVE = "archive"
PROFILE_KIND_UNSET = "unset"
PROFILE_KIND_BACKEND = "backend"
PROFILE_KIND_FRONTEND = "frontend"
ACTION_DEPLOY = "deploy"
ACTION_UPLOAD_ONLY = "upload_only"
ACTION_COMMANDS_ONLY = "commands_only"
ACTION_TEST_CONNECTION = "test_connection"
ACTION_RESTORE_BACKUP = "restore_backup"


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _get_exe_dir() -> Path:
    """exe 所在目录（开发时为项目根目录）。"""
    if _is_frozen():
        return Path(sys.executable).parent
    return Path.cwd()


def get_data_dir() -> Path:
    if _is_frozen():
        return _get_exe_dir()
    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) if root else Path.home()
    return base / APP_NAME


def get_config_path() -> Path:
    exe_dir = _get_exe_dir()
    # 优先读取同级目录的 config.json
    config_json = exe_dir / "config.json"
    if config_json.exists():
        return config_json
    # 否则找同级目录第一个 .json 文件
    json_files = sorted(exe_dir.glob("*.json"))
    if json_files:
        return json_files[0]
    # 都没有则默认使用 config.json（新建时写入）
    return config_json


def get_logs_dir() -> Path:
    return get_data_dir() / "logs"
