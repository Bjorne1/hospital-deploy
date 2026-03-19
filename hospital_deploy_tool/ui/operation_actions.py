from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide2.QtCore import QThread
from PySide2.QtWidgets import QFileDialog, QMessageBox

from ..constants import (
    ACTION_COMMANDS_ONLY,
    ACTION_DEPLOY,
    ACTION_RESTORE_BACKUP,
    ACTION_TEST_CONNECTION,
    ACTION_UPLOAD_ONLY,
    get_logs_dir,
)
from ..models import BackupRecord, DeploymentProfile, HistoryRecord
from ..workers import OperationWorker
from .dialogs import BackupDialog, HistoryDialog


class OperationActions:
    def test_connection(self) -> None:
        profile = self.persist_form_profile()
        self.connection_state.setText("连接测试中...")
        self.start_worker(ACTION_TEST_CONNECTION, profile)

    def start_operation(
        self,
        action: str,
        profile: DeploymentProfile | None = None,
        backup_record: BackupRecord | None = None,
    ) -> None:
        if self.thread is not None:
            QMessageBox.warning(self, "操作进行中", "当前已有任务在执行，请等待完成。")
            return
        current = profile or self.persist_form_profile()
        if action != ACTION_TEST_CONNECTION and not self.confirm_action(action, current, backup_record):
            return
        self.start_worker(action, current, backup_record)

    def persist_form_profile(self) -> DeploymentProfile:
        profile = self.snapshot_profile()
        self.storage.upsert_profile(self.state, profile)
        self.active_profile_id = profile.id
        self.load_profiles()
        return profile

    def confirm_action(
        self,
        action: str,
        profile: DeploymentProfile,
        backup_record: BackupRecord | None,
    ) -> bool:
        titles = {
            ACTION_DEPLOY: "开始部署",
            ACTION_UPLOAD_ONLY: "仅上传",
            ACTION_COMMANDS_ONLY: "仅执行命令",
            ACTION_RESTORE_BACKUP: "恢复备份",
        }
        summary = self.summary_text(profile)
        if backup_record:
            summary += f"\n恢复备份: {backup_record.remote_backup_path}"
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        answer = QMessageBox.question(self, titles[action], summary, buttons)
        return answer == QMessageBox.StandardButton.Yes

    def start_worker(
        self,
        action: str,
        profile: DeploymentProfile,
        backup_record: BackupRecord | None = None,
    ) -> None:
        self.set_busy(True)
        self.clear_log()
        self.progress_bar.setValue(0)
        self.current_file_label.setText("准备执行...")
        self.progress_detail_label.setText("-")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in profile.name)
        log_path = get_logs_dir() / f"{timestamp}_{safe}_{action}.log"
        self.current_log_file = str(log_path)
        self.running_profile_id = profile.id
        self.thread = QThread(self)
        self.worker = OperationWorker(action, profile, log_path, backup_record)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log_emitted.connect(self.append_log)
        self.worker.status_changed.connect(self.set_status)
        self.worker.progress_changed.connect(self.update_progress)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.on_thread_finished)
        self.thread.start()

    def on_worker_finished(self, success: bool, payload: object) -> None:
        data = dict(payload)
        profile = self.find_profile(self.running_profile_id) or self.current_profile()
        if data.get("backup_record"):
            self.state.backups.insert(0, data["backup_record"])
        self.remove_deleted_backups(data.get("deleted_backups", []))
        history = HistoryRecord(
            profile_id=profile.id,
            profile_name=profile.name,
            action=data["action"],
            host=profile.host,
            target_path=data.get("deployed_target_path") or profile.target_path,
            source_type=profile.source_type,
            source_path=profile.source_path,
            success=success,
            started_at=data["started_at"],
            ended_at=data["ended_at"],
            duration_seconds=data["duration_seconds"],
            log_file=data["log_file"],
            summary=data["summary"],
            backup_id=data["backup_record"].id if data.get("backup_record") else "",
        )
        self.storage.add_history(self.state, history)
        if data.get("backup_record"):
            self.storage.save(self.state)
        self.statusBar().showMessage(data["summary"])
        self.set_status("成功" if success else "失败")
        if data["action"] == ACTION_TEST_CONNECTION:
            self.connection_state.setText("连接成功" if success else "连接失败")

    def on_thread_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None
        self.running_profile_id = ""
        self.set_busy(False)

    def append_log(self, _level: str, line: str) -> None:
        self.log_edit.appendPlainText(line)

    def update_progress(self, percent: int, file_text: str, detail: str) -> None:
        self.progress_bar.setValue(percent)
        self.current_file_label.setText(file_text)
        self.progress_detail_label.setText(detail)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_busy(self, busy: bool) -> None:
        buttons = [
            self.deploy_button,
            self.upload_button,
            self.commands_button,
            self.save_button,
            self.new_button,
            self.rename_button,
            self.clone_button,
            self.backup_button,
            self.history_button,
        ]
        for button in buttons:
            button.setEnabled(not busy)

    def open_backup_dialog(self) -> None:
        dialog = BackupDialog(self.state.backups, self)
        dialog.restore_requested.connect(self.restore_backup)
        dialog.delete_requested.connect(lambda backup_id: self.on_backup_deleted(dialog, backup_id))
        dialog.exec()

    def open_history_dialog(self) -> None:
        HistoryDialog(self.state.history, self).exec()

    def restore_backup(self, backup_id: str) -> None:
        record = next((item for item in self.state.backups if item.id == backup_id), None)
        profile = self.find_profile(record.profile_id) if record else None
        if record is None or profile is None:
            QMessageBox.critical(self, "恢复失败", "未找到对应 Profile，无法使用保存的连接信息恢复。")
            return
        self.start_operation(ACTION_RESTORE_BACKUP, profile=profile, backup_record=record)

    def delete_backup_record(self, backup_id: str) -> None:
        self.storage.remove_backup(self.state, backup_id)
        self.statusBar().showMessage("备份记录已删除")

    def on_backup_deleted(self, dialog: BackupDialog, backup_id: str) -> None:
        self.delete_backup_record(backup_id)
        dialog.load_rows(self.state.backups)

    def remove_deleted_backups(self, deleted_backups: list[BackupRecord]) -> None:
        if not deleted_backups:
            return
        deleted_paths = {item.remote_backup_path for item in deleted_backups}
        self.state.backups = [
            item for item in self.state.backups if item.remote_backup_path not in deleted_paths
        ]
        self.storage.save(self.state)

    def clear_log(self) -> None:
        self.log_edit.clear()

    def export_log(self) -> None:
        if not self.log_edit.toPlainText():
            QMessageBox.information(self, "导出日志", "当前没有可导出的日志。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", self.current_log_file or "deploy.log")
        if path:
            Path(path).write_text(self.log_edit.toPlainText(), encoding="utf-8")
            self.statusBar().showMessage(f"日志已导出到 {path}")
