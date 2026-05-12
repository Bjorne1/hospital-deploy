from __future__ import annotations

from datetime import datetime
import unittest

from hospital_deploy_tool.models import BackupRecord, DeploymentProfile
from hospital_deploy_tool.remote import RemoteDeployer


class NoopLogger:
    def info(self, _message: str) -> None:
        pass

    def success(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass


class BackupVersionTimeTests(unittest.TestCase):
    def test_make_backup_record_uses_file_mtime(self) -> None:
        deployer = RemoteDeployer(DeploymentProfile(), NoopLogger())
        deployer.backup_scope_key = lambda: "scope"  # type: ignore[method-assign]
        deployer.remote_path_mtime_epoch = lambda _path: 1710000000.0

        record = deployer.make_backup_record("/remote/backup.txt", "file", "/remote/app.txt", 128)

        self.assertEqual(record.version_at, self.format_epoch(1710000000.0))

    def test_make_backup_record_uses_latest_directory_file_mtime(self) -> None:
        deployer = RemoteDeployer(DeploymentProfile(), NoopLogger())
        deployer.backup_scope_key = lambda: "scope"  # type: ignore[method-assign]
        seen: list[str] = []

        def latest_mtime(path: str) -> float | None:
            seen.append(path)
            return 1710000500.0

        deployer.remote_latest_file_mtime_epoch = latest_mtime
        deployer.remote_path_mtime_epoch = lambda _path: 1700000000.0

        record = deployer.make_backup_record("/remote/backup.tar.gz", "directory", "/remote/app", 256)

        self.assertEqual(seen, ["/remote/app"])
        self.assertEqual(record.version_at, self.format_epoch(1710000500.0))

    def test_backup_record_falls_back_to_created_time_for_legacy_payloads(self) -> None:
        record = BackupRecord.from_dict({"created_at": "2026-05-12T10:11:12"})

        self.assertEqual(record.display_version_time(), "2026-05-12 10:11:12")

    @staticmethod
    def format_epoch(value: float) -> str:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    unittest.main()
