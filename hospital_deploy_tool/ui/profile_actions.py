from __future__ import annotations

from pathlib import Path

from PySide2.QtCore import QItemSelectionModel, QSize, Qt
from PySide2.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidgetItem,
    QPushButton,
    QWidget,
)

from ..constants import (
    DEFAULT_BACKUP_ROOT,
    PROFILE_KIND_BACKEND,
    PROFILE_KIND_FRONTEND,
    PROFILE_KIND_UNSET,
    SOURCE_TYPE_ARCHIVE,
    SOURCE_TYPE_DIRECTORY,
)
from ..models import DeploymentProfile


class ProfileActions:
    def load_profiles(self, checked_ids: list[str] | None = None) -> None:
        if not self.state.profiles:
            profile = DeploymentProfile(name="默认配置")
            self.state.profiles.append(profile)
            self.storage.save(self.state)
            self.active_profile_id = profile.id
        if not self.find_profile(self.active_profile_id):
            self.active_profile_id = self.state.profiles[0].id
        restored_ids = checked_ids or self.selected_profile_ids()
        self.refresh_profile_list(restored_ids)
        item = self.profile_list.currentItem()
        if item:
            profile_id = item.data(Qt.UserRole)
            if profile_id:
                self.select_profile(profile_id, sync_list=False)
                return
        self.select_profile(self.active_profile_id)

    def select_profile(self, profile_id: str, *, sync_list: bool = True) -> None:
        profile = self.find_profile(profile_id) or self.state.profiles[0]
        self.active_profile_id = profile.id
        if sync_list:
            self.set_profile_list_selection(profile.id)
        self.fill_form(profile)
        self.refresh_profile_runtime_view(profile)
        self.refresh_log_viewer(profile, auto_fetch=False)

    def fill_form(self, profile: DeploymentProfile) -> None:
        self.profile_kind_combo.setCurrentIndex(self.profile_kind_combo.findData(profile.profile_kind))
        self.source_type_combo.setCurrentIndex(self.source_type_combo.findData(profile.source_type))
        self.compress_check.setChecked(profile.compress_upload)
        self.source_path_edit.setText(profile.source_path)
        self.host_edit.setText(profile.host)
        self.port_spin.setValue(profile.port)
        self.user_edit.setText(profile.username)
        self.password_edit.setText(profile.password)
        self.target_edit.setText(profile.target_path)
        self.max_backup_spin.setValue(profile.max_backup_count)
        self.backup_root_edit.setText(DEFAULT_BACKUP_ROOT)
        self.command_edit.setPlainText("\n".join(profile.post_commands))
        self.profile_status.setText(f"配置: {profile.name} | {self.profile_kind_text(profile.profile_kind)}")
        self.target_status.setText(
            f"目标: {self.host_port_text(profile)} {profile.target_path or ''}".strip()
        )
        self.connection_state.setText("未测试连接")
        self.update_summary()

    def snapshot_profile(self, profile_id: str | None = None, name: str | None = None) -> DeploymentProfile:
        commands = [line.strip() for line in self.command_edit.toPlainText().splitlines() if line.strip()]
        if name:
            profile_name = name
        elif self.state.profiles:
            profile_name = self.current_profile().name
        else:
            profile_name = "新配置"
        existing = self.find_profile(profile_id or self.active_profile_id)
        return DeploymentProfile(
            id=profile_id or self.active_profile_id or DeploymentProfile().id,
            name=profile_name,
            profile_kind=self.profile_kind_combo.currentData() or PROFILE_KIND_UNSET,
            source_type=self.source_type_combo.currentData(),
            source_path=self.source_path_edit.text().strip(),
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            username=self.user_edit.text().strip(),
            password=self.password_edit.text(),
            target_path=self.target_edit.text().strip(),
            post_commands=commands,
            max_backup_count=self.max_backup_spin.value(),
            backup_root=DEFAULT_BACKUP_ROOT,
            compress_upload=self.compress_check.isChecked(),
            log_path_default=existing.log_path_default if existing else "",
            log_path_error=existing.log_path_error if existing else "",
        )

    def current_profile(self) -> DeploymentProfile:
        return self.find_profile(self.active_profile_id) or DeploymentProfile(name="新配置")

    def find_profile(self, profile_id: str) -> DeploymentProfile | None:
        return next((item for item in self.state.profiles if item.id == profile_id), None)

    def button(self, text: str, handler, role: str | None = None) -> QPushButton:
        button = QPushButton(text, self)
        if role:
            button.setProperty("role", role)
        button.clicked.connect(handler)
        return button

    def wrap(self, layout: QHBoxLayout) -> QWidget:
        widget = QWidget(self)
        widget.setLayout(layout)
        return widget

    def wrap_text_button(self, label, button: QPushButton) -> QWidget:
        row = QHBoxLayout()
        row.addWidget(label, 1)
        row.addWidget(button)
        return self.wrap(row)

    def refresh_profile_list(self, checked_ids: list[str] | None = None) -> None:
        selected_id = self.active_profile_id
        checked_set = set(checked_ids or [])
        visible_ids: list[str] = []
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for profile in self.state.profiles:
            if not self.matches_profile_filter(profile):
                continue
            item = QListWidgetItem(self.profile_list_text(profile))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if profile.id in checked_set else Qt.Unchecked)
            item.setData(Qt.UserRole, profile.id)
            item.setToolTip(self.profile_list_tooltip(profile))
            item.setSizeHint(QSize(0, 52))
            self.profile_list.addItem(item)
            visible_ids.append(profile.id)
        self.apply_profile_list_selection(visible_ids, selected_id)
        self.profile_list.blockSignals(False)
        self.profile_empty_label.setVisible(not visible_ids)
        self.update_profile_list_drag_state()

    def set_profile_list_selection(self, profile_id: str) -> None:
        self.profile_list.blockSignals(True)
        self.apply_profile_list_selection(self.visible_profile_ids(), profile_id)
        self.profile_list.blockSignals(False)

    def apply_profile_list_selection(
        self,
        visible_ids: list[str],
        preferred_current_id: str,
    ) -> None:
        current_row = -1
        self.profile_list.clearSelection()
        for row in range(self.profile_list.count()):
            item = self.profile_list.item(row)
            profile_id = item.data(Qt.UserRole)
            if profile_id == preferred_current_id:
                current_row = row
        if current_row >= 0:
            item = self.profile_list.item(current_row)
            item.setSelected(True)
            self.profile_list.setCurrentItem(item, QItemSelectionModel.SelectCurrent)
        elif self.profile_list.count() > 0:
            item = self.profile_list.item(0)
            item.setSelected(True)
            self.profile_list.setCurrentItem(item, QItemSelectionModel.SelectCurrent)

    def selected_profile_ids(self) -> list[str]:
        selected_ids: list[str] = []
        for row in range(self.profile_list.count()):
            item = self.profile_list.item(row)
            if item.checkState() == Qt.Checked:
                profile_id = item.data(Qt.UserRole)
                if profile_id:
                    selected_ids.append(profile_id)
        return selected_ids

    def selected_profiles_in_visual_order(self) -> list[DeploymentProfile]:
        selected_ids = set(self.selected_profile_ids())
        profiles: list[DeploymentProfile] = []
        for row in range(self.profile_list.count()):
            item = self.profile_list.item(row)
            profile_id = item.data(Qt.UserRole)
            if profile_id not in selected_ids:
                continue
            profile = self.find_profile(profile_id)
            if profile is not None:
                profiles.append(profile)
        return profiles

    def visible_profile_ids(self) -> list[str]:
        ids: list[str] = []
        for row in range(self.profile_list.count()):
            item = self.profile_list.item(row)
            profile_id = item.data(Qt.UserRole)
            if profile_id:
                ids.append(profile_id)
        return ids

    def update_profile_list_drag_state(self) -> None:
        allow_drag = not self.profile_search_edit.text().strip() and self.profile_filter_combo.currentData() is None
        mode = QAbstractItemView.InternalMove if allow_drag else QAbstractItemView.NoDragDrop
        self.profile_list.setDragDropMode(mode)
        self.profile_list.setDragEnabled(allow_drag)
        self.profile_list.setAcceptDrops(allow_drag)

    def on_profile_rows_moved(self, *_args) -> None:
        if self.profile_search_edit.text().strip() or self.profile_filter_combo.currentData() is not None:
            return
        ordered_ids = self.visible_profile_ids()
        if len(ordered_ids) != len(self.state.profiles):
            return
        profiles_by_id = {profile.id: profile for profile in self.state.profiles}
        self.state.profiles = [profiles_by_id[profile_id] for profile_id in ordered_ids if profile_id in profiles_by_id]
        self.storage.save(self.state)

    def matches_profile_filter(self, profile: DeploymentProfile) -> bool:
        kind_filter = self.profile_filter_combo.currentData()
        if kind_filter and profile.profile_kind != kind_filter:
            return False
        keyword = self.profile_search_edit.text().strip().lower()
        if not keyword:
            return True
        haystack = " ".join(
            [
                profile.name,
                self.profile_kind_text(profile.profile_kind),
                profile.host,
                profile.target_path,
                profile.source_path,
            ]
        ).lower()
        return keyword in haystack

    def profile_kind_text(self, profile_kind: str) -> str:
        if profile_kind == PROFILE_KIND_BACKEND:
            return "后端"
        if profile_kind == PROFILE_KIND_FRONTEND:
            return "前端"
        return "未设置"

    def profile_list_text(self, profile: DeploymentProfile) -> str:
        details = "  ".join(
            part
            for part in [
                self.profile_kind_text(profile.profile_kind),
                self.host_port_text(profile),
                self.short_text(profile.target_path or profile.source_path or "-"),
            ]
            if part
        )
        return f"{profile.name}\n{details}"

    def profile_list_tooltip(self, profile: DeploymentProfile) -> str:
        return (
            f"类型: {self.profile_kind_text(profile.profile_kind)}\n"
            f"主机: {self.host_port_text(profile)}\n"
            f"目标路径: {profile.target_path or '-'}\n"
            f"源路径: {profile.source_path or '-'}"
        )

    @staticmethod
    def short_text(value: str, limit: int = 48) -> str:
        if len(value) <= limit:
            return value
        return f"{value[:limit]}..."

    def on_profile_selected(self) -> None:
        item = self.profile_list.currentItem()
        profile_id = item.data(Qt.UserRole) if item else None
        if profile_id:
            self.select_profile(profile_id, sync_list=False)

    def on_profile_filter_changed(self) -> None:
        previous_id = self.active_profile_id
        self.refresh_profile_list()
        item = self.profile_list.currentItem()
        if item:
            profile_id = item.data(Qt.UserRole)
            if profile_id and profile_id != previous_id:
                self.select_profile(profile_id, sync_list=False)

    def on_new_profile(self) -> None:
        profile = DeploymentProfile(name="新配置")
        self.active_profile_id = profile.id
        self.profile_list.clearSelection()
        self.fill_form(profile)

    def on_save_profile(self) -> None:
        selected_ids = self.selected_profile_ids()
        profile = self.snapshot_profile()
        self.storage.upsert_profile(self.state, profile)
        self.active_profile_id = profile.id
        self.load_profiles(selected_ids or [profile.id])

    def on_rename_profile(self) -> None:
        profile = self.current_profile()
        name, ok = QInputDialog.getText(self, "重命名配置", "请输入新名称", text=profile.name)
        if ok and name.strip():
            selected_ids = self.selected_profile_ids()
            profile.name = name.strip()
            self.storage.upsert_profile(self.state, profile)
            self.load_profiles(selected_ids or [profile.id])

    def on_clone_profile(self) -> None:
        current = self.current_profile()
        name, ok = QInputDialog.getText(self, "复制配置", "请输入新配置名称", text=f"{current.name} - 副本")
        if ok and name.strip():
            selected_ids = self.selected_profile_ids()
            profile = self.snapshot_profile(profile_id=DeploymentProfile().id, name=name.strip())
            self.storage.upsert_profile(self.state, profile)
            self.active_profile_id = profile.id
            self.load_profiles(selected_ids + [profile.id])

    def toggle_password_visible(self) -> None:
        if self.password_edit.echoMode() == QLineEdit.Password:
            self.password_edit.setEchoMode(QLineEdit.Normal)
            self.password_visible_button.setText("隐藏")
        else:
            self.password_edit.setEchoMode(QLineEdit.Password)
            self.password_visible_button.setText("显示")

    def browse_source(self) -> None:
        source_type = self.source_type_combo.currentData()
        if source_type == SOURCE_TYPE_DIRECTORY:
            path = QFileDialog.getExistingDirectory(self, "选择源目录", self.source_path_edit.text())
        elif source_type == SOURCE_TYPE_ARCHIVE:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择压缩文件", self.source_path_edit.text(),
                "压缩文件 (*.tar.gz *.tgz);;所有文件 (*)",
            )
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择源文件", self.source_path_edit.text())
        if path:
            self.source_path_edit.setText(path)
            self.detect_source_access()
            self.update_summary()

    def detect_source_access(self) -> None:
        path = self.source_path_edit.text().strip()
        exists = Path(path).exists() if path else False
        if exists:
            self.source_hint.setText(f"路径可访问: {path}")
            return
        if path.startswith("\\\\wsl.localhost"):
            self.source_hint.setText("当前会话无法访问 \\\\wsl.localhost，请改用 \\\\tsclient\\盘符 或普通 Windows 目录。")
            return
        self.source_hint.setText(f"路径不可访问: {path or '未填写'}")

    def on_source_type_changed(self) -> None:
        source_type = self.source_type_combo.currentData()
        self.compress_check.setVisible(source_type == SOURCE_TYPE_DIRECTORY)
        if source_type != SOURCE_TYPE_DIRECTORY:
            self.compress_check.setChecked(False)
        self.update_summary()

    def update_summary(self) -> None:
        source_type = self.source_type_combo.currentData()
        if source_type == SOURCE_TYPE_ARCHIVE:
            self.coverage_label.setText("压缩文件模式：上传 tar.gz 到远端后解压到目标目录。")
        elif source_type == SOURCE_TYPE_DIRECTORY and self.compress_check.isChecked():
            self.coverage_label.setText("目录模式(压缩上传)：本地打包 → 传输 → 远端解压。")
        elif source_type == SOURCE_TYPE_DIRECTORY:
            self.coverage_label.setText("目录模式：备份目标目录后清空并上传目录内容。")
        else:
            self.coverage_label.setText("文件模式：目标路径可填目录或完整文件路径；填目录时按源文件名上传，同名文件存在则先备份后覆盖。")
        profile = self.snapshot_profile()
        self.profile_status.setText(f"配置: {profile.name} | {self.profile_kind_text(profile.profile_kind)}")
        self.summary_label.setText(self.summary_text(profile))
        self.target_status.setText(
            f"目标: {self.host_port_text(profile)} {profile.target_path or ''}".strip()
        )

    def summary_text(self, profile: DeploymentProfile) -> str:
        command_count = len([cmd for cmd in profile.post_commands if cmd.strip()])
        return (
            f"配置类型: {self.profile_kind_text(profile.profile_kind)}\n"
            f"源路径: {profile.source_path or '-'}\n"
            f"目标: {self.host_port_text(profile)} -> {profile.target_path or '-'}\n"
            f"备份目录: {profile.backup_root or '-'}\n"
            f"后置命令: {command_count} 条"
        )

    def host_port_text(self, profile: DeploymentProfile) -> str:
        if not profile.host:
            return "-"
        return f"{profile.host}:{profile.port}"
