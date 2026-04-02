from __future__ import annotations

from dataclasses import dataclass
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
    SOURCE_TYPE_FILE,
    get_logs_dir,
)
from ..log_tools import read_local_tail
from ..models import BackupRecord, DeploymentProfile, HistoryRecord
from ..remote import RemoteDeployer
from ..workers import OperationWorker
from .dialogs import BackupDialog
from .log_aux_dialogs import HistoryDialog
from .log_workbench import LogViewerDialog


class _SilentLogger:
    def info(self, *_args) -> None:
        return None

    def warning(self, *_args) -> None:
        return None

    def error(self, *_args) -> None:
        return None

    def success(self, *_args) -> None:
        return None


_INLINE_LOG_LINES = 1000


@dataclass(slots=True)
class QueuedOperation:
    action: str
    profile: DeploymentProfile
    backup_record: BackupRecord | None = None
    run_post_commands_after_restore: bool = False


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
        run_post_commands_after_restore: bool = False,
    ) -> None:
        if self.thread is not None or self.operation_queue:
            QMessageBox.warning(self, "操作进行中", "当前已有任务在执行，请等待完成。")
            return
        current = profile or self.persist_form_profile()
        if action != ACTION_TEST_CONNECTION and not self.confirm_action(
            action,
            current,
            backup_record,
            run_post_commands_after_restore,
        ):
            return
        self.start_worker(action, current, backup_record, run_post_commands_after_restore)

    def persist_form_profile(self) -> DeploymentProfile:
        selected_ids = self.selected_profile_ids()
        profile = self.snapshot_profile()
        self.storage.upsert_profile(self.state, profile)
        self.active_profile_id = profile.id
        self.load_profiles(selected_ids or [profile.id])
        return profile

    def start_batch_deploy(self) -> None:
        if self.thread is not None or self.operation_queue:
            QMessageBox.warning(self, "操作进行中", "当前已有任务在执行，请等待完成。")
            return
        self.persist_form_profile()
        profiles = self.selected_profiles_in_visual_order()
        if not profiles:
            QMessageBox.warning(self, "批量部署", "请先勾选至少一个配置。")
            return
        self.batch_stop_on_failure = self.batch_stop_on_failure_check.isChecked()
        summary = "\n".join(
            f"{index}. {profile.name} -> {profile.host}:{profile.port} {profile.target_path or '-'}"
            for index, profile in enumerate(profiles, start=1)
        )
        fail_strategy = "失败后停止后续任务" if self.batch_stop_on_failure else "失败后继续执行下一个"
        answer = QMessageBox.question(
            self,
            "批量部署",
            f"将按顺序部署以下 {len(profiles)} 个配置：\n\n{summary}\n\n失败策略：{fail_strategy}。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.operation_queue = [QueuedOperation(ACTION_DEPLOY, profile) for profile in profiles]
        self.batch_total = len(self.operation_queue)
        self.batch_finished = 0
        self.batch_has_failure = False
        self.batch_failed_count = 0
        self.start_next_queued_operation()

    def start_next_queued_operation(self) -> None:
        if not self.operation_queue:
            return
        current = self.operation_queue.pop(0)
        self.statusBar().showMessage(
            f"批量部署 {self.batch_finished + 1}/{self.batch_total}: {current.profile.name}"
        )
        self.start_worker(
            current.action,
            current.profile,
            current.backup_record,
            current.run_post_commands_after_restore,
        )

    def confirm_action(
        self,
        action: str,
        profile: DeploymentProfile,
        backup_record: BackupRecord | None,
        run_post_commands_after_restore: bool,
    ) -> bool:
        titles = {
            ACTION_DEPLOY: "开始部署",
            ACTION_UPLOAD_ONLY: "仅上传",
            ACTION_COMMANDS_ONLY: "仅执行命令",
            ACTION_RESTORE_BACKUP: "恢复备份",
        }
        summary = self.summary_text(profile)
        if backup_record:
            summary += f"\n恢复备份: {backup_record.name} ({backup_record.remote_backup_path})"
        if action == ACTION_RESTORE_BACKUP:
            summary += f"\n恢复后执行后置命令: {'是' if run_post_commands_after_restore else '否'}"
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        answer = QMessageBox.question(self, titles[action], summary, buttons)
        return answer == QMessageBox.StandardButton.Yes

    def start_worker(
        self,
        action: str,
        profile: DeploymentProfile,
        backup_record: BackupRecord | None = None,
        run_post_commands_after_restore: bool = False,
    ) -> None:
        self.set_busy(True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in profile.name)
        log_path = get_logs_dir() / f"{timestamp}_{safe}_{action}.log"
        self.current_log_file = str(log_path)
        self.running_profile_id = profile.id
        self.prepare_runtime_view_for_operation(profile)
        self.refresh_log_viewer(initial_log_file=self.current_log_file, auto_fetch=False)
        self.thread = QThread(self)
        self.worker = OperationWorker(
            action,
            profile,
            log_path,
            backup_record,
            run_post_commands_after_restore=run_post_commands_after_restore,
        )
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
        self.refresh_profile_runtime_view()
        self.refresh_log_viewer(auto_fetch=False)
        self.statusBar().showMessage(data["summary"])
        self.set_status("成功" if success else "失败")
        if data["action"] == ACTION_TEST_CONNECTION:
            self.connection_state.setText("连接成功" if success else "连接失败")
        if self.batch_total:
            self.batch_finished += 1
            if not success:
                self.batch_has_failure = True
                self.batch_failed_count += 1
            if not success and self.batch_stop_on_failure:
                self.operation_queue.clear()

    def on_thread_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None
        self.running_profile_id = ""
        if self.operation_queue:
            self.start_next_queued_operation()
            return
        self.set_busy(False)
        if self.batch_total:
            if self.batch_has_failure and self.batch_stop_on_failure:
                self.statusBar().showMessage(
                    f"批量部署已停止，已完成 {self.batch_finished}/{self.batch_total} 个配置。"
                )
            elif self.batch_has_failure:
                self.statusBar().showMessage(
                    f"批量部署完成，共 {self.batch_total} 个配置，失败 {self.batch_failed_count} 个。"
                )
            else:
                self.statusBar().showMessage(f"批量部署完成，共 {self.batch_total} 个配置。")
            self.batch_total = 0
            self.batch_finished = 0
            self.batch_has_failure = False
            self.batch_failed_count = 0
            self.batch_stop_on_failure = False
        self.refresh_profile_runtime_view()

    def append_log(self, _level: str, line: str) -> None:
        if self.active_profile_id != self.running_profile_id:
            return
        self.log_edit.appendPlainText(line)

    def update_progress(self, percent: int, file_text: str, detail: str) -> None:
        if self.active_profile_id != self.running_profile_id:
            return
        self.progress_bar.setValue(percent)
        self.current_file_label.setText(file_text)
        self.progress_detail_label.setText(detail)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_busy(self, busy: bool) -> None:
        buttons = [
            self.deploy_button,
            self.batch_deploy_button,
            self.batch_stop_on_failure_check,
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
        profile = self.persist_form_profile()
        try:
            backups = self.load_remote_backups(profile)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "备份管理", str(exc))
            return
        dialog = BackupDialog(backups, self)
        dialog.refresh_requested.connect(lambda: self.refresh_backup_dialog(dialog, profile))
        dialog.restore_requested.connect(
            lambda backup_id, run_commands: self.restore_backup(
                dialog,
                profile,
                backup_id,
                run_commands,
            )
        )
        dialog.delete_requested.connect(lambda backup_id: self.on_backup_deleted(dialog, profile, backup_id))
        dialog.metadata_save_requested.connect(
            lambda record: self.on_backup_metadata_saved(dialog, profile, record)
        )
        dialog.exec()

    def open_history_dialog(self) -> None:
        dialog = HistoryDialog(self.state.history, self)
        dialog.open_log_requested.connect(self.open_history_log)
        dialog.exec()

    def open_log_viewer(
        self,
        initial_log_file: str = "",
        profile: DeploymentProfile | None = None,
    ) -> None:
        current_profile = profile or self.current_profile()
        current_log_file = self.current_log_file_for_profile(current_profile)
        window = getattr(self, "log_viewer_window", None)
        if window is None:
            window = LogViewerDialog(
                current_profile,
                self.state.history,
                current_log_file=current_log_file,
                initial_log_file=initial_log_file,
                parent=self,
            )
            window.config_saved.connect(self.on_log_config_saved)
            window.destroyed.connect(lambda *_args: setattr(self, "log_viewer_window", None))
            self.log_viewer_window = window
        else:
            window.refresh_context(
                current_profile,
                self.state.history,
                current_log_file=current_log_file,
                initial_log_file=initial_log_file,
                auto_fetch=False,
            )
        window.show()
        window.raise_()
        window.activateWindow()
        window.refresh_context(
            current_profile,
            self.state.history,
            current_log_file=current_log_file,
            initial_log_file=initial_log_file,
            auto_fetch=True,
        )

    def open_history_log(self, record: HistoryRecord) -> None:
        profile = self.find_profile(record.profile_id) or self.current_profile()
        self.open_log_viewer(initial_log_file=record.log_file, profile=profile)

    def on_log_config_saved(self, profile_id: str, default_path: str, error_path: str) -> None:
        profile = self.find_profile(profile_id)
        if profile is None:
            return
        profile.log_path_default = default_path
        profile.log_path_error = error_path
        self.storage.upsert_profile(self.state, profile)
        self.refresh_log_viewer(profile, auto_fetch=False)

    def refresh_log_viewer(
        self,
        profile: DeploymentProfile | None = None,
        initial_log_file: str = "",
        auto_fetch: bool = False,
    ) -> None:
        window = getattr(self, "log_viewer_window", None)
        if window is None:
            return
        current_profile = profile or self.current_profile()
        window.refresh_context(
            current_profile,
            self.state.history,
            current_log_file=self.current_log_file_for_profile(current_profile),
            initial_log_file=initial_log_file,
            auto_fetch=auto_fetch,
        )

    def restore_backup(
        self,
        dialog: BackupDialog,
        profile: DeploymentProfile,
        backup_id: str,
        run_post_commands_after_restore: bool,
    ) -> None:
        record = next((item for item in dialog.backups if item.id == backup_id), None)
        if record is None:
            QMessageBox.critical(self, "恢复失败", "未找到选中的备份记录。")
            return
        self.start_operation(
            ACTION_RESTORE_BACKUP,
            profile=profile,
            backup_record=record,
            run_post_commands_after_restore=run_post_commands_after_restore,
        )

    def on_backup_deleted(
        self,
        dialog: BackupDialog,
        profile: DeploymentProfile,
        backup_id: str,
    ) -> None:
        record = next((item for item in dialog.backups if item.id == backup_id), None)
        if record is None:
            QMessageBox.warning(self, "删除失败", "未找到选中的备份记录。")
            return
        answer = QMessageBox.question(
            self,
            "删除备份",
            f"确认删除备份“{record.name}”吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            with RemoteDeployer(profile, _SilentLogger()) as deployer:
                deployer.delete_backup(record)
            self.state.backups = [item for item in dialog.backups if item.id != backup_id]
            dialog.load_rows(self.state.backups)
            self.statusBar().showMessage("备份记录已删除")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "删除备份", str(exc))

    def on_backup_metadata_saved(
        self,
        dialog: BackupDialog,
        profile: DeploymentProfile,
        record: BackupRecord,
    ) -> None:
        if not record.name.strip():
            QMessageBox.warning(self, "保存失败", "备份名称不能为空。")
            return
        try:
            with RemoteDeployer(profile, _SilentLogger()) as deployer:
                deployer.save_backup_record(record)
            self.state.backups = [
                record if item.id == record.id else item
                for item in dialog.backups
            ]
            dialog.load_rows(self.state.backups, selected_backup_id=record.id)
            self.statusBar().showMessage("备份信息已保存")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存备份信息", str(exc))

    def refresh_backup_dialog(self, dialog: BackupDialog, profile: DeploymentProfile) -> None:
        selected_backup_id = dialog.selected_backup_id()
        try:
            backups = self.load_remote_backups(profile)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "刷新备份", str(exc))
            return
        dialog.load_rows(backups, selected_backup_id=selected_backup_id)

    def load_remote_backups(self, profile: DeploymentProfile) -> list[BackupRecord]:
        self.validate_backup_browser_profile(profile)
        with RemoteDeployer(profile, _SilentLogger()) as deployer:
            backups = deployer.list_backups()
        self.state.backups = backups
        return backups

    def validate_backup_browser_profile(self, profile: DeploymentProfile) -> None:
        if not profile.host.strip():
            raise ValueError("请先填写 Linux 主机 IP，再打开备份管理。")
        if not profile.username.strip():
            raise ValueError("请先填写 Linux 用户名，再打开备份管理。")
        if not profile.password:
            raise ValueError("请先填写 Linux 密码，再打开备份管理。")
        if not profile.target_path.strip():
            raise ValueError("请先填写 Linux 目标路径，再打开备份管理。")
        if profile.source_type == SOURCE_TYPE_FILE and not profile.source_path.strip():
            raise ValueError("文件模式下请先填写源文件路径，再打开备份管理。")

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

    def current_log_file_for_profile(self, profile: DeploymentProfile) -> str:
        if profile.id == self.running_profile_id:
            return self.current_log_file
        return ""

    def latest_history_for_profile(self, profile_id: str) -> HistoryRecord | None:
        return next(
            (
                record
                for record in self.state.history
                if record.profile_id == profile_id and record.log_file
            ),
            None,
        )

    def prepare_runtime_view_for_operation(self, profile: DeploymentProfile) -> None:
        if self.active_profile_id != profile.id:
            return
        self.clear_log()
        self.progress_bar.setValue(0)
        self.current_file_label.setText("准备执行...")
        self.progress_detail_label.setText("-")

    def refresh_profile_runtime_view(self, profile: DeploymentProfile | None = None) -> None:
        current_profile = profile or self.current_profile()
        if current_profile.id == self.running_profile_id and self.current_log_file:
            self.load_log_preview(
                self.current_log_file,
                file_text=Path(self.current_log_file).name,
                detail="执行中",
            )
            return
        history = self.latest_history_for_profile(current_profile.id)
        if history is None:
            self.progress_bar.setValue(0)
            self.current_file_label.setText("尚未开始")
            self.progress_detail_label.setText("当前配置暂无部署日志")
            self.log_edit.setPlainText("当前配置暂无部署日志。")
            return
        detail = f"{history.started_at} | {'成功' if history.success else '失败'}"
        self.load_log_preview(history.log_file, file_text=Path(history.log_file).name, detail=detail)

    def load_log_preview(self, path: str, *, file_text: str, detail: str) -> None:
        self.progress_bar.setValue(0)
        self.current_file_label.setText(file_text)
        self.progress_detail_label.setText(detail)
        try:
            self.log_edit.setPlainText(read_local_tail(path, _INLINE_LOG_LINES))
        except Exception as exc:  # noqa: BLE001
            self.log_edit.setPlainText(f"[错误] {exc}")

    def export_log(self) -> None:
        if not self.log_edit.toPlainText():
            QMessageBox.information(self, "导出日志", "当前没有可导出的日志。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", self.current_log_file or "deploy.log")
        if path:
            Path(path).write_text(self.log_edit.toPlainText(), encoding="utf-8")
            self.statusBar().showMessage(f"日志已导出到 {path}")
