from __future__ import annotations

import posixpath
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide2.QtCore import QDateTime, QSettings, Qt, QThread, Signal
from PySide2.QtGui import QFont, QTextCursor
from PySide2.QtWidgets import (
    QApplication,
    QCheckBox,
    QButtonGroup,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..constants import APP_NAME
from ..log_tools import FilteredLogResult, filter_log_lines, read_local_tail, resolve_time_range
from ..models import DeploymentProfile, HistoryRecord
from .log_aux_dialogs import LogPathConfigDialog

_SETTINGS_GROUP = "log_workbench"
_GEOMETRY_KEY = "geometry"
_DEFAULT_LINES = 1000
_LOAD_MORE_STEP = 1000
_MAX_LINES = 20000
_SERVICE_LOG_SPECS = (
    ("info", "info.log"),
    ("error", "error.log"),
    ("debug", "debug.log"),
    ("warn", "warn.log"),
)


@dataclass(frozen=True, slots=True)
class LogSource:
    key: str
    label: str
    path: str
    source_type: str


class _NullLogger:
    def info(self, *_args) -> None:
        return None

    def warning(self, *_args) -> None:
        return None

    def error(self, *_args) -> None:
        return None

    def success(self, *_args) -> None:
        return None


class LogFetchWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, profile: DeploymentProfile, source: LogSource, line_limit: int) -> None:
        super().__init__()
        self.profile = profile
        self.source = source
        self.line_limit = line_limit

    def run(self) -> None:
        try:
            if self.source.source_type == "local":
                text = read_local_tail(self.source.path, self.line_limit)
            else:
                text = self._read_remote_tail()
            self.finished.emit(text)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _read_remote_tail(self) -> str:
        from ..remote import RemoteDeployer

        with RemoteDeployer(self.profile, _NullLogger()) as deployer:
            return deployer.read_remote_log(self.source.path, lines=self.line_limit)


class LogViewerDialog(QDialog):
    config_saved = Signal(str, str, str)

    def __init__(
        self,
        profile: DeploymentProfile,
        history: list[HistoryRecord],
        current_log_file: str = "",
        initial_log_file: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.history = history
        self.current_log_file = current_log_file
        self.initial_log_file = initial_log_file
        self._sources: dict[str, LogSource] = {}
        self._source_buttons: dict[str, QPushButton] = {}
        self._source_button_group: QButtonGroup | None = None
        self._direct_source: LogSource | None = None
        self._worker: LogFetchWorker | None = None
        self._raw_lines: list[str] = []
        self._display_text = ""
        self._last_result = FilteredLogResult([], 0, 0, 0, 0)
        self._worker_request: tuple[str, int] | None = None
        self.setWindowTitle(f"日志工作台 - {profile.name} @ {profile.host}")
        self.setWindowFlag(Qt.Window, True)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
        self.setWindowModality(Qt.NonModal)
        self.resize(1320, 820)
        self._build_ui()
        self._restore_geometry()
        self.refresh_context(profile, history, current_log_file, initial_log_file, auto_fetch=False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addLayout(self._build_source_bar())
        layout.addLayout(self._build_filter_bar())
        layout.addLayout(self._build_time_bar())
        layout.addLayout(self._build_action_bar())
        self._log_area = QPlainTextEdit(self)
        self._log_area.setReadOnly(True)
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.Monospace)
        self._log_area.setFont(font)
        layout.addWidget(self._log_area, 1)
        self._status_label = QLabel("就绪", self)
        self._status_label.setProperty("role", "muted")
        layout.addWidget(self._status_label)

    def _build_source_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._source_button_group = QButtonGroup(self)
        self._source_button_group.setExclusive(True)
        self._path_label = QLabel("-", self)
        self._path_label.setProperty("role", "muted")
        self._path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(QLabel("日志来源", self))
        for key, filename in _SERVICE_LOG_SPECS:
            button = QPushButton(filename, self)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, source_key=key: self._on_source_button_clicked(source_key))
            self._source_button_group.addButton(button)
            self._source_buttons[key] = button
            row.addWidget(button)
        row.addWidget(self._path_label, 5)
        return row

    def _build_filter_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._include_edit = QLineEdit(self)
        self._include_edit.setPlaceholderText("包含关键字")
        self._exclude_edit = QLineEdit(self)
        self._exclude_edit.setPlaceholderText("排除关键字")
        self._trace_id_edit = QLineEdit(self)
        self._trace_id_edit.setPlaceholderText("traceId")
        self._case_check = QCheckBox("区分大小写", self)
        self._context_spin = QSpinBox(self)
        self._context_spin.setRange(0, 20)
        self._context_spin.setValue(0)
        self._unescape_newline_check = QCheckBox("还原转义换行", self)
        self._unescape_newline_check.setChecked(True)
        self._unescape_newline_check.setToolTip("将日志中的 \\r\\n 与 \\n 显示为真实换行，便于查看多行 SQL")
        row.addWidget(QLabel("筛选", self))
        row.addWidget(self._include_edit, 2)
        row.addWidget(self._exclude_edit, 2)
        row.addWidget(self._trace_id_edit, 2)
        row.addWidget(self._case_check)
        row.addWidget(QLabel("上下文", self))
        row.addWidget(self._context_spin)
        row.addWidget(self._unescape_newline_check)
        self._include_edit.textChanged.connect(self._apply_filters)
        self._exclude_edit.textChanged.connect(self._apply_filters)
        self._trace_id_edit.textChanged.connect(self._apply_filters)
        self._case_check.toggled.connect(self._apply_filters)
        self._context_spin.valueChanged.connect(self._apply_filters)
        self._unescape_newline_check.toggled.connect(self._apply_filters)
        return row

    def _build_time_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._range_combo = QComboBox(self)
        self._range_combo.addItem("全部", "all")
        self._range_combo.addItem("最近 10 分钟", "10m")
        self._range_combo.addItem("最近 30 分钟", "30m")
        self._range_combo.addItem("最近 1 小时", "1h")
        self._range_combo.addItem("今天", "today")
        self._range_combo.addItem("自定义", "custom")
        now = QDateTime.currentDateTime()
        self._custom_start_time = now.addSecs(-3600).toPython()
        self._custom_end_time = now.toPython()
        self._start_edit = QDateTimeEdit(now.addSecs(-3600), self)
        self._end_edit = QDateTimeEdit(now, self)
        for control in (self._start_edit, self._end_edit):
            control.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            control.setCalendarPopup(True)
        self._range_combo.currentIndexChanged.connect(self._on_time_mode_changed)
        self._start_edit.dateTimeChanged.connect(self._on_custom_time_changed)
        self._end_edit.dateTimeChanged.connect(self._on_custom_time_changed)
        row.addWidget(QLabel("时间范围", self))
        row.addWidget(self._range_combo)
        row.addWidget(QLabel("开始", self))
        row.addWidget(self._start_edit)
        row.addWidget(QLabel("结束", self))
        row.addWidget(self._end_edit)
        row.addStretch(1)
        self._on_time_mode_changed()
        return row

    def _build_action_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._line_limit_spin = QSpinBox(self)
        self._line_limit_spin.setRange(100, _MAX_LINES)
        self._line_limit_spin.setSingleStep(100)
        self._line_limit_spin.setValue(_DEFAULT_LINES)
        self._refresh_button = QPushButton("刷新", self)
        self._refresh_button.setProperty("role", "secondary")
        self._refresh_button.clicked.connect(self._fetch_current)
        self._load_more_button = QPushButton("加载更多", self)
        self._load_more_button.setProperty("role", "secondary")
        self._load_more_button.clicked.connect(self._load_more)
        self._jump_button = QPushButton("跳到最新", self)
        self._jump_button.clicked.connect(self._jump_to_latest)
        self._copy_button = QPushButton("复制结果", self)
        self._copy_button.clicked.connect(self._copy_filtered_text)
        self._export_button = QPushButton("导出结果", self)
        self._export_button.clicked.connect(self._export_filtered_text)
        self._config_button = QPushButton("配置路径", self)
        self._config_button.setProperty("role", "muted")
        self._config_button.clicked.connect(self._open_config)
        self._close_button = QPushButton("关闭", self)
        self._close_button.clicked.connect(self.close)
        row.addWidget(QLabel("读取行数", self))
        row.addWidget(self._line_limit_spin)
        row.addWidget(self._refresh_button)
        row.addWidget(self._load_more_button)
        row.addWidget(self._jump_button)
        row.addWidget(self._copy_button)
        row.addWidget(self._export_button)
        row.addStretch(1)
        row.addWidget(self._config_button)
        row.addWidget(self._close_button)
        self._line_limit_spin.valueChanged.connect(self._fetch_current)
        return row

    def refresh_context(
        self,
        profile: DeploymentProfile,
        history: list[HistoryRecord],
        current_log_file: str = "",
        initial_log_file: str = "",
        auto_fetch: bool = True,
    ) -> None:
        self.profile = profile
        self.history = history
        self.current_log_file = current_log_file
        self.initial_log_file = initial_log_file
        self._direct_source = self._make_direct_source(initial_log_file)
        selected_key = self._current_source_key()
        self._sources = self._build_sources()
        self._reload_source_buttons(selected_key)
        if auto_fetch:
            self._fetch_current()

    def _build_sources(self) -> dict[str, LogSource]:
        return {
            key: LogSource(key, f"服务日志 | {filename}", self._effective_remote_path(key), "remote")
            for key, filename in _SERVICE_LOG_SPECS
        }

    def _make_direct_source(self, path: str) -> LogSource | None:
        if not path:
            return None
        return LogSource(f"history:{path}", f"历史日志 | {self._path_name(path)}", path, "local")

    def _reload_source_buttons(self, selected_key: str | None) -> None:
        preferred_key = self._resolve_preferred_key(selected_key)
        if self._direct_source is not None:
            preferred_key = None
        for key, button in self._source_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == preferred_key)
            button.blockSignals(False)
        self._update_source_caption()

    def _resolve_preferred_key(self, selected_key: str | None) -> str | None:
        if self._direct_source is not None:
            return None
        for candidate in (selected_key, "info", "error", "debug", "warn"):
            if not candidate:
                continue
            if candidate in self._sources:
                return candidate
        return next(iter(self._sources), None)

    def _current_source_key(self) -> str | None:
        if self._direct_source is not None:
            return self._direct_source.key
        for key, button in self._source_buttons.items():
            if button.isChecked():
                return key
        return None

    def _current_source(self) -> LogSource | None:
        if self._direct_source is not None:
            return self._direct_source
        key = self._current_source_key()
        return self._sources.get(key) if key else None

    def _current_request(self) -> tuple[str, int] | None:
        source = self._current_source()
        if source is None:
            return None
        return source.key, self._line_limit_spin.value()

    def _on_source_button_clicked(self, source_key: str) -> None:
        self._direct_source = None
        self._update_source_caption()
        self._fetch_current()

    def _update_source_caption(self) -> None:
        source = self._current_source()
        self._path_label.setText(source.path if source and source.path else "当前没有可读取的日志来源")
        is_remote = bool(source and source.source_type == "remote")
        self._config_button.setEnabled(is_remote)

    def _effective_remote_path(self, kind: str) -> str:
        base = self.profile.target_path.rstrip("/")
        if kind == "info":
            if self.profile.log_path_default:
                return self._service_log_path_from_config(self.profile.log_path_default, "info.log")
            return f"{base}/logs/info.log" if base else ""
        if kind == "error":
            if self.profile.log_path_error:
                return self._service_log_path_from_config(self.profile.log_path_error, "error.log")
            return f"{base}/logs/error.log" if base else ""
        if kind in {"debug", "warn"}:
            default_path = self._effective_remote_path("info")
            if default_path:
                return self._sibling_log_path(default_path, f"{kind}.log")
            return f"{base}/logs/{kind}.log" if base else ""
        return ""

    def _fetch_current(self) -> None:
        source = self._current_source()
        if source is None or not source.path:
            self._set_empty_state("当前没有可读取的日志来源")
            return
        request = self._current_request()
        if request is None:
            self._set_empty_state("当前没有可读取的日志来源")
            return
        if self._worker and self._worker.isRunning():
            if self._worker_request != request:
                self._status_label.setText("已切换日志来源，当前加载完成后自动刷新")
                self._set_loading_state(source)
            return
        self._status_label.setText("加载中...")
        self._set_loading_state(source)
        self._set_fetch_buttons(False)
        self._worker_request = request
        self._worker = LogFetchWorker(self.profile, source, self._line_limit_spin.value())
        self._worker.finished.connect(self._on_fetch_done)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.start()

    def _set_fetch_buttons(self, enabled: bool) -> None:
        self._refresh_button.setEnabled(enabled)
        self._load_more_button.setEnabled(enabled)
        self._line_limit_spin.setEnabled(enabled)

    def _on_fetch_done(self, text: str) -> None:
        finished_request = self._worker_request
        self._worker = None
        self._worker_request = None
        if self._should_refetch_after_current_worker(finished_request):
            self._set_fetch_buttons(True)
            self._status_label.setText("加载中...")
            self._fetch_current()
            return
        self._raw_lines = text.splitlines()
        self._apply_filters()
        self._set_fetch_buttons(True)
        self.initial_log_file = ""

    def _on_fetch_failed(self, error: str) -> None:
        finished_request = self._worker_request
        self._worker = None
        self._worker_request = None
        if self._should_refetch_after_current_worker(finished_request):
            self._set_fetch_buttons(True)
            self._status_label.setText("加载中...")
            self._fetch_current()
            return
        self._raw_lines = []
        self._display_text = f"[错误] {error}"
        self._log_area.setPlainText(self._display_text)
        self._status_label.setText("加载失败")
        self._set_fetch_buttons(True)

    def _apply_filters(self) -> None:
        start_time, end_time = self._refresh_time_range_display()
        if not self._raw_lines:
            if not self._display_text.startswith("[错误]"):
                self._set_empty_state("当前日志没有内容")
            return
        self._last_result = filter_log_lines(
            self._raw_lines,
            include_keyword=self._include_edit.text(),
            exclude_keyword=self._exclude_edit.text(),
            trace_id_keyword=self._trace_id_edit.text(),
            case_sensitive=self._case_check.isChecked(),
            start_time=start_time,
            end_time=end_time,
            context_lines=self._context_spin.value(),
        )
        self._display_text = "\n".join(self._prepare_display_lines(self._last_result.lines))
        self._log_area.setPlainText(self._display_text)
        self._update_status(start_time, end_time)

    def _resolve_active_range(self) -> tuple[datetime | None, datetime | None]:
        mode = str(self._range_combo.currentData())
        return resolve_time_range(mode, self._custom_start_time, self._custom_end_time)

    def _refresh_time_range_display(self) -> tuple[datetime | None, datetime | None]:
        start_time, end_time = self._resolve_active_range()
        self._sync_time_editors(start_time, end_time)
        return start_time, end_time

    def _sync_time_editors(self, start_time: datetime | None, end_time: datetime | None) -> None:
        mode = str(self._range_combo.currentData())
        if mode == "all":
            return
        if mode == "custom":
            start_value = self._custom_start_time
            end_value = self._custom_end_time
        else:
            start_value = start_time
            end_value = end_time
        self._set_time_editor_value(self._start_edit, start_value)
        self._set_time_editor_value(self._end_edit, end_value)

    def _update_status(self, start_time: datetime | None, end_time: datetime | None) -> None:
        loaded = len(self._raw_lines)
        matched = self._last_result.matched_lines
        displayed = self._last_result.displayed_lines
        parts = [f"已加载 {loaded} 行", f"命中 {matched} 行", f"显示 {displayed} 行"]
        if start_time or end_time:
            parts.append(f"无时间戳跳过 {self._last_result.skipped_without_time} 行")
        parts.append(f"最后更新 {datetime.now().strftime('%H:%M:%S')}")
        self._status_label.setText(" | ".join(parts))
        self._jump_to_latest()

    def _prepare_display_lines(self, lines: list[str]) -> list[str]:
        if not self._unescape_newline_check.isChecked():
            return lines
        return [self._restore_escaped_line_breaks(line) for line in lines]

    @staticmethod
    def _restore_escaped_line_breaks(line: str) -> str:
        restored = line.replace("\\r\\n", "\n")
        restored = restored.replace("\\n", "\n")
        return restored.replace("\\r", "\n")

    def _set_empty_state(self, text: str) -> None:
        self._display_text = text
        self._last_result = FilteredLogResult([], 0, 0, 0, 0)
        self._log_area.setPlainText(text)
        self._status_label.setText(text)

    def _set_loading_state(self, source: LogSource) -> None:
        message = f"正在加载 {source.label}（最近 {self._line_limit_spin.value()} 行）..."
        self._status_label.setText(message)
        if not self._raw_lines:
            self._last_result = FilteredLogResult([], 0, 0, 0, 0)
            self._display_text = message
            self._log_area.setPlainText(self._display_text)

    def _load_more(self) -> None:
        next_value = min(_MAX_LINES, self._line_limit_spin.value() + _LOAD_MORE_STEP)
        if next_value == self._line_limit_spin.value():
            return
        self._line_limit_spin.setValue(next_value)

    def _jump_to_latest(self) -> None:
        cursor = self._log_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._log_area.setTextCursor(cursor)

    def _copy_filtered_text(self) -> None:
        if not self._display_text:
            QMessageBox.information(self, "复制结果", "当前没有可复制的内容。")
            return
        QApplication.clipboard().setText(self._display_text)
        self._status_label.setText("已复制当前结果")

    def _export_filtered_text(self) -> None:
        if not self._display_text:
            QMessageBox.information(self, "导出结果", "当前没有可导出的内容。")
            return
        name = self._path_name(self._current_source().path if self._current_source() else "")
        default_name = name or "filtered.log"
        path, _ = QFileDialog.getSaveFileName(self, "导出结果", default_name)
        if not path:
            return
        Path(path).write_text(self._display_text, encoding="utf-8")
        self._status_label.setText(f"已导出到 {path}")

    def _open_config(self) -> None:
        dialog = LogPathConfigDialog(
            self.profile.log_path_default or self._effective_remote_path("info"),
            self.profile.log_path_error or self._effective_remote_path("error"),
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        default_path, error_path = dialog.get_paths()
        self.profile.log_path_default = default_path
        self.profile.log_path_error = error_path
        self.config_saved.emit(self.profile.id, default_path, error_path)
        self.refresh_context(
            self.profile,
            self.history,
            self.current_log_file,
            initial_log_file="",
            auto_fetch=True,
        )

    def _on_time_mode_changed(self) -> None:
        enabled = str(self._range_combo.currentData()) == "custom"
        self._start_edit.setEnabled(enabled)
        self._end_edit.setEnabled(enabled)
        self._refresh_time_range_display()
        if not hasattr(self, "_log_area"):
            return
        self._apply_filters()

    def _on_custom_time_changed(self) -> None:
        if str(self._range_combo.currentData()) == "custom":
            self._custom_start_time = self._start_edit.dateTime().toPython()
            self._custom_end_time = self._end_edit.dateTime().toPython()
        self._apply_filters()

    def _should_refetch_after_current_worker(self, finished_request: tuple[str, int] | None) -> bool:
        if finished_request is None:
            return False
        current_request = self._current_request()
        return current_request is not None and current_request != finished_request

    @staticmethod
    def _set_time_editor_value(control: QDateTimeEdit, value: datetime | None) -> None:
        if value is None:
            return
        normalized = value.replace(microsecond=0)
        if control.dateTime().toPython().replace(microsecond=0) == normalized:
            return
        control.blockSignals(True)
        control.setDateTime(QDateTime(normalized))
        control.blockSignals(False)

    def _restore_geometry(self) -> None:
        settings = QSettings(APP_NAME, APP_NAME)
        settings.beginGroup(_SETTINGS_GROUP)
        geometry = settings.value(_GEOMETRY_KEY)
        settings.endGroup()
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event) -> None:  # noqa: ANN001
        settings = QSettings(APP_NAME, APP_NAME)
        settings.beginGroup(_SETTINGS_GROUP)
        settings.setValue(_GEOMETRY_KEY, self.saveGeometry())
        settings.endGroup()
        super().closeEvent(event)

    @staticmethod
    def _path_name(path: str) -> str:
        return Path(path).name if path else "-"

    @staticmethod
    def _sibling_log_path(path: str, filename: str) -> str:
        parent = posixpath.dirname(path.rstrip("/"))
        if not parent:
            return filename
        return posixpath.join(parent, filename)

    @classmethod
    def _service_log_path_from_config(cls, path: str, filename: str) -> str:
        basename = posixpath.basename(path.strip())
        if basename == "default.log":
            return cls._sibling_log_path(path, filename)
        return path
