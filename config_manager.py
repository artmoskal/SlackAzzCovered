# config_manager.py
from dotenv import load_dotenv
import os
import logging

class ConfigManager:
    def __init__(self):
        load_dotenv()  # Load environment variables from .env
        # Configure logging
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

        self.redis_password = os.getenv("REDIS_PASSWORD")
        self.weaviate_port = int(os.getenv("WEAVIATE_PORT", 8080))
        self.weaviate_grpc_port = int(os.getenv("WEAVIATE_GRPC_PORT", 50051))
        self.weaviate_api_key = os.getenv("WEAVIATE_API_KEY")
        self.gpt_api_token = os.getenv("GPT_API_TOKEN")
        self.slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
        self.slack_signing_secret = os.getenv("SLACK_SIGNING_SECRET")
        self.slack_app_token = os.getenv("SLACK_APP_TOKEN")
        self.admin_user_ids = os.getenv("ADMIN_USER_IDS", "").split(',')
        self.test_channel_id = os.environ.get("TEST_CHANNEL_ID") # e.g., "G03MX3VE7"
