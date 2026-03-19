from __future__ import annotations

from pathlib import Path

from PySide2.QtWidgets import QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QPushButton, QWidget

from ..constants import SOURCE_TYPE_ARCHIVE, SOURCE_TYPE_DIRECTORY
from ..models import DeploymentProfile


class ProfileActions:
    def load_profiles(self) -> None:
        if not self.state.profiles:
            profile = DeploymentProfile(name="默认配置")
            self.state.profiles.append(profile)
            self.storage.save(self.state)
            self.active_profile_id = profile.id
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self.state.profiles:
            self.profile_combo.addItem(profile.name, profile.id)
        self.profile_combo.blockSignals(False)
        self.select_profile(self.active_profile_id)

    def select_profile(self, profile_id: str) -> None:
        profile = self.find_profile(profile_id) or self.state.profiles[0]
        index = self.profile_combo.findData(profile.id)
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)
        self.active_profile_id = profile.id
        self.fill_form(profile)

    def fill_form(self, profile: DeploymentProfile) -> None:
        self.source_type_combo.setCurrentIndex(self.source_type_combo.findData(profile.source_type))
        self.compress_check.setChecked(profile.compress_upload)
        self.source_path_edit.setText(profile.source_path)
        self.host_edit.setText(profile.host)
        self.port_spin.setValue(profile.port)
        self.user_edit.setText(profile.username)
        self.password_edit.setText(profile.password)
        self.target_edit.setText(profile.target_path)
        self.max_backup_spin.setValue(profile.max_backup_count)
        self.backup_root_edit.setText(profile.backup_root)
        self.command_edit.setPlainText("\n".join(profile.post_commands))
        self.profile_status.setText(f"Profile: {profile.name}")
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
            source_type=self.source_type_combo.currentData(),
            source_path=self.source_path_edit.text().strip(),
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            username=self.user_edit.text().strip(),
            password=self.password_edit.text(),
            target_path=self.target_edit.text().strip(),
            post_commands=commands,
            max_backup_count=self.max_backup_spin.value(),
            backup_root=self.backup_root_edit.text().strip(),
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

    def on_profile_selected(self) -> None:
        profile_id = self.profile_combo.currentData()
        if profile_id:
            self.select_profile(profile_id)

    def on_new_profile(self) -> None:
        profile = DeploymentProfile(name="新配置")
        self.active_profile_id = profile.id
        self.fill_form(profile)

    def on_save_profile(self) -> None:
        profile = self.snapshot_profile()
        self.storage.upsert_profile(self.state, profile)
        self.active_profile_id = profile.id
        self.load_profiles()

    def on_rename_profile(self) -> None:
        profile = self.current_profile()
        name, ok = QInputDialog.getText(self, "重命名配置", "请输入新名称", text=profile.name)
        if ok and name.strip():
            profile.name = name.strip()
            self.storage.upsert_profile(self.state, profile)
            self.load_profiles()

    def on_clone_profile(self) -> None:
        current = self.current_profile()
        name, ok = QInputDialog.getText(self, "复制配置", "请输入新配置名称", text=f"{current.name} - 副本")
        if ok and name.strip():
            profile = self.snapshot_profile(profile_id=DeploymentProfile().id, name=name.strip())
            self.storage.upsert_profile(self.state, profile)
            self.active_profile_id = profile.id
            self.load_profiles()

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
        self.summary_label.setText(self.summary_text(profile))
        self.target_status.setText(
            f"目标: {self.host_port_text(profile)} {profile.target_path or ''}".strip()
        )

    def summary_text(self, profile: DeploymentProfile) -> str:
        command_count = len([cmd for cmd in profile.post_commands if cmd.strip()])
        return (
            f"源路径: {profile.source_path or '-'}\n"
            f"目标: {self.host_port_text(profile)} -> {profile.target_path or '-'}\n"
            f"备份目录: {profile.backup_root or '-'}\n"
            f"后置命令: {command_count} 条"
        )

    def host_port_text(self, profile: DeploymentProfile) -> str:
        if not profile.host:
            return "-"
        return f"{profile.host}:{profile.port}"
