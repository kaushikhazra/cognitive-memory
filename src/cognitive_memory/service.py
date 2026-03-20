"""Windows Service wrapper for Cognitive Memory MCP server."""

from __future__ import annotations

import asyncio
import logging
import os
import selectors
import sys
from pathlib import Path

# Windows service imports — optional dependency
try:
    import win32event
    import win32service
    import win32serviceutil
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


LOG_DIR = Path.home() / ".cognitive-memory"
LOG_FILE = LOG_DIR / "service.log"


def _setup_logging() -> logging.Logger:
    """Configure file-based logging for the service."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cognitive-memory")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(str(LOG_FILE))
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    return logger


if HAS_WIN32:
    class CognitiveMemoryService(win32serviceutil.ServiceFramework):
        """Windows Service running the Cognitive Memory MCP server over HTTP."""

        _svc_name_ = "CognitiveMemory"
        _svc_display_name_ = "Cognitive Memory MCP Server"
        _svc_description_ = "Biologically-inspired cognitive memory system for AI agents, served via MCP over HTTP."

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.is_alive = True
            self.server = None
            self.logger = _setup_logging()

        def SvcDoRun(self):
            """Service entry point — runs until SvcStop is called."""
            self.logger.info("Service starting...")
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)

            try:
                # Force SelectorEventLoop to avoid ProactorEventLoop signal issue
                selector = selectors.SelectSelector()
                loop = asyncio.SelectorEventLoop(selector)
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._run_server())
            except Exception as e:
                self.logger.error(f"Service error: {e}", exc_info=True)
            finally:
                self.logger.info("Service stopped.")

        def SvcStop(self):
            """Called when Windows asks the service to stop."""
            self.logger.info("Stop signal received.")
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self.is_alive = False
            win32event.SetEvent(self.stop_event)
            if self.server:
                self.server.should_exit = True

        async def _run_server(self):
            """Start uvicorn and wait for stop signal."""
            from uvicorn import Config, Server
            from .server import get_app

            port = int(os.environ.get("COGNITIVE_MEMORY_PORT", "52100"))
            host = os.environ.get("COGNITIVE_MEMORY_HOST", "127.0.0.1")

            config = Config(
                app=get_app(),
                host=host,
                port=port,
                log_level="info",
                access_log=False,
            )
            self.server = Server(config)

            self.logger.info(f"Starting HTTP server on {host}:{port}")
            server_task = asyncio.create_task(self.server.serve())

            # Poll for stop signal
            while self.is_alive:
                result = win32event.WaitForSingleObject(self.stop_event, 1000)
                if result == 0:  # WAIT_OBJECT_0
                    self.logger.info("Stop event received, shutting down...")
                    break
                if server_task.done():
                    break
                await asyncio.sleep(0.1)

            # Graceful shutdown
            self.server.should_exit = True
            try:
                await asyncio.wait_for(server_task, timeout=10.0)
            except asyncio.TimeoutError:
                self.logger.warning("Server shutdown timeout, forcing exit")


def handle_command_line():
    """CLI entrypoint for service management."""
    if not HAS_WIN32:
        print("pywin32 is required for Windows Service support.")
        print("Install with: pip install pywin32")
        sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == "debug":
        # Run in foreground for development
        print("Running in debug mode (foreground)...")
        logger = _setup_logging()
        logger.addHandler(logging.StreamHandler())
        from .server import main
        main()
    else:
        win32serviceutil.HandleCommandLine(CognitiveMemoryService)


if __name__ == "__main__":
    handle_command_line()
