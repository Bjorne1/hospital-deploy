from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ROTATION_INDEX_RE = re.compile(r"\.(\d+)\.log(?:\.gz)?$")
_LOG_KIND_ORDER = {
    "info": 0,
    "error": 1,
    "warn": 2,
    "debug": 3,
    "sync-sbo": 4,
}


@dataclass(frozen=True, slots=True)
class HistoryLogFile:
    date: str
    name: str
    remote_path: str
    size: int
    modified_at: datetime | None = None


class HistoryLogCache:
    def __init__(self, root: Path, profile_id: str, profile_name: str, history_root_path: str) -> None:
        self.root = root
        self.profile_id = profile_id
        self.profile_name = profile_name
        self.history_root_path = history_root_path

    @property
    def base_dir(self) -> Path:
        profile = _safe_cache_name(self.profile_name.strip() or self.profile_id or "profile")
        digest = hashlib.sha1(f"{self.profile_id}|{self.history_root_path}".encode("utf-8")).hexdigest()[:12]
        return self.root / f"{profile}_{digest}"

    @property
    def catalog_path(self) -> Path:
        return self.base_dir / "catalog.json"

    @property
    def archives_dir(self) -> Path:
        return self.base_dir / "archives"

    @property
    def text_dir(self) -> Path:
        return self.base_dir / "text"

    def list_dates(self) -> list[str]:
        catalog = self._load_catalog()
        dates = set(catalog.get("dates", []))
        dates.update(str(date) for date in catalog.get("files", {}))
        return sorted((date for date in dates if is_history_date_dir(date)), reverse=True)

    def list_files(self, date: str) -> list[HistoryLogFile]:
        catalog = self._load_catalog()
        files_by_date = catalog.get("files", {})
        rows = files_by_date.get(date, [])
        return sorted((_history_file_from_dict(row) for row in rows), key=history_log_sort_key)

    def update_dates(self, dates: list[str]) -> None:
        catalog = self._load_catalog()
        existing = set(catalog.get("dates", []))
        existing.update(date for date in dates if is_history_date_dir(date))
        catalog["dates"] = sorted(existing, reverse=True)
        self._save_catalog(catalog)

    def update_files(self, date: str, files: list[HistoryLogFile]) -> None:
        catalog = self._load_catalog()
        dates = set(catalog.get("dates", []))
        dates.add(date)
        catalog["dates"] = sorted((item for item in dates if is_history_date_dir(item)), reverse=True)
        files_by_date = dict(catalog.get("files", {}))
        files_by_date[date] = [_history_file_to_dict(file) for file in sorted(files, key=history_log_sort_key)]
        catalog["files"] = files_by_date
        self._save_catalog(catalog)

    def archive_path(self, file: HistoryLogFile) -> Path:
        return self.archives_dir / _safe_history_cache_name(file)

    def text_path(self, file: HistoryLogFile) -> Path:
        return self.text_dir / f"{_safe_history_cache_name(file)}.txt"

    def aggregate_path(self) -> Path:
        return self.base_dir / "selected-history.log"

    def _load_catalog(self) -> dict[str, Any]:
        if not self.catalog_path.exists():
            return self._empty_catalog()
        try:
            payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"历史日志缓存清单损坏: {self.catalog_path} ({exc})") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"历史日志缓存清单格式错误: {self.catalog_path}")
        payload.setdefault("dates", [])
        payload.setdefault("files", {})
        return payload

    def _save_catalog(self, catalog: dict[str, Any]) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog["profile_id"] = self.profile_id
        catalog["history_root_path"] = self.history_root_path
        catalog["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    def _empty_catalog(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "history_root_path": self.history_root_path,
            "dates": [],
            "files": {},
        }


def is_history_date_dir(name: str) -> bool:
    return _DATE_DIR_RE.match(name) is not None


def is_history_log_file(name: str) -> bool:
    return name.endswith(".log") or name.endswith(".log.gz")


def history_log_kind(filename: str) -> str:
    return filename.split(".", 1)[0].strip() or "log"


def history_log_rotation_index(filename: str) -> int:
    match = _ROTATION_INDEX_RE.search(filename)
    if not match:
        return -1
    return int(match.group(1))


def history_log_label(filename: str) -> str:
    kind = history_log_kind(filename)
    index = history_log_rotation_index(filename)
    if index >= 0:
        return f"{kind}.{index}"
    return kind


def history_log_sort_key(file: HistoryLogFile) -> tuple[int, str, int, str]:
    kind = history_log_kind(file.name)
    return (_LOG_KIND_ORDER.get(kind, 99), kind, -history_log_rotation_index(file.name), file.name)


def format_bytes(size: int) -> str:
    value = float(max(size, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} GB"


def read_history_log_text(path: Path) -> str:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    return path.read_text(encoding="utf-8", errors="replace")


def _history_file_to_dict(file: HistoryLogFile) -> dict[str, Any]:
    return {
        "date": file.date,
        "name": file.name,
        "remote_path": file.remote_path,
        "size": file.size,
        "modified_at": file.modified_at.isoformat(timespec="seconds") if file.modified_at else "",
    }


def _history_file_from_dict(payload: dict[str, Any]) -> HistoryLogFile:
    modified_at = None
    modified_at_text = str(payload.get("modified_at") or "")
    if modified_at_text:
        try:
            modified_at = datetime.fromisoformat(modified_at_text)
        except ValueError as exc:
            raise RuntimeError(f"历史日志缓存时间格式错误: {modified_at_text}") from exc
    return HistoryLogFile(
        date=str(payload.get("date") or ""),
        name=str(payload.get("name") or ""),
        remote_path=str(payload.get("remote_path") or ""),
        size=int(payload.get("size") or 0),
        modified_at=modified_at,
    )


def _safe_cache_name(value: str) -> str:
    text = value.strip() or "cache"
    return "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in text)


def _safe_history_cache_name(file: HistoryLogFile) -> str:
    digest = hashlib.sha1(file.remote_path.encode("utf-8")).hexdigest()[:12]
    value = f"{file.date}_{digest}_{file.name}"
    return _safe_cache_name(value)
