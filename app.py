import logging
from dotenv import load_dotenv
from slack_bolt import App

from llm.llm_caller import LlmCaller
from slack.message_history_fetcher import MessageHistoryFetcher
from slack.slack_app import SlackApp
from vectordb.vector_db_helper import VectorDBHelper
import os
import weaviate
# Load environment variables from .env file
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GPT_API_TOKEN = os.environ.get("GPT_API_TOKEN")
WEAVIATE_URL = os.environ.get("WEAVIATE_URL")
WEAVIATE_API_KEY = os.environ.get("WEAVIATE_API_KEY")
TEST_CHANNEL_ID = os.environ.get("TEST_CHANNEL_ID") # e.g., "G03MX3VE7"

client = weaviate.connect_to_local(
    port=8080,
    grpc_port=50051,
    auth_credentials=weaviate.AuthApiKey(WEAVIATE_API_KEY),
    headers={
        "X-OpenAI-Api-Key": GPT_API_TOKEN
    },
    additional_config=weaviate.config.AdditionalConfig(timeout=(15, 60))  # Values in seconds
)


def prepare_data(vector_db_helper):
    vector_db_helper.delete_class_if_exists("Message")
    vector_db_helper.delete_class_if_exists("MessageGroup")
    vector_db_helper.create_schema()
    slack_app.fetch_and_process_channel_history(TEST_CHANNEL_ID, days_ago=2)

if __name__ == "__main__":

    vector_db_helper = VectorDBHelper(client)
    llm_caller = LlmCaller(api_token=GPT_API_TOKEN)

    # Initialize SlackApp with dependencies
    slack_bolt_app = App(
        token=os.getenv("SLACK_BOT_TOKEN"),
        signing_secret=os.getenv("SLACK_SIGNING_SECRET")
    )
    message_history_fetcher =  MessageHistoryFetcher(app=slack_bolt_app)
    slack_app = SlackApp(
        slack_bolt_app,
        slack_app_token=os.getenv("SLACK_APP_TOKEN"),
        vector_db_helper=vector_db_helper,
        qa_processor=None,
        message_history_fetcher=message_history_fetcher,
        llm_caller=llm_caller,
    )

    # prepare_data(vector_db_helper)
    # vector_db_helper.ungroup_all()
    # vector_db_helper.delete_message_groups()

    # prepare_data()
    channel_id = "G03MX3VE7"

    vector_db_helper.group_all_in_channel(channel_id)
    slack_app.start()