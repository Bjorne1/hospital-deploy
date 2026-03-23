from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from PySide2.QtCore import QObject, Signal

from .constants import (
    ACTION_COMMANDS_ONLY,
    ACTION_DEPLOY,
    ACTION_RESTORE_BACKUP,
    ACTION_TEST_CONNECTION,
    ACTION_UPLOAD_ONLY,
    SOURCE_TYPE_ARCHIVE,
    SOURCE_TYPE_DIRECTORY,
)
from .models import BackupRecord, DeploymentProfile
from .remote import RemoteDeployer
from .runlog import RunLogger


class OperationWorker(QObject):
    finished = Signal(bool, object)
    log_emitted = Signal(str, str)
    status_changed = Signal(str)
    progress_changed = Signal(int, str, str)

    def __init__(
        self,
        action: str,
        profile: DeploymentProfile,
        log_path: Path,
        backup_record: BackupRecord | None = None,
        run_post_commands_after_restore: bool = False,
    ) -> None:
        super().__init__()
        self.action = action
        self.profile = profile
        self.log_path = log_path
        self.backup_record = backup_record
        self.run_post_commands_after_restore = run_post_commands_after_restore
        self.started_at = datetime.now()
        self.logger = RunLogger(log_path, self.forward_log)

    def run(self) -> None:
        try:
            self.status_changed.emit(self.status_label())
            self.logger.info(f"开始执行操作: {self.action}")
            self.validate_inputs()
            payload = self.execute()
            payload.update(self.common_payload(True, "操作成功"))
            self.finished.emit(True, payload)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(str(exc))
            payload = self.common_payload(False, str(exc))
            self.finished.emit(False, payload)

    def execute(self) -> dict[str, object]:
        with RemoteDeployer(self.profile, self.logger) as deployer:
            if self.action == ACTION_TEST_CONNECTION:
                deployer.test_connection()
                return {"backup_record": None, "deleted_backups": []}
            if self.action == ACTION_RESTORE_BACKUP:
                assert self.backup_record is not None
                deployer.restore_backup(
                    self.backup_record,
                    run_post_commands=self.run_post_commands_after_restore,
                )
                return {"backup_record": None, "deleted_backups": []}
            result = deployer.deploy(self.action, self.on_progress)
            return {
                "backup_record": result.backup_record,
                "deleted_backups": result.deleted_backups,
                "deployed_target_path": result.deployed_target_path,
            }

    def validate_inputs(self) -> None:
        if not self.profile.host.strip():
            raise ValueError("Linux 主机 IP 不能为空")
        if not self.profile.username.strip():
            raise ValueError("Linux 用户名不能为空")
        if not self.profile.password:
            raise ValueError("Linux 密码不能为空")
        if self.action in {ACTION_DEPLOY, ACTION_UPLOAD_ONLY}:
            self.validate_source()
            self.validate_target()
        if self.action == ACTION_COMMANDS_ONLY and not self.profile.post_commands:
            raise ValueError("未配置后置命令，无法执行“仅执行命令”")
        if self.action == ACTION_RESTORE_BACKUP and self.backup_record is None:
            raise ValueError("未选择需要恢复的备份")

    def validate_source(self) -> None:
        source = Path(self.profile.source_path)
        if not self.profile.source_path.strip():
            raise ValueError("源路径不能为空")
        if not source.exists():
            raise ValueError(f"源路径不可访问: {self.profile.source_path}")
        if self.profile.source_type == SOURCE_TYPE_ARCHIVE:
            if not source.is_file():
                raise ValueError("当前源类型是压缩文件，但源路径不是文件")
            lower = source.name.lower()
            if not (lower.endswith(".tar.gz") or lower.endswith(".tgz")):
                raise ValueError("压缩文件必须是 .tar.gz 或 .tgz 格式")
        elif self.profile.source_type == SOURCE_TYPE_DIRECTORY:
            if not source.is_dir():
                raise ValueError("当前源类型是目录，但源路径不是目录")
        else:
            if not source.is_file():
                raise ValueError("当前源类型是文件，但源路径不是文件")

    def validate_target(self) -> None:
        if not self.profile.target_path.strip():
            raise ValueError("Linux 目标路径不能为空")

    def on_progress(
        self,
        current_file: str,
        file_sent: int,
        file_total: int,
        total_sent: int,
        total_bytes: int,
        index: int,
        total_files: int,
    ) -> None:
        percent = 0 if total_bytes == 0 else min(100, int(total_sent * 100 / total_bytes))
        file_text = f"{index}/{total_files} {current_file}"
        detail = f"{self.format_size(file_sent)} / {self.format_size(file_total)}"
        self.progress_changed.emit(percent, file_text, detail)

    def common_payload(self, success: bool, summary: str) -> dict[str, object]:
        ended = datetime.now()
        duration = round((ended - self.started_at).total_seconds(), 2)
        return {
            "action": self.action,
            "success": success,
            "summary": summary,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "ended_at": ended.isoformat(timespec="seconds"),
            "duration_seconds": duration,
            "log_file": str(self.log_path),
        }

    def status_label(self) -> str:
        mapping = {
            ACTION_DEPLOY: "部署中",
            ACTION_UPLOAD_ONLY: "上传中",
            ACTION_COMMANDS_ONLY: "执行命令中",
            ACTION_TEST_CONNECTION: "连接测试中",
            ACTION_RESTORE_BACKUP: "恢复备份中",
        }
        return mapping[self.action]

    def forward_log(self, level: str, line: str) -> None:
        self.log_emitted.emit(level, line)

    def format_size(self, value: int) -> str:
        size = float(value)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{value} B"
