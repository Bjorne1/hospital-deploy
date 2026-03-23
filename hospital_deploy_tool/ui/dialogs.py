from __future__ import annotations

from datetime import datetime

from PySide2.QtCore import Qt, QThread, Signal
from PySide2.QtGui import QFont, QTextCursor
from PySide2.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import BackupRecord, DeploymentProfile, HistoryRecord


class BackupDialog(QDialog):
    restore_requested = Signal(str, bool)
    delete_requested = Signal(str)
    refresh_requested = Signal()
    metadata_save_requested = Signal(object)

    def __init__(self, backups: list[BackupRecord], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backups = backups
        self.setWindowTitle("备份管理")
        self.resize(1180, 620)
        self.table = QTableWidget(0, 8, self)
        self.table.setHorizontalHeaderLabels(
            ["收藏", "时间", "名称", "描述", "主机", "目标路径", "类型", "大小"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self.fill_details)
        self.name_edit = QLineEdit(self)
        self.favorite_check = QCheckBox("收藏此备份（不自动清理）", self)
        self.description_edit = QPlainTextEdit(self)
        self.description_edit.setMaximumHeight(100)
        self.save_meta_button = QPushButton("保存名称/描述", self)
        self.save_meta_button.clicked.connect(self.on_save_metadata)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.status = QLabel(self)
        self.refresh_button = QPushButton("刷新", self)
        self.restore_button = QPushButton("恢复选中备份", self)
        self.delete_button = QPushButton("删除记录", self)
        self.close_button = QPushButton("关闭", self)
        self.restore_commands_check = QCheckBox("恢复后执行当前配置中的后置命令", self)
        self.refresh_button.clicked.connect(lambda: self.refresh_requested.emit())
        self.restore_button.clicked.connect(self.on_restore)
        self.delete_button.clicked.connect(self.on_delete)
        self.close_button.clicked.connect(self.accept)
        self.build_layout()
        self.load_rows(backups)

    def build_layout(self) -> None:
        button_bar = QHBoxLayout()
        button_bar.addWidget(self.status)
        button_bar.addStretch(1)
        button_bar.addWidget(self.restore_commands_check)
        button_bar.addWidget(self.refresh_button)
        button_bar.addWidget(self.restore_button)
        button_bar.addWidget(self.delete_button)
        button_bar.addWidget(self.close_button)

        right = QVBoxLayout()
        right.addWidget(QLabel("备份名称", self))
        right.addWidget(self.name_edit)
        right.addWidget(self.favorite_check)
        right.addWidget(QLabel("描述", self))
        right.addWidget(self.description_edit)
        right.addWidget(self.save_meta_button)
        right.addWidget(QLabel("备份详情", self))
        right.addWidget(self.details, 1)

        content = QHBoxLayout()
        content.addWidget(self.table, 3)
        right_panel = QWidget(self)
        right_panel.setLayout(right)
        content.addWidget(right_panel, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(content)
        layout.addLayout(button_bar)

    def load_rows(self, backups: list[BackupRecord], selected_backup_id: str | None = None) -> None:
        self.backups = backups
        self.table.setRowCount(len(backups))
        for row, record in enumerate(backups):
            values = [
                "是" if record.favorite else "",
                record.created_at,
                record.name,
                self.short_description(record.description),
                record.host,
                record.target_path,
                record.source_type,
                self.format_size(record.backup_size),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, record.id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.status.setText(f"共 {len(backups)} 条备份记录")
        self.set_editor_enabled(bool(backups))
        if not backups:
            self.clear_details()
            return
        selected_id = selected_backup_id or backups[0].id
        for row in range(len(backups)):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == selected_id:
                self.table.selectRow(row)
                return
        self.table.selectRow(0)

    def selected_backup_id(self) -> str | None:
        items = self.table.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.UserRole)

    def current_record(self) -> BackupRecord | None:
        backup_id = self.selected_backup_id()
        if not backup_id:
            return None
        for record in self.backups:
            if record.id == backup_id:
                return record
        return None

    def fill_details(self) -> None:
        record = self.current_record()
        if record is None:
            self.clear_details()
            return
        self.set_editor_enabled(True)
        self.name_edit.setText(record.name)
        self.favorite_check.setChecked(record.favorite)
        self.description_edit.setPlainText(record.description)
        lines = [
            f"时间: {record.created_at}",
            f"Profile: {record.profile_name}",
            f"主机: {record.host}",
            f"目标路径: {record.target_path}",
            f"源类型: {record.source_type}",
            f"备份模式: {record.backup_mode}",
            f"大小: {self.format_size(record.backup_size)}",
            f"远端备份: {record.remote_backup_path}",
            f"收藏: {'是' if record.favorite else '否'}",
            "后置命令:",
            *[f"  {cmd}" for cmd in record.post_commands],
        ]
        self.details.setPlainText("\n".join(lines))

    def on_restore(self) -> None:
        backup_id = self.selected_backup_id()
        if backup_id:
            self.restore_requested.emit(backup_id, self.restore_commands_check.isChecked())
            self.accept()

    def on_delete(self) -> None:
        backup_id = self.selected_backup_id()
        if backup_id:
            self.delete_requested.emit(backup_id)

    def on_save_metadata(self) -> None:
        record = self.current_record()
        if record is None:
            return
        updated = BackupRecord.from_dict(record.to_dict())
        updated.name = self.name_edit.text().strip() or record.name
        updated.description = self.description_edit.toPlainText().strip()
        updated.favorite = self.favorite_check.isChecked()
        self.metadata_save_requested.emit(updated)

    def clear_details(self) -> None:
        self.name_edit.clear()
        self.description_edit.clear()
        self.favorite_check.setChecked(False)
        self.details.clear()
        self.set_editor_enabled(False)

    def set_editor_enabled(self, enabled: bool) -> None:
        self.name_edit.setEnabled(enabled)
        self.description_edit.setEnabled(enabled)
        self.favorite_check.setEnabled(enabled)
        self.save_meta_button.setEnabled(enabled)
        self.restore_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    @staticmethod
    def short_description(text: str) -> str:
        compact = " ".join(text.split())
        if len(compact) <= 28:
            return compact
        return f"{compact[:28]}..."

    @staticmethod
    def format_size(value: int) -> str:
        if value <= 0:
            return "-"
        size = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{value} B"


class HistoryDialog(QDialog):
    def __init__(self, history: list[HistoryRecord], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.history = history
        self.setWindowTitle("执行历史")
        self.resize(980, 520)
        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["开始时间", "Profile", "动作", "主机", "目标路径", "结果", "耗时"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self.fill_details)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
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
        if history:
            self.table.selectRow(0)

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
            return
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


class LogFetchWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, profile: DeploymentProfile, path: str) -> None:
        super().__init__()
        self.profile = profile
        self.path = path

    def run(self) -> None:
        try:
            from ..remote import RemoteDeployer

            class _NullLogger:
                def info(self, *_): pass
                def warning(self, *_): pass
                def error(self, *_): pass
                def success(self, *_): pass

            with RemoteDeployer(self.profile, _NullLogger()) as deployer:
                text = deployer.read_remote_log(self.path)
            self.finished.emit(text)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class LogViewerDialog(QDialog):
    config_saved = Signal(str, str)

    _TAB_DEFAULT = 0
    _TAB_ERROR = 1

    def __init__(self, profile: DeploymentProfile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.profile = profile
        self._worker: LogFetchWorker | None = None
        self._current_tab = self._TAB_DEFAULT
        self.setWindowTitle(f"查看日志 — {profile.name} @ {profile.host}")
        self.resize(980, 600)
        self._build_ui()
        if self._has_paths():
            self._fetch_current()

    def _has_paths(self) -> bool:
        return bool(self._effective_path(self._TAB_DEFAULT) or self._effective_path(self._TAB_ERROR))

    def _effective_path(self, tab: int) -> str:
        """返回已配置路径；未配置时从 target_path 推导默认值。"""
        if tab == self._TAB_DEFAULT:
            if self.profile.log_path_default:
                return self.profile.log_path_default
            base = self.profile.target_path.rstrip("/")
            return f"{base}/logs/default.log" if base else ""
        else:
            if self.profile.log_path_error:
                return self.profile.log_path_error
            base = self.profile.target_path.rstrip("/")
            return f"{base}/logs/error.log" if base else ""

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top_bar = QHBoxLayout()
        self._config_button = QPushButton("配置路径", self)
        self._config_button.setProperty("role", "muted")
        self._config_button.clicked.connect(self._open_config)
        top_bar.addStretch(1)
        top_bar.addWidget(self._config_button)
        layout.addLayout(top_bar)

        tab_bar = QHBoxLayout()
        self._tab_default = QPushButton("default.log", self)
        self._tab_default.setCheckable(True)
        self._tab_default.setChecked(True)
        self._tab_default.clicked.connect(lambda: self._switch_tab(self._TAB_DEFAULT))
        self._tab_error = QPushButton("error.log", self)
        self._tab_error.setCheckable(True)
        self._tab_error.clicked.connect(lambda: self._switch_tab(self._TAB_ERROR))
        self._refresh_button = QPushButton("刷新", self)
        self._refresh_button.setProperty("role", "secondary")
        self._refresh_button.clicked.connect(self._fetch_current)
        self._close_button = QPushButton("关闭", self)
        self._close_button.clicked.connect(self.accept)
        tab_bar.addWidget(self._tab_default)
        tab_bar.addWidget(self._tab_error)
        tab_bar.addStretch(1)
        tab_bar.addWidget(self._refresh_button)
        tab_bar.addWidget(self._close_button)
        layout.addLayout(tab_bar)

        self._log_area = QPlainTextEdit(self)
        self._log_area.setReadOnly(True)
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.Monospace)
        self._log_area.setFont(font)
        layout.addWidget(self._log_area, 1)

        self._status_label = QLabel("就绪", self)
        self._status_label.setProperty("role", "muted")
        layout.addWidget(self._status_label)

        if not self._has_paths():
            self._log_area.setPlainText("请先点击右上角「配置路径」")

    def _switch_tab(self, tab: int) -> None:
        self._current_tab = tab
        self._tab_default.setChecked(tab == self._TAB_DEFAULT)
        self._tab_error.setChecked(tab == self._TAB_ERROR)
        self._fetch_current()

    def _current_path(self) -> str:
        return self._effective_path(self._current_tab)

    def _fetch_current(self) -> None:
        path = self._current_path()
        if not path:
            self._log_area.setPlainText("请先点击右上角「配置路径」")
            return
        if self._worker and self._worker.isRunning():
            return
        self._status_label.setText("加载中...")
        self._refresh_button.setEnabled(False)
        self._worker = LogFetchWorker(self.profile, path)
        self._worker.finished.connect(self._on_fetch_done)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.start()

    def _on_fetch_done(self, text: str) -> None:
        self._log_area.setPlainText(text)
        cursor = self._log_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._log_area.setTextCursor(cursor)
        line_count = text.count("\n") + 1 if text.strip() else 0
        now = datetime.now().strftime("%H:%M:%S")
        self._status_label.setText(f"已加载 {line_count} 行  最后更新：{now}")
        self._refresh_button.setEnabled(True)

    def _on_fetch_failed(self, error: str) -> None:
        self._log_area.setPlainText(f"[错误] {error}")
        self._status_label.setText("加载失败")
        self._refresh_button.setEnabled(True)

    def _open_config(self) -> None:
        dlg = _LogPathConfigDialog(
            self.profile.log_path_default or self._effective_path(self._TAB_DEFAULT),
            self.profile.log_path_error or self._effective_path(self._TAB_ERROR),
            self,
        )
        if dlg.exec_() == QDialog.Accepted:
            default_path, error_path = dlg.get_paths()
            self.profile.log_path_default = default_path
            self.profile.log_path_error = error_path
            self.config_saved.emit(default_path, error_path)
            self._fetch_current()


class _LogPathConfigDialog(QDialog):
    def __init__(self, default_path: str, error_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("配置日志路径")
        self.setFixedWidth(420)
        form = QFormLayout(self)
        self._default_edit = QLineEdit(default_path, self)
        self._error_edit = QLineEdit(error_path, self)
        form.addRow("正常日志", self._default_edit)
        form.addRow("异常日志", self._error_edit)
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
        w = QWidget(self)
        w.setLayout(layout)
        return w

    def get_paths(self) -> tuple[str, str]:
        return self._default_edit.text().strip(), self._error_edit.text().strip()
