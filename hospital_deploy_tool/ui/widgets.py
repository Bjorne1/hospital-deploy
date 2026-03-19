from __future__ import annotations

from PySide2.QtGui import QWheelEvent
from PySide2.QtWidgets import QSpinBox


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()
