from celery import Celery
from dependency_injector import providers

class CeleryProvider(providers.Factory):
    def __init__(self, celery_main: str, config: dict):
        super().__init__(self._create_celery_app, celery_main, config)

    @staticmethod
    def _create_celery_app(celery_main: str, config: dict) -> Celery:
        # Instantiate Celery with main and direct configuration strings
        celery_app = Celery(
            main=celery_main,
            broker=f"redis://:{config['redis_password']}@{config['redis_host']}:{config['redis_port']}/{config['redis_celery_broker_db_num']}",
            backend=f"redis://:{config['redis_password']}@{config['redis_host']}:{config['redis_port']}/{config['redis_celery_backend_db_num']}",
            include=['celery_scheduler.tasks.ping_manager_when_unanswered']
        )
        # Set additional configuration directly
        celery_app.conf.update(
            task_serializer='json',
            accept_content=['json'],
            result_serializer='json',
            timezone='UTC',
            enable_utc=True,
        )
        return celery_app  # Return the configured Celery instance

    def __call__(self) -> Celery:
        # Ensures that the instance created by Factory returns the actual Celery app
        return super().__call__()
