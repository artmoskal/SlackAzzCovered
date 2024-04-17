from celery import Celery
from dependency_injector import providers

class CeleryProvider(providers.Factory):
    def __init__(self, celery_main, config):
        # Initialize the Factory base class with Celery constructor
        super().__init__(
            Celery,
            main=celery_main,
            # Use Factory provider to delay the configuration resolution until Celery object creation
            broker=providers.Factory(lambda: f"redis://:{config['redis_password']}@{config['redis_host']}:{config['redis_port']}/{config['redis_celery_broker_db_num']}"),
            backend=providers.Factory(lambda: f"redis://:{config['redis_password']}@{config['redis_host']}:{config['redis_port']}/{config['redis_celery_backend_db_num']}"),
            include=['celery_scheduler.tasks.ping_manager_when_unanswered'],
        )
        self.config = config

    def __call__(self):
        # Create the Celery instance
        celery_app = super().__call__()
        # Configure the Celery instance
        celery_app.conf.update(
            task_serializer='json',
            accept_content=['json'],
            result_serializer='json',
            timezone='UTC',
            enable_utc=True,
        )
        return celery_app
