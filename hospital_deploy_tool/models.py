from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from .constants import (
    DEFAULT_BACKUP_ROOT,
    DEFAULT_MAX_BACKUPS,
    DEFAULT_PORT,
    SOURCE_TYPE_ARCHIVE,
    SOURCE_TYPE_DIRECTORY,
    SOURCE_TYPE_FILE,
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid4().hex


@dataclass(slots=True)
class DeploymentProfile:
    id: str = field(default_factory=new_id)
    name: str = "New Profile"
    source_type: str = SOURCE_TYPE_FILE
    source_path: str = ""
    host: str = ""
    port: int = DEFAULT_PORT
    username: str = ""
    password: str = ""
    target_path: str = ""
    post_commands: list[str] = field(default_factory=list)
    backup_enabled: bool = True
    max_backup_count: int = DEFAULT_MAX_BACKUPS
    backup_root: str = DEFAULT_BACKUP_ROOT
    compress_upload: bool = False

    @property
    def is_archive(self) -> bool:
        return self.source_type == SOURCE_TYPE_ARCHIVE

    @property
    def is_directory(self) -> bool:
        return self.source_type == SOURCE_TYPE_DIRECTORY

    @property
    def is_file(self) -> bool:
        return self.source_type == SOURCE_TYPE_FILE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeploymentProfile":
        profile = cls()
        for key, value in payload.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        profile.post_commands = [cmd for cmd in profile.post_commands if cmd.strip()]
        if profile.port <= 0:
            profile.port = DEFAULT_PORT
        if profile.max_backup_count <= 0:
            profile.max_backup_count = DEFAULT_MAX_BACKUPS
        if profile.source_type not in {SOURCE_TYPE_FILE, SOURCE_TYPE_DIRECTORY, SOURCE_TYPE_ARCHIVE}:
            profile.source_type = SOURCE_TYPE_FILE
        return profile


@dataclass(slots=True)
class BackupRecord:
    id: str = field(default_factory=new_id)
    profile_id: str = ""
    profile_name: str = ""
    host: str = ""
    target_path: str = ""
    source_type: str = SOURCE_TYPE_FILE
    remote_backup_path: str = ""
    backup_mode: str = ""
    backup_size: int = 0
    created_at: str = field(default_factory=now_iso)
    post_commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BackupRecord":
        record = cls()
        for key, value in payload.items():
            if hasattr(record, key):
                setattr(record, key, value)
        record.post_commands = [cmd for cmd in record.post_commands if cmd.strip()]
        return record


@dataclass(slots=True)
class HistoryRecord:
    id: str = field(default_factory=new_id)
    profile_id: str = ""
    profile_name: str = ""
    action: str = ""
    host: str = ""
    target_path: str = ""
    source_type: str = SOURCE_TYPE_FILE
    source_path: str = ""
    success: bool = False
    started_at: str = field(default_factory=now_iso)
    ended_at: str = ""
    duration_seconds: float = 0.0
    log_file: str = ""
    summary: str = ""
    backup_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HistoryRecord":
        record = cls()
        for key, value in payload.items():
            if hasattr(record, key):
                setattr(record, key, value)
        return record
