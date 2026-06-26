# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**医院一键部署工具** — A Windows desktop app built with PySide2 + Paramiko. Deploys files/directories to remote Linux servers over SSH/SFTP. Designed to run on hospital remote-desktop machines.

## Build & Run Commands

```bash
# Install dependencies
python -m pip install -r requirements.txt

# Run in development
python -m hospital_deploy_tool

# Run via launch script
python launch.py

# Run tests
python -m pytest tests/ --tb=short

# Self-check (verify GUI can construct without errors, then exit)
python launch.py --self-check
```

### Build standalone .exe (requires Python 3.10 for PySide2 compatibility)

```powershell
py -3.10 -m venv .venv310
.\.venv310\Scripts\python.exe -m pip install -r requirements.txt
.\.venv310\Scripts\python.exe -m pip install pyinstaller
.\build_exe.bat
# Output: dist\HospitalDeployTool.exe
```

## Architecture

```
launch.py                  # Entry point. Handles frozen (PyInstaller) DLL path setup, then calls main.run()
hospital_deploy_tool/
  __init__.py, __main__.py # Package-level: __getattr__ lazy-loads run()
  main.py                  # QApplication init, Storage::load, MainWindow, app.exec_()
  constants.py             # APP_NAME, source types, action types, path resolution helpers
  models.py                # @dataclass: DeploymentProfile, BackupRecord, HistoryRecord (with to_dict/from_dict)
  storage.py               # Storage (JSON file in %LOCALAPPDATA%) + AppState dataclass
  remote.py                # RemoteDeployer — paramiko SSH/SFTP wrapper: connect, deploy, backup, restore, prune
  workers.py               # OperationWorker (QObject) — runs async in QThread, validates, executes, emits progress
  targeting.py             # resolve_file_target() — decides deploy_path for file-mode sources
  runlog.py                # RunLogger — writes timestamped log lines to file + forwards to UI sink
  log_history.py           # HistoryLogCache — catalogs & downloads remote aggregated-service log files by date
  log_tools.py             # Log filtering, time-range resolution, binary medical-record placeholder replacement
  ui/
    main_window.py         # MainWindow(QMainWindow + ProfileActions + OperationActions)
    profile_actions.py     # Mixin: profile CRUD, form fill, drag-reorder, search/filter
    operation_actions.py   # Mixin: test_connection, deploy/upload/commands, batch deploy, backup dialog, history
    log_workbench.py       # LogViewerDialog — local & remote log viewing with keyword/time/trace-id filters
    dialogs.py             # BackupDialog (QTableWidget with favorite markers, restore/delete)
    log_aux_dialogs.py     # HistoryDialog + HistoryLogBrowserDialog + LogPathConfigDialog + catalog worker thread
    widgets.py             # NoWheelSpinBox (QSpinBox that ignores scrollwheel)
    theme.py               # APP_STYLESHEET — global QSS stylesheet
```

## Key Design Patterns

**Mixin UI Composition.** `MainWindow` inherits from `ProfileActions`, `OperationActions`, and `QMainWindow` — profile management and operation orchestration are split into separate mixin classes that operate on shared state (`self.state`, `self.storage`) and widgets created in `main_window.py`.

**Qt Threading.** Every remote operation uses `QThread` + `OperationWorker`. The worker validates inputs, instantiates `RemoteDeployer` as a context manager, executes, and emits `finished(Signal(bool, object))`. Never block the main thread directly — always go through `start_worker()`.

**Batch Deploy.** `operation_actions.py` uses a `self.operation_queue` (list of `QueuedOperation`). After each worker finishes (`on_thread_finished`), it pops the next queued operation and starts it. `batch_stop_on_failure` clears the queue on first error.

**Config Persistence.** `Storage` reads/writes `config.json` in `%LOCALAPPDATA%\Hospital Deploy Tool\`. The `save()` method is called on every mutation (profile save, history add, backup insert). Backups stored on _remote server_ under `/opt/deploy-backups/{scope}/payloads/` and `/opt/deploy-backups/{scope}/records/`.

**Remote Path Resolution.** `targeting.py::resolve_file_target()` handles file-mode edge cases: if target_path is a directory on the remote, the file is uploaded with its source name into that directory; if target_path points to an existing file, it overwrites in place.

**Backup Scoping.** `RemoteDeployer` derives a scope key via SHA1 of `source_type|target_path`, so backups for the same target directory/file are co-located regardless of profile. This allows rolling-prune logic to work across profiles that share the same deploy target.

## Log Workbench

The log workbench (`log_workbench.py`) has two modes:

1. **Local logs** — reads files from `get_logs_dir()` (deploy operation logs)
2. **Service logs** — downloads aggregated logs from remote server at `log_path_default/error/debug/warn` (configured per-profile). Uses `HistoryLogCache` to catalog dates, download archives, and cache locally under `history-log-cache/`.

Log filtering (`log_tools.py`) groups lines into "events" (lines starting with timestamps) and filters by include/exclude/trace-id keywords and time range. Binary medical record content (XTextDocument, XElements, etc.) in JSON string values is automatically replaced with `【二进制病历】`.

## Profile Model

`DeploymentProfile` supports 3 source types:
- `file` — upload a single file (target can be a directory or file path)
- `directory` — upload directory contents (backup target → clear → upload). Optional `compress_upload` for tar.gz pipeline.
- `archive` — upload a `.tar.gz` file, extract on remote.

Profiles have `profile_kind` (unset/backend/frontend) for filtering in the UI. Each profile can optionally configure 4 remote log paths (`log_path_default/error/debug/warn`) for the log workbench.
