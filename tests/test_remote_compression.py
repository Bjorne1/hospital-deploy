from __future__ import annotations

import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hospital_deploy_tool.models import DeploymentProfile
from hospital_deploy_tool.remote import (
    LOCAL_TAR_GZIP_COMPRESSLEVEL,
    RemoteDeployer,
)


class NoopLogger:
    def info(self, _message: str) -> None:
        pass

    def success(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass


class FakeTar:
    def __enter__(self) -> "FakeTar":
        return self

    def __exit__(self, *_args) -> None:
        pass

    def add(self, *_args, **_kwargs) -> None:
        pass


class RemoteCompressionTests(unittest.TestCase):
    def test_create_directory_archive_uses_fast_compression_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "dist"
            source.mkdir()
            (source / "index.html").write_text("ok", encoding="utf-8")
            archive = Path(temp_dir) / "dist.tar.gz"
            deployer = RemoteDeployer(DeploymentProfile(), NoopLogger())
            events = []

            with patch("hospital_deploy_tool.remote.tarfile.open") as open_mock:
                open_mock.return_value = FakeTar()
                deployer.create_directory_archive(
                    source,
                    archive,
                    lambda *args: events.append(args),
                )

            self.assertEqual(
                open_mock.call_args.kwargs["compresslevel"],
                LOCAL_TAR_GZIP_COMPRESSLEVEL,
            )
            self.assertEqual(LOCAL_TAR_GZIP_COMPRESSLEVEL, 1)
            self.assertTrue(events)

    def test_create_directory_archive_keeps_directory_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "dist"
            (source / "assets").mkdir(parents=True)
            (source / "index.html").write_text("index", encoding="utf-8")
            (source / "assets" / "app.js").write_text("app", encoding="utf-8")
            archive = Path(temp_dir) / "dist.tar.gz"
            deployer = RemoteDeployer(DeploymentProfile(), NoopLogger())

            deployer.create_directory_archive(source, archive, lambda *_args: None)

            with tarfile.open(archive, "r:gz") as tar:
                names = set(tar.getnames())

            self.assertIn(".", names)
            self.assertIn("index.html", names)
            self.assertIn("assets", names)
            self.assertIn("assets/app.js", names)


if __name__ == "__main__":
    unittest.main()
