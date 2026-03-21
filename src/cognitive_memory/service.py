"""Service management for Cognitive Memory MCP server.

Primary: Windows Task Scheduler (zero extra dependencies, any Python).
Fallback: Startup folder shortcut (if Task Scheduler is denied).
Optional: pywin32 Windows Service (if installed, for power users).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".cognitive-memory"
LOG_FILE = LOG_DIR / "service.log"
TASK_NAME = "CognitiveMemory"
STARTUP_BAT = "CognitiveMemory.bat"


def _setup_logging() -> logging.Logger:
    """Configure file-based logging for the service."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cognitive-memory")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(str(LOG_FILE))
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    return logger


def _eager_warmup(logger: logging.Logger) -> None:
    """Connect SurrealDB, apply schema, pre-load embedding model."""
    from .server import _get_engine

    logger.info("Eager warmup: initializing engine (SurrealDB + schema)...")
    engine = _get_engine()
    logger.info("Eager warmup: SurrealDB connected, schema applied.")

    logger.info("Eager warmup: pre-loading embedding model...")
    engine.embeddings.warmup()
    logger.info("Eager warmup: embedding model loaded. Ready to serve.")


# === Task Scheduler ===

def _install_task() -> bool:
    """Install as Windows Scheduled Task via PowerShell. Returns True on success."""
    # Use pythonw.exe (windowless) so the task runs hidden — no console window
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    python_exe = str(pythonw if pythonw.exists() else sys.executable).replace("'", "''")

    # PowerShell script: create task with logon trigger for current user + restart on failure
    ps_script = (
        f"$action = New-ScheduledTaskAction -Execute '{python_exe}' -Argument '-m cognitive_memory.server'; "
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


def _install_startup_folder() -> bool:
    """Fallback: create a .bat in the user's Startup folder."""
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    if not startup.exists():
        print(f"Startup folder not found: {startup}")
        return False

    bat = startup / STARTUP_BAT
    bat.write_text(f'@echo off\n"{sys.executable}" -m cognitive_memory.server\n')
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
        print("Is the service installed? Run: cognitive-memory-service install")


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


def _status() -> None:
    """Show current status."""
    result = subprocess.run(
        ["powershell", "-Command", f"Get-ScheduledTask -TaskName '{TASK_NAME}' | Format-List TaskName,State"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        print(result.stdout.strip())
    else:
        startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        bat = startup / STARTUP_BAT
        if bat.exists():
            print(f"Installed via Startup folder: {bat}")
        else:
            print("Service not installed.")


def _debug() -> None:
    """Run in foreground for development."""
    print("Running in debug mode (foreground)...")
    logger = _setup_logging()
    logger.addHandler(logging.StreamHandler())
    _eager_warmup(logger)
    from .server import main
    main()


USAGE = """\
Cognitive Memory MCP Server — service management

Usage:
  cognitive-memory-service install   Install (Task Scheduler + auto-restart)
  cognitive-memory-service remove    Uninstall
  cognitive-memory-service start     Start now
  cognitive-memory-service stop      Stop
  cognitive-memory-service status    Show status
  cognitive-memory-service debug     Run in foreground (development)
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
        "uninstall": _remove,
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
