import os
from dotenv import load_dotenv
import logging
from dependency_injector import providers, containers


class ConfigManager:
    def __init__(self):
        load_dotenv()
        # Configure logging
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

    def load_config(self):
        return {
            "redis_password": os.getenv("REDIS_PASSWORD"),
            "redis_host": os.getenv("REDIS_HOST", "localhost"),
            "redis_port": os.getenv("REDIS_PORT", "6379"),
            "redis_app_db_num": os.getenv("REDIS_APP_DB_NUM", "0"),
            "redis_celery_broker_db_num": os.getenv("REDIS_BROKER_DB_NUM", "1"),
            "redis_celery_backend_db_num": os.getenv("REDIS_BACKEND_DB_NUM", "2"),
            "weaviate_port": int(os.getenv("WEAVIATE_PORT", 8080)),
            "weaviate_grpc_port": int(os.getenv("WEAVIATE_GRPC_PORT", 50051)),
            "weaviate_api_key": os.getenv("WEAVIATE_API_KEY"),
            "gpt_api_token": os.getenv("GPT_API_TOKEN"),
            "slack_bot_token": os.getenv("SLACK_BOT_TOKEN"),
            "slack_signing_secret": os.getenv("SLACK_SIGNING_SECRET"),
            "slack_app_token": os.getenv("SLACK_APP_TOKEN"),
            "admin_user_ids": os.getenv("ADMIN_USER_IDS", "").split(','),
            "test_channel_id": os.getenv("TEST_CHANNEL_ID"),
        }
