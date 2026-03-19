from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class ResolvedFileTarget:
    deploy_path: str
    is_directory_target: bool


def resolve_file_target(
    source_path: str,
    target_path: str,
    path_exists: Callable[[str], bool],
    is_dir: Callable[[str], bool],
    is_file: Callable[[str], bool],
) -> ResolvedFileTarget:
    normalized = target_path.rstrip("/") or "/"
    source_name = Path(source_path).name
    if path_exists(target_path):
        if is_dir(target_path):
            return ResolvedFileTarget(
                deploy_path=posixpath.join(normalized, source_name),
                is_directory_target=True,
            )
        if is_file(target_path):
            return ResolvedFileTarget(
                deploy_path=target_path,
                is_directory_target=False,
            )
        raise RuntimeError("目标路径已存在，但既不是普通文件也不是目录")
    if target_path.endswith("/"):
        return ResolvedFileTarget(
            deploy_path=posixpath.join(normalized, source_name),
            is_directory_target=True,
        )
    if posixpath.basename(normalized) == source_name:
        return ResolvedFileTarget(
            deploy_path=normalized,
            is_directory_target=False,
        )
    return ResolvedFileTarget(
        deploy_path=posixpath.join(normalized, source_name),
        is_directory_target=True,
    )
