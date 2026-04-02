# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Run the app (development)
python -m hospital_deploy_tool

# Run with self-check (headless smoke test)
python -m hospital_deploy_tool --self-check

# Install dependencies
python -m pip install -r requirements.txt

# Build exe (requires Python 3.10 venv at .venv310)
.\build_exe.bat
```

Build output: `dist\HospitalDeployTool.exe`

## Architecture

PySide2 desktop app targeting Windows. No tests. Entry point: `launch.py` → `hospital_deploy_tool/main.py`.

**Layer separation:**

| Module | Role |
|---|---|
| `models.py` | Pure dataclasses: `DeploymentProfile`, `BackupRecord`, `HistoryRecord` |
| `storage.py` | JSON persistence (`AppState`). Config path resolved by `constants.get_config_path()` |
| `remote.py` | All SSH/SFTP logic via paramiko (`RemoteDeployer` context manager) |
| `targeting.py` | Pure function `resolve_file_target()` — determines final remote deploy path for file mode |
| `workers.py` | `OperationWorker(QObject)` — runs `RemoteDeployer` on a `QThread`, emits signals back to UI |
| `ui/main_window.py` | `MainWindow(ProfileActions, OperationActions, QMainWindow)` — builds all widgets |
| `ui/profile_actions.py` | Mixin: profile CRUD, form fill/snapshot, source browsing |
| `ui/operation_actions.py` | Mixin: worker lifecycle, backup/history dialogs, log export |
| `ui/dialogs.py` | `BackupDialog`, `HistoryDialog`, `LogViewerDialog` |
| `ui/theme.py` | `APP_STYLESHEET` — single QSS string |
| `runlog.py` | `RunLogger` — writes timestamped lines to file and forwards to UI via callback |

**Config file location:**
- Dev: `%LOCALAPPDATA%\Hospital Deploy Tool\config.json` (or `config.json` in CWD if it exists)
- Packaged exe: `config.json` next to the exe

**Source types:** `file` / `directory` / `archive` (`.tar.gz`/`.tgz`)

**Actions:** `deploy` (backup + upload + commands) | `upload_only` | `commands_only` | `test_connection` | `restore_backup`

**Deploy flow (file mode):** `targeting.resolve_file_target()` resolves the actual remote path → backup existing file via `cp -a` → SFTP upload → run post-commands → prune old backups.

**Deploy flow (directory/archive mode):** backup target dir as `.tar.gz` → clear target dir → upload files or extract archive → run post-commands.

## Key Conventions

- `MainWindow` uses multiple inheritance from two mixin classes; all UI widget attributes are set on `self` in `main_window.py` and accessed by both mixins.
- `OperationWorker` is moved to a `QThread` — never call Qt UI methods from inside `worker.run()`.
- `RemoteDeployer` is a context manager; always use `with RemoteDeployer(...) as deployer`.
- All remote shell commands go through `RemoteDeployer.run_command()` which raises `RuntimeError` on non-zero exit by default.
- `shlex.quote()` is used on every remote path argument — maintain this for all new shell commands.
- `constants.py` owns all string constants and path resolution logic; do not hardcode paths elsewhere.
