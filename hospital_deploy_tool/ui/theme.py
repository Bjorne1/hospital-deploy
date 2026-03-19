from __future__ import annotations

APP_STYLESHEET = """
QWidget {
    background: #f6f8fb;
    color: #1f2937;
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #d8dee9;
    border-radius: 10px;
    margin-top: 12px;
    padding: 14px;
    background: #ffffff;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QTableWidget {
    border: 1px solid #c9d3e0;
    border-radius: 8px;
    background: #ffffff;
    padding: 6px;
}
QPushButton {
    border: 0;
    border-radius: 8px;
    background: #2563eb;
    color: white;
    padding: 8px 14px;
    min-height: 18px;
}
QPushButton:hover { background: #1d4ed8; }
QPushButton[role="secondary"] { background: #dbeafe; color: #1d4ed8; }
QPushButton[role="danger"] { background: #ef4444; color: white; }
QPushButton[role="muted"] { background: #e5e7eb; color: #111827; }
QLabel[role="muted"] { color: #6b7280; }
QLabel[role="success"] { color: #15803d; font-weight: 700; }
QLabel[role="warning"] { color: #c2410c; font-weight: 700; }
QLabel[role="error"] { color: #b91c1c; font-weight: 700; }
QProgressBar {
    border: 1px solid #d8dee9;
    border-radius: 8px;
    background: #ffffff;
    text-align: center;
    min-height: 18px;
}
QProgressBar::chunk {
    border-radius: 7px;
    background: #2563eb;
}
QStatusBar {
    background: #eef2f7;
}
"""
