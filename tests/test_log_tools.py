from __future__ import annotations

import gzip
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from PySide2.QtWidgets import QApplication

from hospital_deploy_tool.constants import PROFILE_KIND_UNSET
from hospital_deploy_tool.log_history import HistoryLogCache, HistoryLogFile
from hospital_deploy_tool.log_tools import (
    BINARY_MEDICAL_RECORD_PLACEHOLDER,
    filter_log_lines,
    group_line_events,
    parse_line_timestamp,
    read_local_tail,
    read_local_text,
    replace_binary_medical_records,
    resolve_time_range,
)
from hospital_deploy_tool.models import DeploymentProfile
from hospital_deploy_tool.ui.log_aux_dialogs import LogPathConfigDialog
from hospital_deploy_tool.ui.log_workbench import LogFetchResult, LogFetchWorker, LogSource, LogViewerDialog


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

    def test_filter_log_lines_supports_aggregate_source_prefix(self) -> None:
        lines = [
            "[warn] 2026-05-12 10:00:00 warmup",
            "[error] 2026-05-12 10:00:01 target exception",
            "stack line",
            "[info] 2026-05-12 10:00:02 healthy",
        ]
        result = filter_log_lines(lines, include_keyword="target exception")
        self.assertEqual(result.matched_lines, 2)
        self.assertEqual(result.displayed_lines, 2)
        self.assertEqual(
            result.lines,
            [
                "[error] 2026-05-12 10:00:01 target exception",
                "stack line",
            ],
        )

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

    def test_replace_binary_medical_records_keeps_short_snote_titles(self) -> None:
        text = '"snote":"入院记录","stitle":"入院记录"'
        self.assertEqual(replace_binary_medical_records(text), text)

    def test_replace_binary_medical_records_replaces_xtextdocument_field(self) -> None:
        text = (
            '2026-06-26 INFO {"content":"<XTextDocument><XElements>large record</XElements></XTextDocument>",'
            '"other":"keep"}'
        )
        result = replace_binary_medical_records(text)
        self.assertIn(f'"content":"{BINARY_MEDICAL_RECORD_PLACEHOLDER}"', result)
        self.assertIn('"other":"keep"', result)
        self.assertNotIn("<XTextDocument", result)

    def test_replace_binary_medical_records_replaces_multiline_snote_value(self) -> None:
        text = '2026-06-26 INFO {"snote":"<XTextDocument>line1\nline2</XTextDocument>","scode":"1"}'
        result = replace_binary_medical_records(text)
        self.assertEqual(
            result,
            f'2026-06-26 INFO {{"snote":"{BINARY_MEDICAL_RECORD_PLACEHOLDER}","scode":"1"}}',
        )

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

    def test_log_viewer_supports_configured_debug_and_warn_log_paths(self) -> None:
        profile = DeploymentProfile(
            id="profile-1",
            name="demo",
            host="127.0.0.1",
            target_path="/srv/app",
            log_path_default="/custom/logs/info.log",
            log_path_error="/custom/logs/error.log",
            log_path_debug="/debug-area/debug.log",
            log_path_warn="/warn-area/warn.log",
        )
        dialog = LogViewerDialog(profile=profile, history=[])
        try:
            self.assertEqual(dialog._sources["info"].path, "/custom/logs/info.log")
            self.assertEqual(dialog._sources["error"].path, "/custom/logs/error.log")
            self.assertEqual(dialog._sources["debug"].path, "/debug-area/debug.log")
            self.assertEqual(dialog._sources["warn"].path, "/warn-area/warn.log")
            worker = LogFetchWorker(profile, dialog._sources["all"])
            self.assertEqual(worker._effective_remote_path("debug"), "/debug-area/debug.log")
            self.assertEqual(worker._effective_remote_path("warn"), "/warn-area/warn.log")
        finally:
            dialog.close()

    def test_log_path_config_dialog_returns_all_service_log_paths(self) -> None:
        dialog = LogPathConfigDialog(
            " /custom/logs/info.log ",
            " /custom/logs/error.log ",
            " /debug-area/debug.log ",
            " /warn-area/warn.log ",
        )
        try:
            self.assertEqual(
                dialog.get_paths(),
                (
                    "/custom/logs/info.log",
                    "/custom/logs/error.log",
                    "/debug-area/debug.log",
                    "/warn-area/warn.log",
                ),
            )
        finally:
            dialog.close()

    def test_log_viewer_derives_history_root_from_info_log_path(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(
                name="demo",
                host="127.0.0.1",
                target_path="/srv/app",
                log_path_default="/custom/logs/info.log",
            ),
            history=[],
        )
        try:
            self.assertEqual(dialog._history_root_path(), "/custom/logs/history")
        finally:
            dialog.close()

    def test_log_viewer_builds_history_source_label_and_paths(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
        )
        files = (
            HistoryLogFile("2026-06-03", "info.2026-06-03.32.log.gz", "/logs/history/2026-06-03/info.2026-06-03.32.log.gz", 10),
            HistoryLogFile("2026-06-03", "error.2026-06-03.0.log.gz", "/logs/history/2026-06-03/error.2026-06-03.0.log.gz", 20),
        )
        try:
            source = dialog._make_history_source(files)
            self.assertEqual(source.source_type, "history_remote")
            self.assertIn("历史日志 | 2026-06-03", source.label)
            self.assertIn("info x1", source.label)
            self.assertIn("error x1", source.label)
            self.assertIn(files[0].remote_path, source.path)
            self.assertEqual(source.history_files, files)
        finally:
            dialog.close()

    def test_history_log_cache_persists_dates_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache = HistoryLogCache(Path(tmp_dir), "profile-1", "demo", "/srv/app/logs/history")
            files = [
                HistoryLogFile(
                    "2026-06-03",
                    "info.2026-06-03.32.log.gz",
                    "/srv/app/logs/history/2026-06-03/info.2026-06-03.32.log.gz",
                    1024,
                    datetime(2026, 6, 3, 10, 0, 0),
                )
            ]

            cache.update_dates(["2026-06-03", "2026-06-02"])
            cache.update_files("2026-06-03", files)
            reloaded = HistoryLogCache(Path(tmp_dir), "profile-1", "demo", "/srv/app/logs/history")

            self.assertEqual(reloaded.list_dates(), ["2026-06-03", "2026-06-02"])
            self.assertEqual(reloaded.list_files("2026-06-03"), files)
            self.assertTrue(str(reloaded.archive_path(files[0])).startswith(str(Path(tmp_dir))))

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

    def test_log_viewer_replaces_binary_medical_records_by_default(self) -> None:
        dialog = LogViewerDialog(
            profile=DeploymentProfile(name="demo", host="127.0.0.1", target_path="/srv/app"),
            history=[],
        )
        try:
            dialog._raw_lines = [
                '2026-06-26 11:29:48 INFO {"snote":"<XTextDocument><XElements>large record</XElements></XTextDocument>"}'
            ]

            dialog._apply_filters()
            self.assertIn(BINARY_MEDICAL_RECORD_PLACEHOLDER, dialog._display_text)
            self.assertNotIn("<XTextDocument", dialog._display_text)

            dialog._replace_medical_record_check.setChecked(False)
            self.assertIn("<XTextDocument", dialog._display_text)
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

    def test_log_fetch_worker_downloads_and_merges_history_gzip_files(self) -> None:
        class FakeDeployer:
            @staticmethod
            def download_remote_file(remote_path: str, local_path: str) -> int:
                Path(local_path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(remote_path, local_path)
                return Path(remote_path).stat().st_size

        with tempfile.TemporaryDirectory() as tmp_dir:
            remote_dir = Path(tmp_dir) / "remote"
            cache_dir = Path(tmp_dir) / "cache"
            remote_dir.mkdir()
            info_path = remote_dir / "info.2026-06-03.32.log.gz"
            error_path = remote_dir / "error.2026-06-03.0.log.gz"
            with gzip.open(info_path, "wt", encoding="utf-8") as handle:
                handle.write("2026-06-03 10:00:02 info line\n")
            with gzip.open(error_path, "wt", encoding="utf-8") as handle:
                handle.write("2026-06-03 10:00:01 error start\nstack line\n")
            files = (
                HistoryLogFile("2026-06-03", info_path.name, str(info_path), info_path.stat().st_size),
                HistoryLogFile("2026-06-03", error_path.name, str(error_path), error_path.stat().st_size),
            )
            source = LogSource(
                "history_remote:test",
                "历史日志 | 2026-06-03",
                "\n".join(file.remote_path for file in files),
                "history_remote",
                files,
                str(remote_dir),
            )
            worker = LogFetchWorker(
                DeploymentProfile(id="p1", name="demo", host="127.0.0.1", target_path="/srv/app"),
                source,
            )
            worker._history_cache = lambda: HistoryLogCache(cache_dir, "p1", "demo", str(remote_dir))  # type: ignore[method-assign]

            result = worker._download_history_logs(FakeDeployer(), source)

            self.assertEqual(
                result.text.splitlines(),
                [
                    "[history:error.0] 2026-06-03 10:00:01 error start",
                    "stack line",
                    "[history:info.32] 2026-06-03 10:00:02 info line",
                ],
            )
            self.assertEqual(Path(result.local_path).name, "selected-history.log")

    def test_log_fetch_worker_reuses_cached_history_archive_when_size_matches(self) -> None:
        class FailingDeployer:
            @staticmethod
            def download_remote_file(_remote_path: str, _local_path: str) -> int:
                raise AssertionError("不应重复下载已缓存的历史日志")

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache = HistoryLogCache(Path(tmp_dir), "p1", "demo", "/srv/app/logs/history")
            history_file = HistoryLogFile(
                "2026-06-03",
                "info.2026-06-03.32.log.gz",
                "/srv/app/logs/history/2026-06-03/info.2026-06-03.32.log.gz",
                0,
            )
            archive_path = cache.archive_path(history_file)
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(archive_path, "wt", encoding="utf-8") as handle:
                handle.write("2026-06-03 10:00:02 cached info\n")
            history_file = HistoryLogFile(
                history_file.date,
                history_file.name,
                history_file.remote_path,
                archive_path.stat().st_size,
            )
            source = LogSource(
                "history_remote:test",
                "历史日志 | 2026-06-03",
                history_file.remote_path,
                "history_remote",
                (history_file,),
                "/srv/app/logs/history",
            )
            worker = LogFetchWorker(
                DeploymentProfile(id="p1", name="demo", host="127.0.0.1", target_path="/srv/app"),
                source,
            )
            worker._history_cache = lambda: cache  # type: ignore[method-assign]

            result = worker._download_history_logs(FailingDeployer(), source)

            self.assertIn("[history:info.32] 2026-06-03 10:00:02 cached info", result.text)

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
