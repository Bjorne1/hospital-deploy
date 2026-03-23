from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from hospital_deploy_tool.log_tools import (
    filter_log_lines,
    parse_line_timestamp,
    read_local_tail,
    resolve_time_range,
)


class LogToolsTests(unittest.TestCase):
    def test_parse_line_timestamp_supports_full_date(self) -> None:
        parsed = parse_line_timestamp("[INFO] 2026-03-23 10:20:30 hello")
        self.assertEqual(parsed, datetime(2026, 3, 23, 10, 20, 30))

    def test_parse_line_timestamp_supports_short_date(self) -> None:
        parsed = parse_line_timestamp("03-23 10:20:30 hello", now=datetime(2026, 3, 24, 8, 0, 0))
        self.assertEqual(parsed, datetime(2026, 3, 23, 10, 20, 30))

    def test_resolve_time_range_returns_expected_window(self) -> None:
        now = datetime(2026, 3, 23, 12, 0, 0)
        start, end = resolve_time_range("30m", None, None, now=now)
        self.assertEqual(start, datetime(2026, 3, 23, 11, 30, 0))
        self.assertEqual(end, now)

    def test_filter_log_lines_applies_keyword_and_context(self) -> None:
        lines = [
            "2026-03-23 10:00:00 begin",
            "2026-03-23 10:00:01 target",
            "2026-03-23 10:00:02 end",
        ]
        result = filter_log_lines(lines, include_keyword="target", context_lines=1)
        self.assertEqual(result.matched_lines, 1)
        self.assertEqual(result.displayed_lines, 3)
        self.assertEqual(result.lines[1], "2026-03-23 10:00:01 target")

    def test_filter_log_lines_skips_lines_without_timestamp_for_time_filter(self) -> None:
        lines = [
            "plain line",
            "2026-03-23 10:00:00 hit",
        ]
        result = filter_log_lines(
            lines,
            start_time=datetime(2026, 3, 23, 9, 0, 0),
            end_time=datetime(2026, 3, 23, 11, 0, 0),
        )
        self.assertEqual(result.matched_lines, 1)
        self.assertEqual(result.skipped_without_time, 1)

    def test_read_local_tail_returns_last_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "demo.log"
            path.write_text("a\nb\nc\nd\n", encoding="utf-8")
            self.assertEqual(read_local_tail(str(path), 2), "c\nd\n")


if __name__ == "__main__":
    unittest.main()
