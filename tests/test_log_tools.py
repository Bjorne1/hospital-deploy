from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from PySide2.QtWidgets import QApplication

from hospital_deploy_tool.constants import PROFILE_KIND_UNSET
from hospital_deploy_tool.log_tools import (
    filter_log_lines,
    group_line_events,
    parse_line_timestamp,
    read_local_tail,
    read_local_text,
    resolve_time_range,
)
from hospital_deploy_tool.models import DeploymentProfile
from hospital_deploy_tool.ui.log_workbench import LogFetchResult, LogFetchWorker, LogViewerDialog


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

    def test_filter_log_lines_supports_trace_id_keyword(self) -> None:
        lines = [
            '2026-05-12 09:15:12.070 [a59332102fba437bb6db917fdc4646d1] INFO  demo traceId=a59332102fba437bb6db917fdc4646d1',
            '2026-05-12 09:15:13.070 [11111111111111111111111111111111] INFO  demo traceId=11111111111111111111111111111111',
        ]
        result = filter_log_lines(lines, trace_id_keyword="a59332102fba437bb6db917fdc4646d1")
        self.assertEqual(result.matched_lines, 1)
        self.assertEqual(result.displayed_lines, 1)
        self.assertIn("a59332102fba437bb6db917fdc4646d1", result.lines[0])

    def test_filter_log_lines_supports_trace_id_in_brackets(self) -> None:
        lines = [
            '2026-05-12 09:15:12.070 [a59332102fba437bb6db917fdc4646d1] INFO demo',
            '2026-05-12 09:15:13.070 [11111111111111111111111111111111] INFO demo',
        ]
        result = filter_log_lines(lines, trace_id_keyword="a59332102fba437bb6db917fdc4646d1")
        self.assertEqual(result.matched_lines, 1)
        self.assertEqual(result.displayed_lines, 1)

    def test_read_local_tail_returns_last_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "demo.log"
            path.write_text("a\nb\nc\nd\n", encoding="utf-8")
            self.assertEqual(read_local_tail(str(path), 2), "c\nd\n")

    def test_read_local_text_returns_full_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "demo.log"
            path.write_text("a\nb\nc\n", encoding="utf-8")
            self.assertEqual(read_local_text(str(path)), "a\nb\nc\n")

    def test_group_line_events_keeps_multiline_block(self) -> None:
        lines = [
            "2026-05-12 10:00:00 first",
            "line 2",
            "2026-05-12 10:00:01 second",
        ]
        self.assertEqual(group_line_events(lines), [(0, 1, datetime(2026, 5, 12, 10, 0, 0)), (2, 2, datetime(2026, 5, 12, 10, 0, 1))])

    def test_log_viewer_defaults_to_service_log(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
            current_log_file=r"C:\temp\current.log",
        )
        try:
            self.assertEqual(dialog._current_source_key(), "info")
        finally:
            dialog.close()

    def test_log_viewer_normalizes_legacy_default_log_path_to_info_log(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(
                name="demo",
                host="127.0.0.1",
                target_path="/srv/app",
                log_path_default="/srv/app/logs/default.log",
            ),
            history=[],
        )
        try:
            self.assertEqual(dialog._sources["info"].path, "/srv/app/logs/info.log")
        finally:
            dialog.close()

    def test_log_viewer_includes_all_source_and_four_service_logs(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(id="profile-1", name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
        )
        try:
            self.assertEqual(list(dialog._sources), ["all", "info", "error", "debug", "warn"])
            self.assertEqual(dialog._sources["all"].label, "服务日志 | 所有日志")
            self.assertEqual(dialog._sources["info"].path, "/srv/app/logs/info.log")
            self.assertEqual(dialog._sources["error"].path, "/srv/app/logs/error.log")
            self.assertEqual(dialog._sources["debug"].path, "/srv/app/logs/debug.log")
            self.assertEqual(dialog._sources["warn"].path, "/srv/app/logs/warn.log")
            self.assertEqual(len(dialog._source_buttons), 5)
            self.assertEqual(dialog._current_source_key(), "info")
        finally:
            dialog.close()

    def test_log_viewer_can_open_initial_history_log_without_adding_it_to_sources(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(id="profile-1", name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
            initial_log_file=r"C:\logs\initial.log",
        )
        try:
            self.assertEqual(dialog._current_source_key(), r"history:C:\logs\initial.log")
            self.assertEqual(dialog._current_source().path, r"C:\logs\initial.log")
            self.assertEqual(list(dialog._sources), ["all", "info", "error", "debug", "warn"])
            self.assertFalse(any(button.isChecked() for button in dialog._source_buttons.values()))
            self.assertFalse(dialog._refresh_button.isEnabled())
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
            self.assertNotIn(r"C:\logs\initial.log", [source.path for source in dialog._sources.values()])
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
        )
        try:
            dialog._worker = RunningWorkerStub()
            dialog._worker_request = "info"
            dialog._raw_lines = ["2026-03-30 10:00:00 stale"]
            dialog._display_text = "2026-03-30 10:00:00 stale"
            dialog._apply_filters()

            dialog._source_buttons["error"].setChecked(True)
            dialog._on_source_button_clicked("error")

            refresh_calls: list[str | None] = []
            dialog._fetch_current = lambda: refresh_calls.append(dialog._current_source_key())  # type: ignore[method-assign]

            dialog._on_fetch_done(
                LogFetchResult(
                    text="2026-03-30 10:00:00 stale",
                    local_path=r"C:\temp\info.log",
                    updated_at=datetime(2026, 3, 30, 10, 0, 0),
                )
            )

            self.assertEqual(refresh_calls, ["error"])
            self.assertEqual(dialog._raw_lines, ["2026-03-30 10:00:00 stale"])
            self.assertIn("2026-03-30 10:00:00 stale", dialog._log_area.toPlainText())
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

    def test_refresh_button_disabled_for_history_source(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
            initial_log_file=r"C:\logs\history.log",
        )
        try:
            self.assertFalse(dialog._refresh_button.isEnabled())
        finally:
            dialog.close()

    def test_log_viewer_removed_paging_controls(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
        )
        try:
            self.assertFalse(hasattr(dialog, "_line_limit_spin"))
            self.assertFalse(hasattr(dialog, "_load_more_button"))
            self.assertFalse(hasattr(dialog, "_jump_button"))
            self.assertEqual(dialog._refresh_button.text(), "下载最新")
        finally:
            dialog.close()

    def test_log_fetch_worker_aggregate_merges_logs_by_timestamp_and_keeps_multiline_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            worker = LogFetchWorker(
                DeploymentProfile(id="p1", name="demo", host="127.0.0.1", target_path="/srv/app"),
                LogViewerDialog(
                    profile=DeploymentProfile(id="inner", name="demo", host="127.0.0.1", target_path="/srv/app"),
                    history=[],
                )._sources.get("info") or None,  # type: ignore[arg-type]
            )
            info_path = Path(tmp_dir) / "info.log"
            error_path = Path(tmp_dir) / "error.log"
            debug_path = Path(tmp_dir) / "debug.log"
            warn_path = Path(tmp_dir) / "warn.log"
            info_path.write_text("2026-05-12 10:00:02 info line\n", encoding="utf-8")
            error_path.write_text("2026-05-12 10:00:01 error start\nstack line\n", encoding="utf-8")
            debug_path.write_text("2026-05-12 10:00:03 debug line\n", encoding="utf-8")
            warn_path.write_text("2026-05-12 10:00:00 warn line\n", encoding="utf-8")

            merged = worker._merge_log_files([
                ("info", info_path),
                ("error", error_path),
                ("debug", debug_path),
                ("warn", warn_path),
            ])
            self.assertEqual(
                merged.splitlines(),
                [
                    "[warn] 2026-05-12 10:00:00 warn line",
                    "[error] 2026-05-12 10:00:01 error start",
                    "stack line",
                    "[info] 2026-05-12 10:00:02 info line",
                    "[debug] 2026-05-12 10:00:03 debug line",
                ],
            )

    def test_log_fetch_worker_reads_local_history_file_in_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "history.log"
            log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
            source = type("Source", (), {"path": str(log_path), "source_type": "local", "key": "history"})()
            worker = LogFetchWorker(
                DeploymentProfile(id="p1", name="demo", host="127.0.0.1", target_path="/srv/app"),
                source,
            )
            result = worker._read_local_source()
            self.assertEqual(result.text, "line1\nline2\nline3\n")
            self.assertEqual(result.local_path, str(log_path))

    def test_log_viewer_fetch_done_updates_loaded_path_and_status(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
        )
        try:
            dialog._worker_request = "info"
            dialog._on_fetch_done(
                LogFetchResult(
                    text="2026-05-12 10:00:00 hello\n2026-05-12 10:00:01 world",
                    local_path=r"C:\temp\info.log",
                    updated_at=datetime(2026, 5, 12, 10, 1, 0),
                )
            )
            self.assertEqual(dialog._last_loaded_path, r"C:\temp\info.log")
            self.assertEqual(dialog._raw_lines, ["2026-05-12 10:00:00 hello", "2026-05-12 10:00:01 world"])
            self.assertIn("已加载 2 行", dialog._status_label.text())
            self.assertIn("最后更新 10:01:00", dialog._status_label.text())
        finally:
            dialog.close()

    def test_log_viewer_close_cancels_running_fetch_state(self) -> None:
        class RunningWorkerStub:
            finished = None
            failed = None
            canceled = None
            cancel_called = False

            @staticmethod
            def isRunning() -> bool:
                return True

            def cancel(self) -> None:
                self.cancel_called = True

            def deleteLater(self) -> None:
                return None

        class SignalStub:
            def disconnect(self, _handler) -> None:
                return None

            def connect(self, _handler) -> None:
                return None

        worker = RunningWorkerStub()
        worker.finished = SignalStub()
        worker.failed = SignalStub()
        worker.canceled = SignalStub()

        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
        )
        try:
            dialog._worker = worker  # type: ignore[assignment]
            dialog._worker_request = "info"
            dialog._set_loading_state(dialog._sources["info"])

            dialog.close()

            self.assertTrue(worker.cancel_called)
            self.assertIsNone(dialog._worker)
            self.assertIsNone(dialog._worker_request)
            self.assertFalse(dialog._is_loading())
            self.assertTrue(dialog._refresh_button.isEnabled())
        finally:
            dialog.close()

    def test_profile_defaults_to_unset_kind_when_old_config_has_no_field(self) -> None:
        profile = DeploymentProfile.from_dict({"name": "legacy"})
        self.assertEqual(profile.profile_kind, PROFILE_KIND_UNSET)

    def test_profile_invalid_kind_falls_back_to_unset(self) -> None:
        profile = DeploymentProfile.from_dict({"name": "broken", "profile_kind": "java"})
        self.assertEqual(profile.profile_kind, PROFILE_KIND_UNSET)


if __name__ == "__main__":
    unittest.main()
