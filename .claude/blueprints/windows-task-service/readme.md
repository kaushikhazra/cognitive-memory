# Blueprint: Windows Task Service

Run any Python project as a Windows background service using Task Scheduler. No admin elevation, no pywin32 dependency, works with any Python installation.

## When to Use

You have a Python process that needs to:
- Run in the background on Windows (no console window)
- Auto-start at user logon
- Auto-restart on failure
- Be controllable via CLI (install/remove/start/stop/status/debug)

Examples: MCP servers, HTTP APIs, queue workers, file watchers, schedulers.

## Architecture

```
Task Scheduler (primary)
  |-- Register-ScheduledTask: at-logon trigger, current user
  |-- pythonw.exe: windowless Python interpreter (no console flash)
  |-- Auto-restart: 3 attempts, 1 minute apart
  |-- Run forever: -ExecutionTimeLimit 0
  |-- Battery: -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Startup folder .bat (fallback)
  |-- %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
  |-- Simple .bat that runs python -m your_module
  |-- No auto-restart capability
```

Decision path: try Task Scheduler first. If PowerShell or task creation is denied (corporate lockdown, execution policy), fall back to the Startup folder `.bat`.

## File Structure

```
your_project/
  pyproject.toml                  # Entry point: your-project-service = "package.service:handle_command_line"
  src/your_package/
    service.py                    # This blueprint
    server.py (or main.py, etc.)  # The actual process to run
```

Only one file is needed: `service.py`. It has zero project-specific dependencies in the service management layer itself — all project imports happen inside `_debug()` and `_eager_warmup()`.

## pyproject.toml Entry Point

```toml
[project.scripts]
your-project = "your_package.server:main"
your-project-service = "your_package.service:handle_command_line"
```

The `-service` suffix is convention. The main entry point runs the process directly; the `-service` entry point manages it as a background service.

## service.py Skeleton

```python
"""Service management for <ProjectName>.

Primary: Windows Task Scheduler (zero extra dependencies, any Python).
Fallback: Startup folder shortcut (if Task Scheduler is denied).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path


# === CUSTOMIZE: Names and paths ===
TASK_NAME = "YourProjectName"          # Task Scheduler display name (no spaces recommended)
MODULE = "your_package.server"         # Module to run via python -m
STARTUP_BAT = "YourProjectName.bat"   # Filename in Startup folder
LOG_DIR = Path.home() / ".your-project"
LOG_FILE = LOG_DIR / "service.log"
LOGGER_NAME = "your-project"


# === Logging (fixed pattern) ===

def _setup_logging() -> logging.Logger:
    """Configure file-based logging for the service."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(str(LOG_FILE))
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    return logger


# === CUSTOMIZE: Warmup hook (optional, delete if not needed) ===

def _eager_warmup(logger: logging.Logger) -> None:
    """Pre-load expensive resources before accepting work.

    Examples:
    - Load ML models into memory
    - Connect to databases and apply schema
    - Build caches or indexes
    - Validate configuration

    This runs BEFORE the main process loop starts. If warmup fails,
    the process crashes immediately (which triggers Task Scheduler restart).
    """
    # from .server import get_engine
    # logger.info("Warmup: connecting to database...")
    # engine = get_engine()
    # logger.info("Warmup: database connected.")
    pass


# === Task Scheduler (fixed pattern) ===

def _install_task() -> bool:
    """Install as Windows Scheduled Task via PowerShell. Returns True on success."""
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    python_exe = str(pythonw if pythonw.exists() else sys.executable).replace("'", "''")

    ps_script = (
        f"$action = New-ScheduledTaskAction -Execute '{python_exe}' -Argument '-m {MODULE}'; "
        f"$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        f"$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) "
        f"-ExecutionTimeLimit 0 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Settings $settings -Force"
    )

    try:
        result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            print(f"Installed scheduled task '{TASK_NAME}'.")
            print(f"  Auto-starts at logon, restarts on failure (3x, 1 min apart).")
            print(f"  Logs: {LOG_FILE}")
            return True
        else:
            print(f"Task Scheduler failed: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        print("Task Scheduler timed out.")
        return False


# === Startup folder fallback (fixed pattern) ===

def _install_startup_folder() -> bool:
    """Fallback: create a .bat in the user's Startup folder."""
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    if not startup.exists():
        print(f"Startup folder not found: {startup}")
        return False

    bat = startup / STARTUP_BAT
    bat.write_text(f'@echo off\n"{sys.executable}" -m {MODULE}\n')
    print(f"Installed startup script: {bat}")
    print(f"  Server will start at next login.")
    return True


def _remove_startup_folder() -> bool:
    """Remove the Startup folder .bat if it exists."""
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    bat = startup / STARTUP_BAT
    if bat.exists():
        bat.unlink()
        print(f"Removed startup script: {bat}")
        return True
    return False


# === Install / Remove (fixed pattern) ===

def _install() -> None:
    """Install: try Task Scheduler, fall back to Startup folder."""
    if _install_task():
        return
    print("Falling back to Startup folder...")
    if _install_startup_folder():
        return
    print("ERROR: Could not install service via any method.")
    sys.exit(1)


def _remove() -> None:
    """Remove scheduled task and/or startup script."""
    removed = False

    result = subprocess.run(
        ["powershell", "-Command", f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Removed scheduled task '{TASK_NAME}'.")
        removed = True

    if _remove_startup_folder():
        removed = True

    if not removed:
        print("Nothing to remove — service was not installed.")


# === Start / Stop (fixed pattern) ===

def _start() -> None:
    """Start the scheduled task now."""
    result = subprocess.run(
        ["powershell", "-Command", f"Start-ScheduledTask -TaskName '{TASK_NAME}'"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Started '{TASK_NAME}'.")
    else:
        print(f"Failed to start: {result.stderr.strip()}")
        print(f"Is the service installed? Run: {LOGGER_NAME}-service install")


def _stop() -> None:
    """Stop the scheduled task."""
    result = subprocess.run(
        ["powershell", "-Command", f"Stop-ScheduledTask -TaskName '{TASK_NAME}'"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Stopped '{TASK_NAME}'.")
    else:
        print(f"Failed to stop: {result.stderr.strip()}")


# === CUSTOMIZE: Health check ===
# Choose ONE strategy that matches your project. See "Health Check Strategies" below.

def _check_health() -> bool:
    """Check if the service process is alive and functioning."""
    # Strategy: HTTP probe (for HTTP servers)
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request("http://127.0.0.1:8050/health", method="GET")
        urllib.request.urlopen(req, timeout=2)
        return True
    except urllib.error.HTTPError:
        return True  # Any HTTP response means the server is up
    except (urllib.error.URLError, ConnectionRefusedError, OSError):
        return False


# === CUSTOMIZE: Status display ===

def _status() -> None:
    """Show current status with operational details."""
    # Task state (fixed pattern)
    result = subprocess.run(
        ["powershell", "-Command", f"Get-ScheduledTask -TaskName '{TASK_NAME}' | Format-List TaskName,State"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            print(line.strip())
    else:
        startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        bat = startup / STARTUP_BAT
        if bat.exists():
            print(f"Installed  : Startup folder ({bat})")
        else:
            print("Service not installed.")
            return

    # Health check (uses the customized _check_health)
    healthy = _check_health()
    print(f"Healthy    : {'yes' if healthy else 'no'}")

    # === CUSTOMIZE: Project-specific status lines ===
    # print(f"Endpoint   : http://127.0.0.1:8050/api")
    # print(f"Database   : {db_path}")
    print(f"Log file   : {LOG_FILE}")
    if LOG_FILE.exists():
        log_size = LOG_FILE.stat().st_size
        print(f"Log size   : {log_size / 1024:.1f} KB")


# === Debug mode (fixed pattern + customizable warmup) ===

def _debug() -> None:
    """Run in foreground for development."""
    print("Running in debug mode (foreground)...")
    logger = _setup_logging()
    logger.addHandler(logging.StreamHandler())  # Also log to console in debug
    _eager_warmup(logger)
    # === CUSTOMIZE: Import and call your main process ===
    from .server import main
    main()


# === CLI dispatch (fixed pattern) ===

USAGE = f"""\
{TASK_NAME} — service management

Usage:
  {LOGGER_NAME}-service install   Install (Task Scheduler + auto-restart)
  {LOGGER_NAME}-service remove    Uninstall
  {LOGGER_NAME}-service start     Start now
  {LOGGER_NAME}-service stop      Stop
  {LOGGER_NAME}-service status    Show status
  {LOGGER_NAME}-service debug     Run in foreground (development)
"""


def handle_command_line():
    """CLI entrypoint for service management."""
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(0)

    command = sys.argv[1].lower()

    commands = {
        "install": _install,
        "remove": _remove,
        "uninstall": _remove,  # Alias
        "start": _start,
        "stop": _stop,
        "status": _status,
        "debug": _debug,
    }

    fn = commands.get(command)
    if fn is None:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)

    fn()


if __name__ == "__main__":
    handle_command_line()
```

## Health Check Strategies

Choose the strategy that matches your project. Implement it in `_check_health()`.

### HTTP Probe (for HTTP servers, APIs, MCP Streamable HTTP)

```python
def _check_health() -> bool:
    import urllib.request
    import urllib.error
    port = int(os.environ.get("YOUR_PROJECT_PORT", "8050"))
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health", method="GET")
        urllib.request.urlopen(req, timeout=2)
        return True
    except urllib.error.HTTPError:
        return True  # Any HTTP response = server is up (e.g., 405 Method Not Allowed)
    except (urllib.error.URLError, ConnectionRefusedError, OSError):
        return False
```

Why `HTTPError` returns `True`: many servers reject GET on POST-only endpoints. A 405 or 406 still proves the process is alive and listening. Connection refused or timeout means it is not.

### PID File Check (for long-running processes that write a PID file)

```python
def _check_health() -> bool:
    pid_file = LOG_DIR / "service.pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        # os.kill(pid, 0) doesn't kill — it checks if the process exists
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it (still alive)
```

Your process must write its PID on startup: `(LOG_DIR / "service.pid").write_text(str(os.getpid()))`.

### Process Name Check (simplest, for unique process names)

```python
def _check_health() -> bool:
    result = subprocess.run(
        ["powershell", "-Command",
         f"Get-Process | Where-Object {{$_.CommandLine -like '*-m {MODULE}*'}} | Measure-Object | Select-Object -ExpandProperty Count"],
        capture_output=True, text=True, timeout=5,
    )
    try:
        return int(result.stdout.strip()) > 0
    except (ValueError, AttributeError):
        return False
```

Heavier than the others (spawns PowerShell), but requires zero cooperation from the managed process.

### No Health Check (for fire-and-forget workers)

```python
def _check_health() -> bool:
    return True  # Task Scheduler state is sufficient
```

Use this when health checking is meaningless (e.g., a batch processor that runs and exits, a file watcher where "healthy" is hard to define). The `_status()` function still shows the Task Scheduler state, which tells you if the task is Running, Ready, or Disabled.

## Customization Checklist

When creating a `service.py` for a new project, change these and only these:

| Item | What to set | Example |
|------|-------------|---------|
| `TASK_NAME` | Task Scheduler display name | `"CognitiveMemory"` |
| `MODULE` | Python module to run | `"cognitive_memory.server"` |
| `STARTUP_BAT` | Bat filename in Startup folder | `"CognitiveMemory.bat"` |
| `LOG_DIR` | Directory for service log | `Path.home() / ".cognitive-memory"` |
| `LOG_FILE` | Log file path | `LOG_DIR / "service.log"` |
| `LOGGER_NAME` | Logger name (also used in usage text) | `"cognitive-memory"` |
| `_eager_warmup()` | Pre-load resources, or delete entirely | DB connect, model load |
| `_check_health()` | Pick a health check strategy | HTTP probe, PID file, etc. |
| `_status()` | Project-specific status lines after health | Endpoint, DB path, DB size |
| `_debug()` | Import path to your main function | `from .server import main` |
| `pyproject.toml` | Entry point under `[project.scripts]` | `proj-service = "pkg.service:handle_command_line"` |
Everything else (Task Scheduler install/remove/start/stop, Startup folder fallback, CLI dispatch, logging setup) is the fixed pattern. Do not modify it.

> **Note to implementer**: The examples in the checklist above use `CognitiveMemory` / `cognitive-memory` because this blueprint was extracted from that project. Replace all names with your own project's conventions — the pattern is generic, only the names are project-specific.

## Constraints and Gotchas

### PowerShell Execution Policy

Some machines restrict PowerShell script execution. The commands in this blueprint use `-Command` (inline string), not `-File`, so they are not affected by `Set-ExecutionPolicy` restrictions on `.ps1` files. However, if PowerShell itself is blocked by group policy, the entire Task Scheduler path fails and the Startup folder fallback kicks in.

If you need to explicitly bypass for a `.ps1` file approach:
```
powershell -ExecutionPolicy Bypass -File script.ps1
```
This blueprint avoids `.ps1` files entirely, so this is not normally needed. **If you do need to use `-ExecutionPolicy Bypass`, always check with the user first** — some organizations prohibit this, and running it without authorization may violate security policies.

### pythonw.exe Availability

`pythonw.exe` is the windowless Python interpreter — it prevents a console window from flashing on screen when the task runs. It ships with the standard Windows Python installer and the Microsoft Store Python.

It does **not** exist in:
- WSL Python installations
- Some conda environments (depends on build)
- Manually compiled Python without the `pythonw` target

The blueprint detects this automatically and falls back to `python.exe`. The only downside is a brief console flash at logon before the task starts running.

### Task Scheduler Scope

Tasks created without elevation are per-user. They:
- Only run when that user is logged in (the `AtLogOn` trigger)
- Are visible only in that user's Task Scheduler view
- Cannot use `SYSTEM` or other user accounts as the principal
- Cannot use `AtStartup` trigger (requires admin)

This is by design. The blueprint targets developer machines where the user is always logged in, not headless servers.

### Startup Folder Fallback Limitations

The `.bat` fallback:
- Does **not** auto-restart on failure (process dies, it stays dead until next logon)
- Does **not** use `pythonw.exe` (a console window may appear briefly)
- Cannot be started/stopped via `_start()` / `_stop()` (those are Task Scheduler commands)

It exists as a last resort for locked-down machines. If even the Startup folder is restricted, the install fails with an error message.

### Log File Growth

The blueprint uses `logging.FileHandler`, which appends forever. For long-running services, consider switching to `RotatingFileHandler`:

```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    str(LOG_FILE),
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
)
```

This is a project-level decision, not part of the fixed pattern.

### Task Scheduler Task Already Exists

`Register-ScheduledTask -Force` overwrites an existing task with the same name. This is intentional — running `install` again updates the task (e.g., after changing the Python path or module). No need to `remove` first.

### Stopping Behavior

`Stop-ScheduledTask` terminates the process tree. If your process needs graceful shutdown (e.g., flushing buffers, closing DB connections), handle `SIGTERM` / `SIGBREAK` in your main process:

```python
import signal

def _shutdown(signum, frame):
    # Flush, close connections, etc.
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGBREAK, _shutdown)  # Windows-specific
```

## Origin

Generalized from `C:/Projects/cognitive-memory/src/cognitive_memory/service.py` (commit `692dce7`).