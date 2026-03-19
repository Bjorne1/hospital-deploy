from __future__ import annotations

import argparse
import sys

from PySide2.QtWidgets import QApplication

from .storage import Storage
from .ui.main_window import MainWindow


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-check", action="store_true")
    return parser.parse_args(argv[1:])


def run(argv: list[str] | None = None) -> int:
    args_list = argv or sys.argv
    args = parse_args(args_list)
    app = QApplication(args_list[:1])
    storage = Storage()
    state = storage.load()
    window = MainWindow(storage, state)
    if args.self_check:
        window.close()
        return 0
    window.show()
    return app.exec_()
