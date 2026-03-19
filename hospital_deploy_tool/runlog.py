from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable


class RunLogger:
    def __init__(self, log_path: Path, sink: Callable[[str, str], None]) -> None:
        self.log_path = log_path
        self.sink = sink
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}"
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.sink(level, line)

    def info(self, message: str) -> None:
        self.emit("INFO", message)

    def success(self, message: str) -> None:
        self.emit("SUCCESS", message)

    def warning(self, message: str) -> None:
        self.emit("WARNING", message)

    def error(self, message: str) -> None:
        self.emit("ERROR", message)
