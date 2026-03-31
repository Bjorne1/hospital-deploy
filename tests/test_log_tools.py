from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from PySide2.QtWidgets import QApplication

from hospital_deploy_tool.log_tools import (
    filter_log_lines,
    parse_line_timestamp,
    read_local_tail,
    resolve_time_range,
)
from hospital_deploy_tool.models import DeploymentProfile
from hospital_deploy_tool.ui.log_workbench import LogViewerDialog


class LogToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

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

    def test_filter_log_lines_keeps_multiline_event_when_any_line_matches(self) -> None:
        lines = [
            "2026-03-23 10:00:00 SQL start",
            "SELECT *",
            "FROM t WHERE id = 1",
            "2026-03-23 10:00:01 done",
        ]
        result = filter_log_lines(lines, include_keyword="where id = 1")
        self.assertEqual(result.matched_lines, 3)
        self.assertEqual(result.displayed_lines, 3)
        self.assertEqual(result.lines[0], "2026-03-23 10:00:00 SQL start")
        self.assertEqual(result.lines[-1], "FROM t WHERE id = 1")

    def test_read_local_tail_returns_last_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "demo.log"
            path.write_text("a\nb\nc\nd\n", encoding="utf-8")
            self.assertEqual(read_local_tail(str(path), 2), "c\nd\n")

    def test_log_viewer_defaults_to_service_log(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
            current_log_file=r"C:\temp\current.log",
        )
        try:
            self.assertEqual(dialog._current_source_key(), "remote_default")
        finally:
            dialog.close()

    def test_source_switch_during_loading_refetches_latest_selection(self) -> None:
        class RunningWorkerStub:
            @staticmethod
            def isRunning() -> bool:
                return True

        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
            current_log_file=r"C:\temp\current.log",
        )
        try:
            current_index = dialog._source_combo.findData("current")
            dialog._source_combo.blockSignals(True)
            dialog._source_combo.setCurrentIndex(current_index)
            dialog._source_combo.blockSignals(False)
            dialog._update_source_caption()

            dialog._worker = RunningWorkerStub()
            dialog._worker_request = ("current", dialog._line_limit_spin.value())

            remote_default_index = dialog._source_combo.findData("remote_default")
            dialog._source_combo.setCurrentIndex(remote_default_index)

            refresh_calls: list[str | None] = []
            dialog._fetch_current = lambda: refresh_calls.append(dialog._current_source_key())  # type: ignore[method-assign]

            dialog._on_fetch_done("2026-03-30 10:00:00 stale")

            self.assertEqual(refresh_calls, ["remote_default"])
            self.assertEqual(dialog._raw_lines, [])
        finally:
            dialog.close()

    def test_preset_time_range_updates_visible_controls_and_preserves_custom_range(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
        )
        try:
            custom_start = datetime(2026, 3, 20, 8, 0, 0)
            custom_end = datetime(2026, 3, 20, 9, 0, 0)
            dialog._range_combo.setCurrentIndex(dialog._range_combo.findData("custom"))
            dialog._start_edit.setDateTime(custom_start)
            dialog._end_edit.setDateTime(custom_end)

            before_switch = datetime.now().replace(microsecond=0)
            dialog._range_combo.setCurrentIndex(dialog._range_combo.findData("1h"))
            visible_start = dialog._start_edit.dateTime().toPython().replace(microsecond=0)
            visible_end = dialog._end_edit.dateTime().toPython().replace(microsecond=0)

            self.assertLessEqual(abs((visible_start - (before_switch - timedelta(hours=1))).total_seconds()), 5)
            self.assertLessEqual(abs((visible_end - before_switch).total_seconds()), 5)

            dialog._range_combo.setCurrentIndex(dialog._range_combo.findData("today"))
            today_start = dialog._start_edit.dateTime().toPython().replace(microsecond=0)
            today_end = dialog._end_edit.dateTime().toPython().replace(microsecond=0)
            after_today = datetime.now().replace(microsecond=0)

            self.assertEqual((today_start.hour, today_start.minute, today_start.second), (0, 0, 0))
            self.assertEqual(today_start.date(), after_today.date())
            self.assertLessEqual(abs((today_end - after_today).total_seconds()), 5)

            dialog._range_combo.setCurrentIndex(dialog._range_combo.findData("custom"))
            self.assertEqual(dialog._start_edit.dateTime().toPython().replace(microsecond=0), custom_start)
            self.assertEqual(dialog._end_edit.dateTime().toPython().replace(microsecond=0), custom_end)
        finally:
            dialog.close()

    def test_log_viewer_can_restore_escaped_line_breaks(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
        )
        try:
            dialog._raw_lines = ["2026-03-23 10:00:00 SQL: SELECT 1\\nFROM dual"]
            dialog._apply_filters()
            self.assertIn("SELECT 1\nFROM dual", dialog._display_text)

            dialog._unescape_newline_check.setChecked(False)
            self.assertIn("SELECT 1\\nFROM dual", dialog._display_text)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
