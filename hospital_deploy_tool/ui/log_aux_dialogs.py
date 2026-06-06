from __future__ import annotations

import posixpath

from PySide2.QtCore import QThread, Qt, Signal
from PySide2.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..constants import get_history_log_cache_dir
from ..log_history import (
    HistoryLogCache,
    HistoryLogFile,
    format_bytes,
    history_log_kind,
    history_log_sort_key,
    is_history_date_dir,
    is_history_log_file,
)
from ..models import DeploymentProfile, HistoryRecord

_CATALOG_OPERATION_TIMEOUT_SECONDS = 20
_CATALOG_CANCEL_WAIT_MS = 3000


class _DialogNullLogger:
    def info(self, *_args) -> None:
        return None

    def warning(self, *_args) -> None:
        return None

    def error(self, *_args) -> None:
        return None

    def success(self, *_args) -> None:
        return None


class HistoryLogCatalogWorker(QThread):
    loaded = Signal(str, object)
    failed = Signal(str)
    canceled = Signal(str)

    def __init__(self, profile: DeploymentProfile, history_root_path: str, date: str = "") -> None:
        super().__init__()
        self.profile = profile
        self.history_root_path = history_root_path
        self.date = date
        self._deployer = None
        self._cancel_requested = False

    @property
    def request_key(self) -> str:
        return f"files:{self.date}" if self.date else "dates"

    def cancel(self) -> None:
        self._cancel_requested = True
        if self._deployer is not None:
            self._deployer.close()

    def run(self) -> None:
        request_key = self.request_key
        try:
            from ..remote import RemoteDeployer

            deployer = RemoteDeployer(
                self.profile,
                _DialogNullLogger(),
                operation_timeout=_CATALOG_OPERATION_TIMEOUT_SECONDS,
            )
            self._deployer = deployer
            with deployer:
                if self._cancel_requested:
                    self.canceled.emit(request_key)
                    return
                payload = self._list_files(deployer) if self.date else self._list_dates(deployer)
                if self._cancel_requested:
                    self.canceled.emit(request_key)
                    return
                self.loaded.emit(request_key, payload)
        except Exception as exc:  # noqa: BLE001
            if self._cancel_requested:
                self.canceled.emit(request_key)
                return
            self.failed.emit(str(exc))

    def _list_dates(self, deployer) -> list[str]:  # noqa: ANN001
        entries = deployer.list_remote_dir(self.history_root_path)
        dates = [entry.name for entry in entries if entry.is_dir and is_history_date_dir(entry.name)]
        return sorted(dates, reverse=True)

    def _list_files(self, deployer) -> list[HistoryLogFile]:  # noqa: ANN001
        date_path = posixpath.join(self.history_root_path.rstrip("/"), self.date)
        files: list[HistoryLogFile] = []
        for entry in deployer.list_remote_dir(date_path):
            if entry.is_dir or not is_history_log_file(entry.name):
                continue
            files.append(
                HistoryLogFile(
                    date=self.date,
                    name=entry.name,
                    remote_path=entry.path,
                    size=entry.size,
                    modified_at=entry.modified_at,
                )
            )
        return sorted(files, key=history_log_sort_key)


class HistoryLogBrowserDialog(QDialog):
    def __init__(
        self,
        profile: DeploymentProfile,
        history_root_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.history_root_path = history_root_path
        self._cache = HistoryLogCache(get_history_log_cache_dir(), profile.id, profile.name, history_root_path)
        self._worker: HistoryLogCatalogWorker | None = None
        self._files: list[HistoryLogFile] = []
        self._checked_paths: set[str] = set()
        self.setWindowTitle("历史日志")
        self.resize(980, 620)
        self._build_layout()
        self._load_cached_dates_or_sync()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        self._root_label = QLabel(f"目录: {self.history_root_path}", self)
        self._root_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._root_label)

        content = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("日期", self))
        self._date_list = QListWidget(self)
        self._date_list.itemSelectionChanged.connect(self._on_date_changed)
        left.addWidget(self._date_list, 1)
        content.addLayout(left, 1)

        right = QVBoxLayout()
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("文件", self))
        self._file_filter_edit = QLineEdit(self)
        self._file_filter_edit.setPlaceholderText("按文件名筛选")
        self._file_filter_edit.textChanged.connect(self._populate_file_rows)
        filter_row.addWidget(self._file_filter_edit, 1)
        right.addLayout(filter_row)

        self._file_table = QTableWidget(0, 4, self)
        self._file_table.setHorizontalHeaderLabels(["文件名", "类型", "大小", "修改时间"])
        self._file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._file_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._file_table.itemChanged.connect(self._on_file_item_changed)
        right.addWidget(self._file_table, 1)
        content.addLayout(right, 3)
        layout.addLayout(content, 1)

        action_row = QHBoxLayout()
        self._status_label = QLabel("正在读取历史日志目录...", self)
        self._status_label.setProperty("role", "muted")
        self._refresh_button = QPushButton("同步日期", self)
        self._refresh_button.clicked.connect(self._sync_remote_dates)
        self._sync_files_button = QPushButton("同步文件", self)
        self._sync_files_button.clicked.connect(self._sync_current_date_files)
        self._select_visible_button = QPushButton("全选可见", self)
        self._select_visible_button.clicked.connect(self._select_visible_files)
        self._clear_button = QPushButton("清空选择", self)
        self._clear_button.clicked.connect(self._clear_selection)
        self._load_button = QPushButton("加载选中文件", self)
        self._load_button.clicked.connect(self.accept)
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        action_row.addWidget(self._status_label, 1)
        action_row.addWidget(self._refresh_button)
        action_row.addWidget(self._sync_files_button)
        action_row.addWidget(self._select_visible_button)
        action_row.addWidget(self._clear_button)
        action_row.addWidget(self._load_button)
        action_row.addWidget(cancel)
        layout.addLayout(action_row)

    def _load_cached_dates_or_sync(self) -> None:
        try:
            dates = self._cache.list_dates()
        except RuntimeError as exc:
            QMessageBox.warning(self, "历史日志缓存", str(exc))
            dates = []
        if dates:
            self._populate_dates(dates, f"已从本地缓存读取 {len(dates)} 个日期目录")
            return
        self._sync_remote_dates()

    def _sync_current_date_files(self) -> None:
        date = self._current_date()
        if date:
            self._sync_remote_files(date)

    def _sync_remote_dates(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._files = []
        self._checked_paths.clear()
        self._date_list.clear()
        self._file_table.setRowCount(0)
        self._set_busy(True, "正在同步远端历史日志日期...")
        self._start_worker("")

    def _load_files(self, date: str) -> None:
        try:
            cached_files = self._cache.list_files(date)
        except RuntimeError as exc:
            QMessageBox.warning(self, "历史日志缓存", str(exc))
            cached_files = []
        if cached_files:
            self._files = cached_files
            self._checked_paths.clear()
            self._populate_file_rows()
            self._set_busy(False, f"{date} 已从本地缓存读取 {len(self._files)} 个历史日志文件")
            return
        self._sync_remote_files(date)

    def _sync_remote_files(self, date: str) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._files = []
        self._checked_paths.clear()
        self._file_table.setRowCount(0)
        self._set_busy(True, f"正在同步 {date} 的历史日志文件...")
        self._start_worker(date)

    def _start_worker(self, date: str) -> None:
        worker = HistoryLogCatalogWorker(self.profile, self.history_root_path, date)
        worker.loaded.connect(self._on_worker_loaded)
        worker.failed.connect(self._on_worker_failed)
        worker.canceled.connect(self._on_worker_canceled)
        self._worker = worker
        worker.start()

    def _on_worker_loaded(self, request_key: str, payload: object) -> None:
        self._finish_worker()
        if request_key == "dates":
            dates = list(payload)
            self._cache.update_dates(dates)
            self._populate_dates(self._cache.list_dates(), f"已同步 {len(dates)} 个远端日期目录")
            return
        date = request_key.removeprefix("files:")
        if date != self._current_date():
            self._set_busy(False, "已忽略过期的历史日志同步结果")
            return
        self._cache.update_files(date, list(payload))
        self._files = self._cache.list_files(date)
        self._populate_file_rows()
        self._set_busy(False, f"{date} 已同步 {len(self._files)} 个历史日志文件")

    def _on_worker_failed(self, error: str) -> None:
        self._finish_worker()
        self._set_busy(False, "读取失败")
        QMessageBox.critical(self, "历史日志", error)

    def _on_worker_canceled(self, _request_key: str) -> None:
        self._finish_worker()
        self._set_busy(False, "已取消读取历史日志")

    def _finish_worker(self) -> None:
        worker = self._worker
        if worker is None:
            return
        if worker.isRunning() and not worker.wait(_CATALOG_CANCEL_WAIT_MS):
            return
        self._worker = None
        worker.deleteLater()

    def _populate_dates(self, dates: list[str], message: str) -> None:
        previous_date = self._current_date()
        self._date_list.clear()
        for date in dates:
            self._date_list.addItem(QListWidgetItem(date))
        if dates:
            self._set_busy(False, message)
            preferred_row = dates.index(previous_date) if previous_date in dates else 0
            self._date_list.setCurrentRow(preferred_row)
            return
        self._set_busy(False, "没有找到历史日志日期目录")

    def _populate_file_rows(self) -> None:
        keyword = self._file_filter_edit.text().strip().lower()
        visible_files = [file for file in self._files if not keyword or keyword in file.name.lower()]
        self._file_table.blockSignals(True)
        self._file_table.setRowCount(len(visible_files))
        for row, file in enumerate(visible_files):
            name_item = QTableWidgetItem(file.name)
            name_item.setCheckState(Qt.Checked if file.remote_path in self._checked_paths else Qt.Unchecked)
            name_item.setData(Qt.UserRole, file)
            kind_item = QTableWidgetItem(history_log_kind(file.name))
            size_item = QTableWidgetItem(format_bytes(file.size))
            modified = file.modified_at.strftime("%Y-%m-%d %H:%M:%S") if file.modified_at else "-"
            modified_item = QTableWidgetItem(modified)
            for item in (name_item, kind_item, size_item, modified_item):
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._file_table.setItem(row, 0, name_item)
            self._file_table.setItem(row, 1, kind_item)
            self._file_table.setItem(row, 2, size_item)
            self._file_table.setItem(row, 3, modified_item)
        self._file_table.blockSignals(False)
        self._update_selection_status()

    def _on_file_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        file = item.data(Qt.UserRole)
        if not isinstance(file, HistoryLogFile):
            return
        if item.checkState() == Qt.Checked:
            self._checked_paths.add(file.remote_path)
        else:
            self._checked_paths.discard(file.remote_path)
        self._update_selection_status()

    def _select_visible_files(self) -> None:
        self._file_table.blockSignals(True)
        for row in range(self._file_table.rowCount()):
            item = self._file_table.item(row, 0)
            file = item.data(Qt.UserRole)
            if isinstance(file, HistoryLogFile):
                self._checked_paths.add(file.remote_path)
                item.setCheckState(Qt.Checked)
        self._file_table.blockSignals(False)
        self._update_selection_status()

    def _clear_selection(self) -> None:
        self._checked_paths.clear()
        self._populate_file_rows()

    def _selected_files(self) -> list[HistoryLogFile]:
        selected = [file for file in self._files if file.remote_path in self._checked_paths]
        return sorted(selected, key=history_log_sort_key)

    def selected_files(self) -> tuple[HistoryLogFile, ...]:
        return tuple(self._selected_files())

    def accept(self) -> None:
        if not self._selected_files():
            QMessageBox.information(self, "历史日志", "请先选择至少一个历史日志文件。")
            return
        super().accept()

    def _on_date_changed(self) -> None:
        date = self._current_date()
        if date:
            self._load_files(date)

    def _current_date(self) -> str:
        items = self._date_list.selectedItems()
        return items[0].text() if items else ""

    def _set_busy(self, busy: bool, message: str) -> None:
        self._date_list.setEnabled(not busy)
        self._file_table.setEnabled(not busy)
        self._file_filter_edit.setEnabled(not busy)
        self._refresh_button.setEnabled(not busy)
        self._sync_files_button.setEnabled(not busy and bool(self._current_date()))
        self._select_visible_button.setEnabled(not busy)
        self._clear_button.setEnabled(not busy)
        self._load_button.setEnabled(not busy)
        self._status_label.setText(message)

    def _update_selection_status(self) -> None:
        selected = self._selected_files()
        selected_size = sum(file.size for file in selected)
        if selected:
            self._status_label.setText(f"已选择 {len(selected)} 个文件，压缩大小 {format_bytes(selected_size)}")
            return
        if self._files:
            self._status_label.setText(f"当前日期共 {len(self._files)} 个历史日志文件")

    def closeEvent(self, event) -> None:  # noqa: ANN001
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            if not self._worker.wait(_CATALOG_CANCEL_WAIT_MS):
                event.ignore()
                self._status_label.setText("正在取消远程读取，请稍候...")
                return
            self._worker.deleteLater()
            self._worker = None
        super().closeEvent(event)


class HistoryDialog(QDialog):
    open_log_requested = Signal(object)

    def __init__(self, history: list[HistoryRecord], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.history = history
        self.setWindowTitle("执行历史")
        self.resize(1080, 560)
        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["开始时间", "Profile", "动作", "主机", "目标路径", "结果", "耗时"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self.fill_details)
        self.table.itemDoubleClicked.connect(lambda *_args: self.open_selected_log())
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.open_button = QPushButton("打开日志", self)
        self.open_button.clicked.connect(self.open_selected_log)
        self.close_button = QPushButton("关闭", self)
        self.close_button.clicked.connect(self.accept)
        self.build_layout()
        self.load_rows(history)

    def build_layout(self) -> None:
        right = QVBoxLayout()
        right.addWidget(QLabel("执行详情", self))
        right.addWidget(self.details, 1)

        content = QHBoxLayout()
        content.addWidget(self.table, 3)
        right_panel = QWidget(self)
        right_panel.setLayout(right)
        content.addWidget(right_panel, 2)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(content)
        layout.addLayout(buttons)

    def load_rows(self, history: list[HistoryRecord]) -> None:
        self.history = history
        self.table.setRowCount(len(history))
        for row, record in enumerate(history):
            values = [
                record.started_at,
                record.profile_name,
                record.action,
                record.host,
                record.target_path,
                "成功" if record.success else "失败",
                f"{record.duration_seconds:.2f}s",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, record.id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.open_button.setEnabled(bool(history))
        if history:
            self.table.selectRow(0)
            return
        self.details.clear()

    def selected_history(self) -> HistoryRecord | None:
        items = self.table.selectedItems()
        if not items:
            return None
        history_id = items[0].data(Qt.UserRole)
        for record in self.history:
            if record.id == history_id:
                return record
        return None

    def fill_details(self) -> None:
        record = self.selected_history()
        if record is None:
            self.details.clear()
            self.open_button.setEnabled(False)
            return
        self.open_button.setEnabled(bool(record.log_file))
        lines = [
            f"开始时间: {record.started_at}",
            f"结束时间: {record.ended_at}",
            f"动作: {record.action}",
            f"Profile: {record.profile_name}",
            f"主机: {record.host}",
            f"源路径: {record.source_path}",
            f"目标路径: {record.target_path}",
            f"结果: {'成功' if record.success else '失败'}",
            f"耗时: {record.duration_seconds:.2f}s",
            f"日志文件: {record.log_file}",
            f"摘要: {record.summary}",
        ]
        self.details.setPlainText("\n".join(lines))

    def open_selected_log(self) -> None:
        record = self.selected_history()
        if record is None or not record.log_file:
            QMessageBox.information(self, "打开日志", "当前记录没有可打开的日志文件。")
            return
        self.open_log_requested.emit(record)
        self.accept()


class LogPathConfigDialog(QDialog):
    def __init__(
        self,
        default_path: str,
        error_path: str,
        debug_path: str,
        warn_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("配置日志路径")
        self.setFixedWidth(420)
        form = QFormLayout(self)
        self._default_edit = QLineEdit(default_path, self)
        self._error_edit = QLineEdit(error_path, self)
        self._debug_edit = QLineEdit(debug_path, self)
        self._warn_edit = QLineEdit(warn_path, self)
        form.addRow("info.log", self._default_edit)
        form.addRow("error.log", self._error_edit)
        form.addRow("debug.log", self._debug_edit)
        form.addRow("warn.log", self._warn_edit)
        buttons = QHBoxLayout()
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存", self)
        save.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        form.addRow("", self._wrap(buttons))

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        widget = QWidget(self)
        widget.setLayout(layout)
        return widget

    def get_paths(self) -> tuple[str, str, str, str]:
        return (
            self._default_edit.text().strip(),
            self._error_edit.text().strip(),
            self._debug_edit.text().strip(),
            self._warn_edit.text().strip(),
        )
