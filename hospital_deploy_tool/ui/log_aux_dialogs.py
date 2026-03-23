from __future__ import annotations

from PySide2.QtCore import Qt, Signal
from PySide2.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import HistoryRecord


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
        widget = QWidget(self)
        widget.setLayout(layout)
        return widget

    def get_paths(self) -> tuple[str, str]:
        return self._default_edit.text().strip(), self._error_edit.text().strip()
