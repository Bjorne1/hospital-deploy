from __future__ import annotations

from pathlib import Path

from PySide2.QtCore import Qt, QThread
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QListWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QComboBox,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..constants import (
    ACTION_COMMANDS_ONLY,
    ACTION_DEPLOY,
    ACTION_UPLOAD_ONLY,
    DEFAULT_BACKUP_ROOT,
    PROFILE_KIND_BACKEND,
    PROFILE_KIND_FRONTEND,
    PROFILE_KIND_UNSET,
    SOURCE_TYPE_ARCHIVE,
    SOURCE_TYPE_DIRECTORY,
    SOURCE_TYPE_FILE,
)
from ..models import DeploymentProfile
from ..storage import AppState, Storage
from ..workers import OperationWorker
from .operation_actions import OperationActions
from .profile_actions import ProfileActions
from .theme import APP_STYLESHEET
from .widgets import NoWheelSpinBox


class MainWindow(ProfileActions, OperationActions, QMainWindow):
    def __init__(self, storage: Storage, state: AppState) -> None:
        super().__init__()
        self.storage = storage
        self.state = state
        self.thread: QThread | None = None
        self.worker: OperationWorker | None = None
        self.current_log_file = ""
        self.log_viewer_window = None
        self.running_profile_id = ""
        self.operation_queue = []
        self.batch_total = 0
        self.batch_finished = 0
        self.batch_has_failure = False
        self.batch_failed_count = 0
        self.batch_stop_on_failure = False
        self.active_profile_id = state.profiles[0].id if state.profiles else ""
        self.setWindowTitle("医院一键部署工具")
        icon_path = self._find_icon()
        if icon_path and icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1440, 900)
        self.setStyleSheet(APP_STYLESHEET)
        self.build_ui()
        self.load_profiles()

    @staticmethod
    def _find_icon() -> Path | None:
        import sys
        if getattr(sys, "frozen", False):
            base = Path(sys._MEIPASS)  # noqa: SLF001
        else:
            base = Path(__file__).resolve().parent.parent
        icon = base / "hospital_deploy_tool" / "app_icon.ico"
        if icon.exists():
            return icon
        icon = base / "app_icon.ico"
        return icon if icon.exists() else None

    def build_ui(self) -> None:
        root = QWidget(self)
        page = QHBoxLayout(root)
        page.addWidget(self.build_left_panel(), 3)
        page.addWidget(self.build_right_panel(), 1)
        self.setCentralWidget(root)
        bar = QStatusBar(self)
        bar.showMessage("就绪")
        self.setStatusBar(bar)

    def profile_group(self) -> QGroupBox:
        group = QGroupBox("配置管理", self)
        layout = QVBoxLayout(group)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索", self))
        self.profile_search_edit = QLineEdit(self)
        self.profile_search_edit.setPlaceholderText("按配置名、IP、路径筛选")
        self.profile_search_edit.textChanged.connect(self.on_profile_filter_changed)
        search_row.addWidget(self.profile_search_edit, 1)
        layout.addLayout(search_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("筛选", self))
        self.profile_filter_combo = QComboBox(self)
        self.profile_filter_combo.addItem("全部", None)
        self.profile_filter_combo.addItem("后端", PROFILE_KIND_BACKEND)
        self.profile_filter_combo.addItem("前端", PROFILE_KIND_FRONTEND)
        self.profile_filter_combo.addItem("未设置", PROFILE_KIND_UNSET)
        self.profile_filter_combo.currentIndexChanged.connect(self.on_profile_filter_changed)
        filter_row.addWidget(self.profile_filter_combo)
        self.new_button = self.button("新建", self.on_new_profile, "secondary")
        filter_row.addStretch(1)
        filter_row.addWidget(self.new_button)
        layout.addLayout(filter_row)

        self.profile_list = QListWidget(self)
        self.profile_list.setMinimumHeight(220)
        self.profile_list.setWordWrap(True)
        self.profile_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.profile_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.profile_list.setDefaultDropAction(Qt.MoveAction)
        self.profile_list.setDragEnabled(True)
        self.profile_list.setAcceptDrops(True)
        self.profile_list.setDropIndicatorShown(True)
        self.profile_list.itemSelectionChanged.connect(self.on_profile_selected)
        self.profile_list.model().rowsMoved.connect(self.on_profile_rows_moved)
        layout.addWidget(self.profile_list)

        self.profile_empty_label = QLabel("没有匹配的配置", self)
        self.profile_empty_label.setProperty("role", "muted")
        self.profile_empty_label.setVisible(False)
        layout.addWidget(self.profile_empty_label)

        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("当前类型", self))
        self.profile_kind_combo = QComboBox(self)
        self.profile_kind_combo.addItem("未设置", PROFILE_KIND_UNSET)
        self.profile_kind_combo.addItem("后端", PROFILE_KIND_BACKEND)
        self.profile_kind_combo.addItem("前端", PROFILE_KIND_FRONTEND)
        self.profile_kind_combo.currentIndexChanged.connect(self.update_summary)
        kind_row.addWidget(self.profile_kind_combo, 1)
        layout.addLayout(kind_row)

        primary_button_row = QHBoxLayout()
        self.save_button = self.button("保存", self.on_save_profile)
        self.rename_button = self.button("重命名", self.on_rename_profile, "secondary")
        self.clone_button = self.button("复制", self.on_clone_profile, "secondary")
        self.backup_button = self.button("备份管理", self.open_backup_dialog, "muted")
        self.history_button = self.button("执行历史", self.open_history_dialog, "muted")
        primary_button_row.addWidget(self.save_button)
        primary_button_row.addWidget(self.rename_button)
        primary_button_row.addWidget(self.clone_button)
        layout.addLayout(primary_button_row)

        secondary_button_row = QHBoxLayout()
        secondary_button_row.addWidget(self.backup_button)
        secondary_button_row.addWidget(self.history_button)
        layout.addLayout(secondary_button_row)
        return group

    def build_left_panel(self) -> QWidget:
        root = QWidget(self)
        layout = QHBoxLayout(root)

        profile_panel = QWidget(self)
        profile_panel.setMinimumWidth(220)
        profile_panel.setMaximumWidth(260)
        profile_layout = QVBoxLayout(profile_panel)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addWidget(self.profile_group(), 1)

        form_container = QWidget(self)
        form_layout = QVBoxLayout(form_container)
        form_layout.addWidget(self.source_group())
        middle = QHBoxLayout()
        middle.addWidget(self.linux_group(), 1)
        middle.addWidget(self.behavior_group(), 1)
        form_layout.addLayout(middle)
        form_layout.addWidget(self.action_group())
        form_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_container)

        layout.addWidget(profile_panel)
        layout.addWidget(scroll, 1)
        return root

    def build_right_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setMinimumWidth(360)
        layout = QVBoxLayout(panel)
        layout.addWidget(self.status_group())
        layout.addWidget(self.progress_group())
        layout.addWidget(self.log_group(), 1)
        return panel

    def source_group(self) -> QGroupBox:
        group = QGroupBox("源配置", self)
        vbox = QVBoxLayout(group)

        self.source_type_combo = QComboBox(self)
        self.source_type_combo.addItem("文件", SOURCE_TYPE_FILE)
        self.source_type_combo.addItem("目录", SOURCE_TYPE_DIRECTORY)
        self.source_type_combo.addItem("压缩文件", SOURCE_TYPE_ARCHIVE)
        self.source_type_combo.currentIndexChanged.connect(self.on_source_type_changed)

        self.compress_check = QCheckBox("压缩上传（本地打包 tar.gz → 传输 → 远端解压）", self)
        self.compress_check.setVisible(False)
        self.compress_check.toggled.connect(self.update_summary)

        self.source_path_edit = QLineEdit(self)
        self.source_path_edit.textChanged.connect(self.update_summary)

        self.source_hint = QLabel("请选择当前会话能直接访问的源路径。", self)
        self.source_hint.setProperty("role", "muted")

        browse = self.button("浏览", self.browse_source, "secondary")
        detect = self.button("检测可访问性", self.detect_source_access, "secondary")

        # 左右布局：源类型占 1/5，源路径+按钮占 4/5
        main_row = QHBoxLayout()
        main_row.setSpacing(8)

        type_widget = QWidget(self)
        type_layout = QVBoxLayout(type_widget)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.setSpacing(2)
        type_label = QLabel("源类型", self)
        type_layout.addWidget(type_label)
        type_layout.addWidget(self.source_type_combo)
        type_layout.addStretch()

        path_widget = QWidget(self)
        path_layout = QVBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(2)
        path_label = QLabel("源路径", self)
        path_row = QHBoxLayout()
        path_row.setSpacing(4)
        path_row.addWidget(self.source_path_edit, 1)
        path_row.addWidget(browse)
        path_row.addWidget(detect)
        path_layout.addWidget(path_label)
        path_layout.addLayout(path_row)
        path_layout.addWidget(self.compress_check)
        path_layout.addWidget(self.source_hint)

        main_row.addWidget(type_widget, 1)   # 1/5
        main_row.addWidget(path_widget, 4)   # 4/5

        vbox.addLayout(main_row)
        return group

    def linux_group(self) -> QGroupBox:
        group = QGroupBox("目标 Linux 配置", self)
        form = QFormLayout(group)
        self.host_edit = QLineEdit(self)
        self.port_spin = NoWheelSpinBox(self)
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.port_spin.valueChanged.connect(self.update_summary)
        self.user_edit = QLineEdit(self)
        self.password_edit = QLineEdit(self)
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_visible_button = self.button("显示", self.toggle_password_visible, "muted")
        self.target_edit = QLineEdit(self)
        self.host_edit.textChanged.connect(self.update_summary)
        self.target_edit.textChanged.connect(self.update_summary)
        self.connection_state = QLabel("未测试连接", self)
        self.connection_state.setProperty("role", "muted")
        test_button = self.button("测试连接", self.test_connection, "secondary")
        form.addRow("主机 IP", self.host_edit)
        form.addRow("端口", self.port_spin)
        form.addRow("用户名", self.user_edit)
        password_row = QHBoxLayout()
        password_row.addWidget(self.password_edit, 1)
        password_row.addWidget(self.password_visible_button)
        form.addRow("密码", self.wrap(password_row))
        form.addRow("目标路径", self.target_edit)
        form.addRow("连接状态", self.wrap_text_button(self.connection_state, test_button))
        return group

    def behavior_group(self) -> QGroupBox:
        group = QGroupBox("部署行为", self)
        form = QFormLayout(group)
        self.max_backup_spin = NoWheelSpinBox(self)
        self.max_backup_spin.setRange(1, 999)
        self.max_backup_spin.setValue(10)
        self.max_backup_spin.valueChanged.connect(self.update_summary)
        self.backup_root_edit = QLineEdit(self)
        self.backup_root_edit.setText(DEFAULT_BACKUP_ROOT)
        self.backup_root_edit.setReadOnly(True)
        self.coverage_label = QLabel("文件模式：备份目标文件后覆盖。", self)
        self.coverage_label.setWordWrap(True)
        self.command_edit = QPlainTextEdit(self)
        self.command_edit.setPlaceholderText(
            "一行一个命令，例如：\nsystemctl restart his-drg.service"
        )
        self.command_edit.setMaximumHeight(72)
        self.command_edit.textChanged.connect(self.update_summary)
        form.addRow("覆盖说明", self.coverage_label)
        form.addRow("最大备份数", self.max_backup_spin)
        form.addRow("备份根目录", self.backup_root_edit)
        form.addRow("后置命令", self.command_edit)
        return group

    def action_group(self) -> QGroupBox:
        group = QGroupBox("执行区", self)
        layout = QVBoxLayout(group)
        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        self.deploy_button = self.button("开始部署", lambda: self.start_operation(ACTION_DEPLOY))
        self.upload_button = self.button(
            "仅上传",
            lambda: self.start_operation(ACTION_UPLOAD_ONLY),
            "secondary",
        )
        self.commands_button = self.button(
            "仅命令",
            lambda: self.start_operation(ACTION_COMMANDS_ONLY),
            "muted",
        )
        self.batch_deploy_button = self.button("批量部署", self.start_batch_deploy, "secondary")
        self.batch_stop_on_failure_check = QCheckBox("失败中断", self)
        self.batch_stop_on_failure_check.setChecked(False)
        self.batch_stop_on_failure_check.setToolTip("勾选后，批量部署遇到失败会停止后续任务。")
        self.log_button = self.button("查看日志", self.open_log_viewer, "muted")
        layout.addWidget(self.summary_label, 1)
        row = QHBoxLayout()
        batch_widget = QWidget(self)
        batch_layout = QVBoxLayout(batch_widget)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(4)
        batch_layout.addWidget(self.batch_deploy_button)
        batch_layout.addWidget(self.batch_stop_on_failure_check, 0, Qt.AlignHCenter)
        row.addWidget(self.deploy_button)
        row.addWidget(self.upload_button)
        row.addWidget(self.commands_button)
        row.addWidget(batch_widget)
        row.addWidget(self.log_button)
        layout.addLayout(row)
        return group

    def status_group(self) -> QGroupBox:
        group = QGroupBox("当前状态", self)
        layout = QVBoxLayout(group)
        self.status_label = QLabel("待执行", self)
        self.status_label.setProperty("role", "warning")
        self.profile_status = QLabel("-", self)
        self.target_status = QLabel("-", self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.profile_status)
        layout.addWidget(self.target_status)
        return group

    def progress_group(self) -> QGroupBox:
        group = QGroupBox("传输进度", self)
        layout = QVBoxLayout(group)
        self.progress_bar = QProgressBar(self)
        self.current_file_label = QLabel("尚未开始", self)
        self.progress_detail_label = QLabel("-", self)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.current_file_label)
        layout.addWidget(self.progress_detail_label)
        return group

    def log_group(self) -> QGroupBox:
        group = QGroupBox("实时日志", self)
        layout = QVBoxLayout(group)
        buttons = QHBoxLayout()
        self.clear_log_button = self.button("清空显示", self.clear_log, "muted")
        self.export_log_button = self.button("导出日志", self.export_log, "muted")
        buttons.addWidget(self.clear_log_button)
        buttons.addWidget(self.export_log_button)
        buttons.addStretch(1)
        self.log_edit = QPlainTextEdit(self)
        self.log_edit.setReadOnly(True)
        layout.addLayout(buttons)
        layout.addWidget(self.log_edit, 1)
        return group
