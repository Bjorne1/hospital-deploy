from __future__ import annotations

from PySide2.QtCore import Qt, Signal
from PySide2.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import BackupRecord


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
