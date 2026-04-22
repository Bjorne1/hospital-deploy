from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

_FULL_TIMESTAMP_RE = re.compile(r"(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2})")
_SHORT_TIMESTAMP_RE = re.compile(r"(\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_EVENT_START_TIMESTAMP_RE = re.compile(
    r"^\s*(?:\[?\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?|\[?\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[.,]\d+)?)"
)


@dataclass(frozen=True, slots=True)
class FilteredLogResult:
    lines: list[str]
    total_lines: int
    matched_lines: int
    displayed_lines: int
    skipped_without_time: int


def read_local_tail(path: str, lines: int) -> str:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"日志文件不存在: {path}")
    if not target.is_file():
        raise ValueError(f"不是日志文件: {path}")
    if lines <= 0:
        return target.read_text(encoding="utf-8")
    with target.open("r", encoding="utf-8", errors="replace") as handle:
        tail_lines = deque(handle, maxlen=lines)
    return "".join(tail_lines)


def parse_line_timestamp(line: str, now: datetime | None = None) -> datetime | None:
    current = now or datetime.now()
    match = _FULL_TIMESTAMP_RE.search(line)
    if match:
        stamp = match.group(1).replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(stamp, fmt)
            except ValueError:
                continue
    match = _SHORT_TIMESTAMP_RE.search(line)
    if not match:
        return None
    try:
        short_value = datetime.strptime(match.group(1), "%m-%d %H:%M:%S")
    except ValueError:
        return None
    return short_value.replace(year=current.year)


def resolve_time_range(
    mode: str,
    custom_start: datetime | None,
    custom_end: datetime | None,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    current = (now or datetime.now()).replace(microsecond=0)
    if mode == "all":
        return None, None
    if mode == "10m":
        return current - timedelta(minutes=10), current
    if mode == "30m":
        return current - timedelta(minutes=30), current
    if mode == "1h":
        return current - timedelta(hours=1), current
    if mode == "today":
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, current
    return custom_start, custom_end


def filter_log_lines(
    lines: list[str],
    include_keyword: str = "",
    exclude_keyword: str = "",
    case_sensitive: bool = False,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    context_lines: int = 0,
    now: datetime | None = None,
) -> FilteredLogResult:
    include = include_keyword.strip()
    exclude = exclude_keyword.strip()
    use_time = start_time is not None or end_time is not None
    normalized_include = include if case_sensitive else include.lower()
    normalized_exclude = exclude if case_sensitive else exclude.lower()
    matched_indexes: list[int] = []
    skipped_without_time = 0
    for start, end, event_time in _group_line_events(lines, now):
        event_lines = lines[start : end + 1]
        event_text = "\n".join(event_lines)
        probe = event_text if case_sensitive else event_text.lower()
        if normalized_include and normalized_include not in probe:
            continue
        if normalized_exclude and normalized_exclude in probe:
            continue
        if use_time:
            if event_time is None:
                skipped_without_time += end - start + 1
                continue
            if start_time is not None and event_time < start_time:
                continue
            if end_time is not None and event_time > end_time:
                continue
        matched_indexes.extend(range(start, end + 1))
    displayed_indexes = _expand_indexes(matched_indexes, len(lines), context_lines)
    filtered_lines = [lines[index] for index in displayed_indexes]
    return FilteredLogResult(
        lines=filtered_lines,
        total_lines=len(lines),
        matched_lines=len(matched_indexes),
        displayed_lines=len(filtered_lines),
        skipped_without_time=skipped_without_time,
    )


def _expand_indexes(indexes: list[int], total: int, context_lines: int) -> list[int]:
    if context_lines <= 0 or not indexes:
        return indexes
    expanded: set[int] = set()
    for index in indexes:
        start = max(0, index - context_lines)
        end = min(total - 1, index + context_lines)
        expanded.update(range(start, end + 1))
    return sorted(expanded)


def _group_line_events(
    lines: list[str],
    now: datetime | None,
) -> list[tuple[int, int, datetime | None]]:
    if not lines:
        return []
    ranges: list[tuple[int, int, datetime | None]] = []
    start = 0
    stamp = parse_line_timestamp(lines[0], now) if _is_event_start(lines[0]) else None
    for index in range(1, len(lines)):
        line = lines[index]
        if not _is_event_start(line):
            continue
        ranges.append((start, index - 1, stamp))
        start = index
        stamp = parse_line_timestamp(line, now)
    ranges.append((start, len(lines) - 1, stamp))
    return ranges


def _is_event_start(line: str) -> bool:
    return _EVENT_START_TIMESTAMP_RE.search(line) is not None
