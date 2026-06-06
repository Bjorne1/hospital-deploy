from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hospital_deploy_tool.constants import ACTION_UPLOAD_ONLY
from hospital_deploy_tool.models import DeploymentProfile
from hospital_deploy_tool.workers import OperationWorker


class ProgressEstimateTests(unittest.TestCase):
    def make_worker(self) -> OperationWorker:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return OperationWorker(
            ACTION_UPLOAD_ONLY,
            DeploymentProfile(),
            Path(temp_dir.name) / "deploy.log",
        )

    def test_progress_detail_includes_speed_and_estimated_finish_time(self) -> None:
        worker = self.make_worker()
        worker.update_progress_timer(total_sent=0, total_bytes=2000, now=100.0)
        worker.update_progress_timer(total_sent=1000, total_bytes=2000, now=110.0)

        detail = worker.format_progress_detail(
            file_sent=1000,
            file_total=2000,
            total_sent=1000,
            total_bytes=2000,
            now=110.0,
        )

        self.assertIn("1000.0 B / 2.0 KB", detail)
        self.assertIn("总计 1000.0 B / 2.0 KB", detail)
        self.assertIn("\n速度", detail)
        self.assertIn("速度 100.0 B/s", detail)
        self.assertIn("剩余 10秒", detail)
        self.assertRegex(detail, r"预计完成 \d{2}:\d{2}:\d{2}")

    def test_progress_timer_resets_when_total_size_changes(self) -> None:
        worker = self.make_worker()
        worker.update_progress_timer(total_sent=1000, total_bytes=4000, now=100.0)
        worker.update_progress_timer(total_sent=2000, total_bytes=4000, now=110.0)
        worker.update_progress_timer(total_sent=0, total_bytes=800, now=120.0)

        detail = worker.format_transfer_estimate(total_sent=400, total_bytes=800, now=124.0)

        self.assertIn("速度 100.0 B/s", detail)
        self.assertIn("剩余 4秒", detail)


if __name__ == "__main__":
    unittest.main()
