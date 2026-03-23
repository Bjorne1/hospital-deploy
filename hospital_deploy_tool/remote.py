from __future__ import annotations

import hashlib
import json
import os
import posixpath
import shlex
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import paramiko

from .constants import (
    ACTION_COMMANDS_ONLY,
    ACTION_UPLOAD_ONLY,
    DEFAULT_BACKUP_ROOT,
    SOURCE_TYPE_ARCHIVE,
    SOURCE_TYPE_DIRECTORY,
)
from .models import BackupRecord, DeploymentProfile, default_backup_name
from .targeting import resolve_file_target


ProgressCallback = Callable[[str, int, int, int, int, int, int], None]


@dataclass(slots=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class DeployResult:
    backup_record: BackupRecord | None
    deleted_backups: list[BackupRecord]
    deployed_target_path: str


class RemoteDeployer:
    def __init__(self, profile: DeploymentProfile, logger) -> None:
        self.profile = profile
        self.logger = logger
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.sftp: paramiko.SFTPClient | None = None

    def __enter__(self) -> "RemoteDeployer":
        self.connect()
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def connect(self) -> None:
        self.logger.info(f"连接 {self.profile.host}:{self.profile.port}")
        self.client.connect(
            hostname=self.profile.host,
            port=self.profile.port,
            username=self.profile.username,
            password=self.profile.password,
            timeout=15,
            banner_timeout=15,
            auth_timeout=15,
        )
        self.sftp = self.client.open_sftp()
        self.logger.success("SSH/SFTP 连接成功")

    def close(self) -> None:
        if self.sftp:
            self.sftp.close()
        self.client.close()

    def test_connection(self) -> None:
        result = self.run_command("uname -a")
        self.logger.info(result.stdout.strip() or "远端连通性检查完成")

    def deploy(self, action: str, progress: ProgressCallback) -> DeployResult:
        backup = None
        deleted: list[BackupRecord] = []
        if action != ACTION_COMMANDS_ONLY:
            backup = self.prepare_backup()
            self.upload_source(progress)
        if action != ACTION_UPLOAD_ONLY:
            self.run_post_commands()
        if backup:
            deleted = self.prune_backups()
        return DeployResult(
            backup_record=backup,
            deleted_backups=deleted,
            deployed_target_path=self.deployed_target_path(),
        )

    def restore_backup(self, record: BackupRecord, run_post_commands: bool = False) -> None:
        self.logger.info(f"恢复备份: {record.remote_backup_path}")
        if record.source_type in {SOURCE_TYPE_DIRECTORY, SOURCE_TYPE_ARCHIVE}:
            self.restore_directory(record.remote_backup_path, record.target_path)
        else:
            self.restore_file(record.remote_backup_path, record.target_path)
        if run_post_commands:
            self.run_post_commands()
        self.logger.success("备份恢复完成")

    def prepare_backup(self) -> BackupRecord | None:
        if not self.profile.backup_enabled:
            self.logger.warning("已禁用备份，跳过备份阶段")
            return None
        if self.profile.source_type in {SOURCE_TYPE_DIRECTORY, SOURCE_TYPE_ARCHIVE}:
            return self.backup_directory()
        return self.backup_file()

    def upload_source(self, progress: ProgressCallback) -> None:
        if self.profile.source_type == SOURCE_TYPE_ARCHIVE:
            self.upload_archive(progress)
        elif self.profile.source_type == SOURCE_TYPE_DIRECTORY and self.profile.compress_upload:
            self.upload_compressed_directory(progress)
        elif self.profile.source_type == SOURCE_TYPE_DIRECTORY:
            self.upload_directory(progress)
        else:
            self.upload_file(progress)

    def backup_file(self) -> BackupRecord | None:
        target = self.deployed_target_path()
        if not self.path_exists(target):
            self.logger.info("目标文件不存在，跳过文件备份")
            return None
        if not self.is_file(target):
            raise RuntimeError("目标路径已存在，但不是文件，无法按文件模式覆盖")
        backup_dir = self.backup_payload_dir()
        backup_path = posixpath.join(backup_dir, self.file_backup_name(target))
        self.ensure_backup_dirs()
        self.run_command(f"cp -a {shlex.quote(target)} {shlex.quote(backup_path)}")
        size = self.remote_size(backup_path)
        self.logger.success(f"文件备份完成: {backup_path}")
        record = self.make_backup_record(backup_path, "file", target, size)
        self.save_backup_record(record)
        return record

    def backup_directory(self) -> BackupRecord | None:
        if not self.path_exists(self.profile.target_path):
            self.logger.info("目标目录不存在，跳过目录备份")
            return None
        if not self.is_dir(self.profile.target_path):
            raise RuntimeError("目标路径已存在，但不是目录，无法按目录模式部署")
        backup_dir = self.backup_payload_dir()
        backup_path = posixpath.join(backup_dir, self.dir_backup_name())
        parent = posixpath.dirname(self.profile.target_path.rstrip("/")) or "/"
        name = posixpath.basename(self.profile.target_path.rstrip("/"))
        self.ensure_backup_dirs()
        command = f"tar -czf {shlex.quote(backup_path)} -C {shlex.quote(parent)} {shlex.quote(name)}"
        self.run_command(command)
        size = self.remote_size(backup_path)
        self.logger.success(f"目录备份完成: {backup_path}")
        record = self.make_backup_record(backup_path, "directory", self.profile.target_path, size)
        self.save_backup_record(record)
        return record

    def upload_file(self, progress: ProgressCallback) -> None:
        source = Path(self.profile.source_path)
        target = self.deployed_target_path()
        parent = posixpath.dirname(target) or "."
        self.ensure_dir(parent)
        self.logger.info(f"上传文件到 {target}")
        self.sftp_put(source, target, 1, 1, 0, source.stat().st_size, progress)
        self.logger.success("文件上传完成")

    def upload_directory(self, progress: ProgressCallback) -> None:
        source = Path(self.profile.source_path)
        files = self.collect_files(source)
        self.ensure_dir(self.profile.target_path)
        self.clear_directory(self.profile.target_path)
        total_files = len(files)
        total_bytes = sum(item.stat().st_size for item in files)
        if total_files == 0:
            self.logger.warning("源目录为空，目标目录已清空")
            return
        self.logger.info(f"开始上传目录内容，共 {total_files} 个文件")
        sent_before = 0
        for index, item in enumerate(files, start=1):
            relative = item.relative_to(source).as_posix()
            target = posixpath.join(self.profile.target_path, relative)
            self.ensure_dir(posixpath.dirname(target))
            self.sftp_put(
                item,
                target,
                index,
                total_files,
                sent_before,
                total_bytes,
                progress,
            )
            sent_before += item.stat().st_size
        self.logger.success("目录上传完成")

    def upload_archive(self, progress: ProgressCallback) -> None:
        source = Path(self.profile.source_path)
        target_path = self.profile.target_path
        remote_tmp = posixpath.join("/tmp", f"deploy_{source.name}")
        self.ensure_dir(target_path)
        self.clear_directory(target_path)
        self.logger.info(f"上传压缩文件到远端临时路径 {remote_tmp}")
        self.sftp_put(source, remote_tmp, 1, 1, 0, source.stat().st_size, progress)
        self.logger.info("远端解压中...")
        self.run_command(
            f"tar -xzf {shlex.quote(remote_tmp)} -C {shlex.quote(target_path)}"
        )
        self.run_command(f"rm -f {shlex.quote(remote_tmp)}")
        self.logger.success("压缩文件上传并解压完成")

    def upload_compressed_directory(self, progress: ProgressCallback) -> None:
        source = Path(self.profile.source_path)
        target_path = self.profile.target_path
        local_tmp = None
        try:
            self.logger.info("本地打包目录为 tar.gz...")
            fd, local_tmp = tempfile.mkstemp(suffix=".tar.gz")
            os.close(fd)
            with tarfile.open(local_tmp, "w:gz") as tar:
                tar.add(str(source), arcname=".")
            local_archive = Path(local_tmp)
            remote_tmp = posixpath.join("/tmp", f"deploy_compressed_{local_archive.name}")
            self.ensure_dir(target_path)
            self.clear_directory(target_path)
            self.logger.info(f"上传压缩包到远端临时路径 {remote_tmp}")
            self.sftp_put(local_archive, remote_tmp, 1, 1, 0, local_archive.stat().st_size, progress)
            self.logger.info("远端解压中...")
            self.run_command(
                f"tar -xzf {shlex.quote(remote_tmp)} -C {shlex.quote(target_path)}"
            )
            self.run_command(f"rm -f {shlex.quote(remote_tmp)}")
            self.logger.success("目录压缩上传并解压完成")
        finally:
            if local_tmp and Path(local_tmp).exists():
                Path(local_tmp).unlink()

    def run_post_commands(self) -> None:
        commands = [cmd.strip() for cmd in self.profile.post_commands if cmd.strip()]
        if not commands:
            self.logger.info("未配置后置命令，跳过命令阶段")
            return
        for index, command in enumerate(commands, start=1):
            self.logger.info(f"执行命令 {index}/{len(commands)}: {command}")
            result = self.run_command(command)
            if result.stdout.strip():
                self.logger.info(result.stdout.strip())
            if result.stderr.strip():
                self.logger.warning(result.stderr.strip())
        self.logger.success("后置命令执行完成")

    def prune_backups(self) -> list[BackupRecord]:
        records = [item for item in self.list_backups() if not item.favorite]
        if len(records) <= self.profile.max_backup_count:
            return []
        deleted: list[BackupRecord] = []
        for record in records[self.profile.max_backup_count :]:
            self.delete_backup(record)
            deleted.append(record)
            self.logger.warning(f"滚动删除旧备份: {record.remote_backup_path}")
        return deleted

    def restore_file(self, backup_path: str, target_path: str) -> None:
        self.ensure_dir(posixpath.dirname(target_path) or ".")
        self.run_command(f"cp -a {shlex.quote(backup_path)} {shlex.quote(target_path)}")

    def restore_directory(self, backup_path: str, target_path: str) -> None:
        parent = posixpath.dirname(target_path.rstrip("/")) or "/"
        self.run_command(f"rm -rf {shlex.quote(target_path)}")
        self.ensure_dir(parent)
        self.run_command(f"tar -xzf {shlex.quote(backup_path)} -C {shlex.quote(parent)}")

    def clear_directory(self, target_path: str) -> None:
        command = f"find {shlex.quote(target_path)} -mindepth 1 -maxdepth 1 -exec rm -rf {{}} +"
        self.run_command(command)

    def collect_files(self, source: Path) -> list[Path]:
        return [item for item in source.rglob("*") if item.is_file()]

    def sftp_put(
        self,
        source: Path,
        target: str,
        index: int,
        total_files: int,
        sent_before: int,
        aggregate_total: int,
        progress: ProgressCallback,
    ) -> None:
        file_total = source.stat().st_size
        total_bytes = aggregate_total or file_total
        progress(source.name, 0, file_total, sent_before, total_bytes, index, total_files)

        def callback(sent: int, file_total: int) -> None:
            progress(
                source.name,
                sent,
                file_total,
                sent_before + sent,
                total_bytes,
                index,
                total_files,
            )

        assert self.sftp is not None
        self.sftp.put(str(source), target, callback=callback)

    def remote_size(self, remote_path: str) -> int:
        assert self.sftp is not None
        try:
            return self.sftp.stat(remote_path).st_size or 0
        except OSError:
            return 0

    def path_exists(self, remote_path: str) -> bool:
        assert self.sftp is not None
        try:
            self.sftp.stat(remote_path)
            return True
        except OSError:
            return False

    def is_file(self, remote_path: str) -> bool:
        return self.run_command(f"test -f {shlex.quote(remote_path)}", check=False).exit_code == 0

    def is_dir(self, remote_path: str) -> bool:
        return self.run_command(f"test -d {shlex.quote(remote_path)}", check=False).exit_code == 0

    def ensure_dir(self, remote_path: str) -> None:
        self.run_command(f"mkdir -p {shlex.quote(remote_path)}")

    def ensure_backup_dirs(self) -> None:
        self.ensure_dir(self.backup_payload_dir())
        self.ensure_dir(self.backup_records_dir())

    def list_backups(self) -> list[BackupRecord]:
        records_dir = self.backup_records_dir()
        if not self.path_exists(records_dir):
            return []
        assert self.sftp is not None
        records: list[BackupRecord] = []
        for item in self.sftp.listdir_attr(records_dir):
            if not item.filename.endswith(".json"):
                continue
            remote_path = posixpath.join(records_dir, item.filename)
            try:
                payload = json.loads(self.read_remote_text(remote_path))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"备份元数据损坏: {remote_path} ({exc})") from exc
            record = BackupRecord.from_dict(payload)
            record.metadata_path = remote_path
            if not record.scope_key:
                record.scope_key = self.backup_scope_key()
            if not record.name.strip():
                record.name = default_backup_name(record.created_at)
            records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        records.sort(key=lambda item: 0 if item.favorite else 1)
        return records

    def save_backup_record(self, record: BackupRecord) -> None:
        record.scope_key = self.backup_scope_key()
        record.metadata_path = self.backup_metadata_path(record.id)
        self.ensure_backup_dirs()
        self.write_remote_text(
            record.metadata_path,
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
        )

    def delete_backup(self, record: BackupRecord) -> None:
        if record.remote_backup_path:
            self.run_command(f"rm -f {shlex.quote(record.remote_backup_path)}", check=False)
        metadata_path = record.metadata_path or self.backup_metadata_path(record.id)
        self.run_command(f"rm -f {shlex.quote(metadata_path)}", check=False)

    def profile_backup_dir(self) -> str:
        return posixpath.join(self.backup_root_path(), self.backup_scope_dir_name())

    def backup_root_path(self) -> str:
        return DEFAULT_BACKUP_ROOT

    def backup_payload_dir(self) -> str:
        return posixpath.join(self.profile_backup_dir(), "payloads")

    def backup_records_dir(self) -> str:
        return posixpath.join(self.profile_backup_dir(), "records")

    def backup_metadata_path(self, backup_id: str) -> str:
        return posixpath.join(self.backup_records_dir(), f"{backup_id}.json")

    def backup_scope_dir_name(self) -> str:
        return f"{self.safe_remote_name(self.backup_scope_label())}_{self.backup_scope_key()}"

    def backup_scope_key(self) -> str:
        raw = f"{self.profile.source_type}|{self.backup_scope_target_path()}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def backup_scope_label(self) -> str:
        target = self.backup_scope_target_path().rstrip("/")
        if target == "":
            return "root"
        return posixpath.basename(target) or "root"

    def backup_scope_target_path(self) -> str:
        if self.profile.source_type in {SOURCE_TYPE_DIRECTORY, SOURCE_TYPE_ARCHIVE}:
            return self.profile.target_path.rstrip("/") or "/"
        resolved = resolve_file_target(
            self.profile.source_path,
            self.profile.target_path,
            self.path_exists,
            self.is_dir,
            self.is_file,
        )
        return resolved.deploy_path.rstrip("/") or "/"

    def safe_remote_name(self, value: str) -> str:
        text = value.strip() or "backup"
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)

    def file_backup_name(self, target_path: str) -> str:
        target = posixpath.basename(target_path)
        return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{target}"

    def dir_backup_name(self) -> str:
        target = posixpath.basename(self.profile.target_path.rstrip("/")) or "backup"
        return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{target}.tar.gz"

    def make_backup_record(self, remote_path: str, mode: str, target_path: str, size: int = 0) -> BackupRecord:
        created_at = datetime.now().isoformat(timespec="seconds")
        return BackupRecord(
            profile_id=self.profile.id,
            profile_name=self.profile.name,
            host=self.profile.host,
            target_path=target_path,
            source_type=self.profile.source_type,
            remote_backup_path=remote_path,
            backup_mode=mode,
            backup_size=size,
            created_at=created_at,
            name=default_backup_name(created_at),
            scope_key=self.backup_scope_key(),
            post_commands=list(self.profile.post_commands),
        )

    def deployed_target_path(self) -> str:
        if self.profile.source_type in {SOURCE_TYPE_DIRECTORY, SOURCE_TYPE_ARCHIVE}:
            return self.profile.target_path
        resolved = resolve_file_target(
            self.profile.source_path,
            self.profile.target_path,
            self.path_exists,
            self.is_dir,
            self.is_file,
        )
        return resolved.deploy_path

    def read_remote_log(self, path: str, lines: int = 500) -> str:
        result = self.run_command(f"tail -n {lines} {shlex.quote(path)}", check=False)
        if result.exit_code != 0:
            raise RuntimeError(result.stderr.strip() or f"无法读取日志: {path}")
        return result.stdout

    def run_command(self, command: str, check: bool = True) -> CommandResult:
        stdin, stdout, stderr = self.client.exec_command(command)
        stdin.close()
        exit_code = stdout.channel.recv_exit_status()
        result = CommandResult(
            exit_code=exit_code,
            stdout=stdout.read().decode("utf-8", errors="replace"),
            stderr=stderr.read().decode("utf-8", errors="replace"),
        )
        if check and exit_code != 0:
            raise RuntimeError(result.stderr.strip() or f"命令执行失败: {command}")
        return result

    def read_remote_text(self, remote_path: str) -> str:
        assert self.sftp is not None
        with self.sftp.file(remote_path, "rb") as handle:
            return handle.read().decode("utf-8", errors="replace")

    def write_remote_text(self, remote_path: str, text: str) -> None:
        assert self.sftp is not None
        with self.sftp.file(remote_path, "wb") as handle:
            handle.write(text.encode("utf-8"))
