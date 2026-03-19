from __future__ import annotations

from PySide2.QtCore import Qt, Signal
from PySide2.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import BackupRecord, HistoryRecord


class BackupDialog(QDialog):
    restore_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, backups: list[BackupRecord], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backups = backups
        self.setWindowTitle("备份管理")
        self.resize(980, 520)
        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["时间", "Profile", "主机", "目标路径", "类型", "大小", "远端备份路径"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self.fill_details)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.status = QLabel(self)
        self.restore_button = QPushButton("恢复选中备份", self)
        self.delete_button = QPushButton("删除记录", self)
        self.close_button = QPushButton("关闭", self)
        self.restore_button.clicked.connect(self.on_restore)
        self.delete_button.clicked.connect(self.on_delete)
        self.close_button.clicked.connect(self.accept)
        self.build_layout()
        self.load_rows(backups)

    def build_layout(self) -> None:
        button_bar = QHBoxLayout()
        button_bar.addWidget(self.status)
        button_bar.addStretch(1)
        button_bar.addWidget(self.restore_button)
        button_bar.addWidget(self.delete_button)
        button_bar.addWidget(self.close_button)

        right = QVBoxLayout()
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

    def load_rows(self, backups: list[BackupRecord]) -> None:
        self.backups = backups
        self.table.setRowCount(len(backups))
        for row, record in enumerate(backups):
            values = [
                record.created_at,
                record.profile_name,
                record.host,
                record.target_path,
                record.source_type,
                self.format_size(record.backup_size),
                record.remote_backup_path,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, record.id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.status.setText(f"共 {len(backups)} 条备份记录")
        if backups:
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
            self.details.clear()
            return
        lines = [
            f"时间: {record.created_at}",
            f"Profile: {record.profile_name}",
            f"主机: {record.host}",
            f"目标路径: {record.target_path}",
            f"源类型: {record.source_type}",
            f"备份模式: {record.backup_mode}",
            f"大小: {self.format_size(record.backup_size)}",
            f"远端备份: {record.remote_backup_path}",
            "后置命令:",
            *[f"  {cmd}" for cmd in record.post_commands],
        ]
        self.details.setPlainText("\n".join(lines))

    def on_restore(self) -> None:
        backup_id = self.selected_backup_id()
        if backup_id:
            self.restore_requested.emit(backup_id)

    def on_delete(self) -> None:
        backup_id = self.selected_backup_id()
        if backup_id:
            self.delete_requested.emit(backup_id)

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
