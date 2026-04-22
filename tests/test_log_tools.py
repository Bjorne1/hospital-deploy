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
from hospital_deploy_tool.constants import PROFILE_KIND_UNSET
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

    def test_filter_log_lines_supports_bracketed_timestamp_prefix_for_time_filter(self) -> None:
        lines = [
            "[2026-04-22 10:00:00] [INFO] hello",
            "[2026-04-22 10:00:01] [INFO] world",
        ]
        result = filter_log_lines(
            lines,
            start_time=datetime(2026, 4, 22, 0, 0, 0),
            end_time=datetime(2026, 4, 22, 23, 59, 59),
        )
        self.assertEqual(result.matched_lines, 2)
        self.assertEqual(result.displayed_lines, 2)
        self.assertEqual(result.skipped_without_time, 0)

    def test_filter_log_lines_supports_short_timestamp_prefix_for_time_filter(self) -> None:
        lines = [
            "04-22 10:00:00 INFO hello",
            "04-22 10:00:01 INFO world",
        ]
        result = filter_log_lines(
            lines,
            start_time=datetime(2026, 4, 22, 0, 0, 0),
            end_time=datetime(2026, 4, 22, 23, 59, 59),
            now=datetime(2026, 4, 22, 12, 0, 0),
        )
        self.assertEqual(result.matched_lines, 2)
        self.assertEqual(result.displayed_lines, 2)
        self.assertEqual(result.skipped_without_time, 0)

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

    def test_log_viewer_limits_sources_to_service_logs_and_recent_three_local_logs(self) -> None:
        history = [
            self._history_record("1", r"C:\logs\one.log", "2026-04-22T10:00:00"),
            self._history_record("2", r"C:\logs\two.log", "2026-04-22T09:00:00"),
            self._history_record("3", r"C:\logs\three.log", "2026-04-22T08:00:00"),
            self._history_record("4", r"C:\logs\four.log", "2026-04-22T07:00:00"),
        ]
        dialog = LogViewerDialog(
            profile=DeploymentProfile(id="profile-1", name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=history,
            initial_log_file=r"C:\logs\four.log",
        )
        try:
            self.assertEqual([source.key for source in dialog._sources[:2]], ["remote_default", "remote_error"])
            self.assertEqual(len(dialog._sources), 5)
            self.assertIn(r"C:\logs\four.log", [source.path for source in dialog._sources])
            self.assertNotIn(r"C:\logs\three.log", [source.path for source in dialog._sources[2:]])
        finally:
            dialog.close()

    def test_refresh_context_clears_previous_initial_log_file(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(id="profile-1", name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
            initial_log_file=r"C:\logs\initial.log",
        )
        try:
            self.assertEqual(dialog.initial_log_file, r"C:\logs\initial.log")
            dialog.refresh_context(dialog.profile, [], initial_log_file="", auto_fetch=False)
            self.assertEqual(dialog.initial_log_file, "")
            self.assertNotIn(r"C:\logs\initial.log", [source.path for source in dialog._sources])
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
            initial_log_file=r"C:\temp\current.log",
        )
        try:
            current_index = dialog._source_combo.findData("history:current")
            dialog._source_combo.blockSignals(True)
            dialog._source_combo.setCurrentIndex(current_index)
            dialog._source_combo.blockSignals(False)
            dialog._update_source_caption()

            dialog._worker = RunningWorkerStub()
            dialog._worker_request = ("history:current", dialog._line_limit_spin.value())
            dialog._raw_lines = ["2026-03-30 10:00:00 stale"]
            dialog._apply_filters()

            remote_default_index = dialog._source_combo.findData("remote_default")
            dialog._source_combo.setCurrentIndex(remote_default_index)

            refresh_calls: list[str | None] = []
            dialog._fetch_current = lambda: refresh_calls.append(dialog._current_source_key())  # type: ignore[method-assign]

            dialog._on_fetch_done("2026-03-30 10:00:00 stale")

            self.assertEqual(refresh_calls, ["remote_default"])
            self.assertEqual(dialog._raw_lines, [])
            self.assertIn("正在加载 服务日志 | default.log", dialog._log_area.toPlainText())
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

    def test_profile_defaults_to_unset_kind_when_old_config_has_no_field(self) -> None:
        profile = DeploymentProfile.from_dict({"name": "legacy"})
        self.assertEqual(profile.profile_kind, PROFILE_KIND_UNSET)

    def test_profile_invalid_kind_falls_back_to_unset(self) -> None:
        profile = DeploymentProfile.from_dict({"name": "broken", "profile_kind": "java"})
        self.assertEqual(profile.profile_kind, PROFILE_KIND_UNSET)

    @staticmethod
    def _history_record(record_id: str, log_file: str, started_at: str) -> object:
        from hospital_deploy_tool.models import HistoryRecord

        return HistoryRecord(
            id=record_id,
            profile_id="profile-1",
            profile_name="demo",
            action="deploy",
            host="127.0.0.1",
            log_file=log_file,
            started_at=started_at,
            success=True,
        )


if __name__ == "__main__":
    unittest.main()
