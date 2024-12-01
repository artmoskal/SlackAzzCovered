# api/app_manager.py
import asyncio
import multiprocessing
import signal
import tempfile
import platform
from contextlib import asynccontextmanager
from typing import Any, Optional, Dict
import logging
import gunicorn.app.base
from fastapi import FastAPI
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from gunicorn.config import Config

class StandaloneApplication(gunicorn.app.base.BaseApplication):
    def __init__(self, app: Any, options: Optional[Dict[str, Any]] = None):
        self.options = options or {}
        self.application = app
        self.cfg: Config  # Declare cfg attribute type before super().__init__
        super().__init__()

    def load_config(self) -> None:
        # Now the linter knows self.cfg is definitely a Config instance
        config = {
            key: value for key, value in self.options.items()
            if key in self.cfg.settings and value is not None
        }
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self) -> Any:
        return self.application

def run_slack_process(config: dict):
    """Run Slack app in a separate process using configuration"""
    from config.container import Container

    logger = logging.getLogger(__name__)
    running = True

    def signal_handler(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    async def run_slack():
        container = Container()
        container.config.override(config)
        slack_app = container.slack_app()
        await slack_app.setup_commands_and_events()

        handler = AsyncSocketModeHandler(
            app=slack_app.app,
            app_token=slack_app.slack_app_token
        )

        try:
            await handler.start_async()
        except Exception as e:
            logger.error(f"Error in Slack connection: {e}")
        finally:
            if running:
                await handler.close_async()

    asyncio.run(run_slack())


class AppManager:
    def __init__(
            self,
            slack_app,  # from container.slack_app
            n8n_manager,  # from container.n8n_workflow_manager
            config: dict[str, Any]  # from container.config
    ):
        self.slack_app = slack_app
        self.n8n_manager = n8n_manager
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._slack_process = None

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            try:
                self.logger.info("Starting services...")
                await self.n8n_manager.setup_workflows(
                    recreate=self.config.get('recreate_workflows', False)
                )
                yield
            except Exception as e:
                self.logger.error(f"Error during startup: {e}")
                raise

        self.fastapi_app = FastAPI(lifespan=lifespan)
        from api.endpoints import router
        self.fastapi_app.include_router(router, prefix="/api/v1")

    def run_slack_and_api(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Run both Slack and FastAPI server using gunicorn"""
        try:
            # Start Slack process with injected container
            self._slack_process = multiprocessing.Process(
                target=run_slack_process,
                args=(self.config,),
                name="slack-websocket"
            )
            self._slack_process.start()
            self.logger.info("Slack process started")

            workers = multiprocessing.cpu_count() * 2 + 1
            self.logger.info(f"Starting server on {host}:{port} with {workers} workers")

            # Choose appropriate temp directory based on OS
            if platform.system() == "Linux":
                worker_tmp_dir = '/dev/shm'
            else:
                worker_tmp_dir = tempfile.gettempdir()

            options = {
                'bind': f'{host}:{port}',
                'workers': 2,
                'worker_class': 'uvicorn_worker.UvicornWorker',
                'timeout': 120,
                'keepalive': 5,
                'accesslog': '-',  # Log to stdout
                'errorlog': '-',
                'loglevel': 'info',
                'worker_tmp_dir': worker_tmp_dir,
                'preload_app': True,
                'reload': True
            }

            try:
                StandaloneApplication(self.fastapi_app, options).run()
            finally:
                # Cleanup Slack process on API server shutdown
                if self._slack_process and self._slack_process.is_alive():
                    self._slack_process.terminate()
                    self._slack_process.join(timeout=5)
                    if self._slack_process.is_alive():
                        self._slack_process.kill()

        except Exception as e:
            self.logger.error(f"Server error: {e}")
            if self._slack_process and self._slack_process.is_alive():
                self._slack_process.terminate()
            raise