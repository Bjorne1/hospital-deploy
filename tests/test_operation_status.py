from __future__ import annotations

import unittest
from unittest.mock import Mock

from hospital_deploy_tool.constants import ACTION_DEPLOY, ACTION_UPLOAD_ONLY
from hospital_deploy_tool.models import BackupRecord, DeploymentProfile
from hospital_deploy_tool.remote import RemoteDeployer


class NoopLogger:
    def info(self, _message: str) -> None:
        pass

    def success(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass


class OperationStatusTests(unittest.TestCase):
    def make_deployer(self, profile: DeploymentProfile, statuses: list[str]) -> RemoteDeployer:
        return RemoteDeployer(profile, NoopLogger(), status_callback=statuses.append)

    def test_full_deploy_reports_execution_phases_in_order(self) -> None:
        statuses: list[str] = []
        profile = DeploymentProfile(post_commands=["systemctl restart app"])
        backup = BackupRecord(remote_backup_path="/backup/app.tar.gz")
        deployer = self.make_deployer(profile, statuses)
        deployer.prepare_backup = Mock(return_value=backup)  # type: ignore[method-assign]
        deployer.upload_source = Mock()  # type: ignore[method-assign]
        deployer.run_post_commands = Mock()  # type: ignore[method-assign]
        deployer.prune_backups = Mock(return_value=[])  # type: ignore[method-assign]
        deployer.deployed_target_path = Mock(return_value="/opt/app")  # type: ignore[method-assign]

        result = deployer.deploy(ACTION_DEPLOY, lambda *_args: None)

        self.assertEqual(
            statuses,
            ["备份中", "上传中", "执行命令中", "清理旧备份中"],
        )
        self.assertIs(result.backup_record, backup)

    def test_upload_only_skips_command_and_cleanup_status_without_backup(self) -> None:
        statuses: list[str] = []
        deployer = self.make_deployer(DeploymentProfile(), statuses)
        deployer.prepare_backup = Mock(return_value=None)  # type: ignore[method-assign]
        deployer.upload_source = Mock()  # type: ignore[method-assign]
        deployer.deployed_target_path = Mock(return_value="/opt/app")  # type: ignore[method-assign]

        deployer.deploy(ACTION_UPLOAD_ONLY, lambda *_args: None)

        self.assertEqual(statuses, ["备份中", "上传中"])

    def test_restore_with_post_commands_reports_restore_then_commands(self) -> None:
        statuses: list[str] = []
        deployer = self.make_deployer(DeploymentProfile(), statuses)
        record = BackupRecord(source_type="file", remote_backup_path="/backup/app.jar")
        deployer.restore_file = Mock()  # type: ignore[method-assign]
        deployer.run_post_commands = Mock()  # type: ignore[method-assign]

        deployer.restore_backup(record, run_post_commands=True)

        self.assertEqual(statuses, ["恢复备份中", "执行命令中"])


if __name__ == "__main__":
    unittest.main()
