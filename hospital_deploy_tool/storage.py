from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .constants import CONFIG_VERSION, get_config_path, get_data_dir, get_logs_dir
from .models import BackupRecord, DeploymentProfile, HistoryRecord


@dataclass(slots=True)
class AppState:
    profiles: list[DeploymentProfile] = field(default_factory=list)
    backups: list[BackupRecord] = field(default_factory=list)
    history: list[HistoryRecord] = field(default_factory=list)


class Storage:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or get_config_path()

    def ensure_dirs(self) -> None:
        get_data_dir().mkdir(parents=True, exist_ok=True)
        get_logs_dir().mkdir(parents=True, exist_ok=True)

    def load(self) -> AppState:
        self.ensure_dirs()
        if not self.config_path.exists():
            return AppState()
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        profiles = [DeploymentProfile.from_dict(row) for row in payload.get("profiles", [])]
        history = [HistoryRecord.from_dict(row) for row in payload.get("history", [])]
        return AppState(profiles=profiles, backups=[], history=history)

    def save(self, state: AppState) -> None:
        self.ensure_dirs()
        payload = {
            "version": CONFIG_VERSION,
            "profiles": [profile.to_dict() for profile in state.profiles],
            "backups": [],
            "history": [record.to_dict() for record in state.history],
        }
        self.config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert_profile(self, state: AppState, profile: DeploymentProfile) -> None:
        for index, current in enumerate(state.profiles):
            if current.id == profile.id:
                state.profiles[index] = profile
                break
        else:
            state.profiles.append(profile)
        self.save(state)

    def add_backup(self, state: AppState, record: BackupRecord) -> None:
        state.backups.insert(0, record)
        self.save(state)

    def remove_backup(self, state: AppState, backup_id: str) -> None:
        state.backups = [item for item in state.backups if item.id != backup_id]
        self.save(state)

    def add_history(self, state: AppState, record: HistoryRecord) -> None:
        state.history.insert(0, record)
        self.save(state)
