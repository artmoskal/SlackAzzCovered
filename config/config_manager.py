from pathlib import Path

from environs import Env
import logging


class ConfigManager:
    def __init__(self):
        self.env = Env()
        # Load .env from both root and infra folder
        app_root_env = Path(__file__).parent.parent / '.env'  # Adjust to point to app root
        infra_env = Path(__file__).parent.parent / 'infra/.env'

        # Read both .env files if they exist
        if app_root_env.exists():
            self.env.read_env(path=str(app_root_env), override=False)  # Do not override existing values
        if infra_env.exists():
            self.env.read_env(path=str(infra_env), override=True)  # Allow infra values to override root values        # Configure logging
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

    def is_running_in_docker(self):
        """Check if the app is running inside Docker."""
        try:
            with open('/proc/1/cgroup', 'r') as f:
                return 'docker' in f.read()
        except Exception:
            return False

    def resolve_host(self, base_key: str) -> str:
        """
        Resolve host dynamically based on the environment.
        :param base_key: The base key for the host variable (e.g., "REDIS_HOST").
        :return: The resolved host (local or dockerized).
        """
        local_key = f"{base_key}_LOCAL"
        dockerized_key = f"{base_key}_DOCKERIZED"
        local_host = self.env.str(local_key, "localhost")
        dockerized_host = self.env.str(dockerized_key, base_key.lower())  # Default to lowercase key as dockerized host
        return dockerized_host if self.is_running_in_docker() else local_host


    def load_config(self):
        # Directly return structured config with types defined by environs
        protocol = self.env.str("N8N_PROTOCOL", "http")  # Default protocol
        host = self.resolve_host("N8N_HOST")
        port = self.env.int("N8N_PORT", 5678)
        return {
            # Redis Configuration
            "redis_host": self.resolve_host('REDIS_HOST'),
            "redis_port": self.env.int("REDIS_PORT", 6379),
            "redis_password": self.env.str("REDIS_PASSWORD", None),
            "redis_app_db_num": self.env.int("REDIS_APP_DB_NUM", 0),
            "redis_celery_broker_db_num": self.env.int("REDIS_BROKER_DB_NUM", 1),
            "redis_celery_backend_db_num": self.env.int("REDIS_BACKEND_DB_NUM", 2),

            # Weaviate Configuration
            "weaviate_host": self.resolve_host("WEAVIATE_HOST"),
            "weaviate_port": self.env.int("WEAVIATE_PORT", 8080),
            "weaviate_secure": self.env.bool("WEAVIATE_SECURE", False),
            "weaviate_grpc_port": self.env.int("WEAVIATE_GRPC_PORT", 50051),
            "weaviate_api_key": self.env.str("WEAVIATE_API_KEY", None),


            "gpt_api_token": self.env.str("GPT_API_TOKEN", None),
            "slack_bot_token": self.env.str("SLACK_BOT_TOKEN", None),
            "slack_signing_secret": self.env.str("SLACK_SIGNING_SECRET", None),
            "slack_app_token": self.env.str("SLACK_APP_TOKEN", None),
            "admin_user_ids": self.env.list("ADMIN_USER_IDS", []),  # Automatically parses as list
            "test_channel_id": self.env.str("TEST_CHANNEL_ID", None),


             # N8N Configuration
            "n8n_base_url": f"{protocol}://{host}:{port}",
            "n8n_encryption_key": self.env.str("N8N_ENCRYPTION_KEY", None),
            "n8n_api_key": self.env.str("N8N_API_KEY", None),
            "n8n_test_webhooks": self.env.str("N8N_TEST_WEBHOOKS", False),

            "ollama_host": self.env.str("OLLAMA_HOST_LOCAL", None),
        }
