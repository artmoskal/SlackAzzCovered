from dependency_injector import containers, providers
import redis
import weaviate
from slack_bolt import App

from llm.llm_caller import LlmCaller
from slack.message_history_fetcher import MessageHistoryFetcher
from slack.slack_app import SlackApp
from vectordb.vector_db_helper import VectorDBHelper
from config_manager import ConfigManager

config = ConfigManager()

class Container(containers.DeclarativeContainer):
    # Using providers.Factory or providers.Object for static values
    redis_client = providers.Singleton(
        redis.Redis,
        host='localhost',
        port=6379,
        db=0,
        password=providers.Object(config.redis_password)
    )

    weaviate_client = providers.Singleton(
        weaviate.connect_to_local,
        port=providers.Object(config.weaviate_port),
        grpc_port=providers.Object(config.weaviate_grpc_port),
        auth_credentials=providers.Factory(
            weaviate.AuthApiKey,
            api_key=providers.Object(config.weaviate_api_key)
        ),
        headers=providers.Dict({"X-OpenAI-Api-Key": providers.Object(config.gpt_api_token)}),
        additional_config=providers.Factory(
            weaviate.config.AdditionalConfig,
            timeout=(15, 60)
        )
    )

    vector_db_helper = providers.Factory(
        VectorDBHelper,
        client=weaviate_client
    )

    slack_bolt_app = providers.Factory(
        App,
        token=providers.Object(config.slack_bot_token),
        signing_secret=providers.Object(config.slack_signing_secret),
        ignoring_self_events_enabled=True
    )

    message_history_fetcher = providers.Factory(
        MessageHistoryFetcher,
        app=slack_bolt_app
    )

    slack_app = providers.Factory(
        SlackApp,
        slack_bolt_app=slack_bolt_app,
        slack_app_token=providers.Object(config.slack_app_token),
        vector_db_helper=vector_db_helper,
        qa_processor=None,
        message_history_fetcher=message_history_fetcher,
        llm_caller=providers.Factory(LlmCaller, api_token=providers.Object(config.gpt_api_token)),
        redis_client=redis_client,
        admin_user_ids=providers.Object(config.admin_user_ids)
    )

container = Container()
def prepare_data(vector_db_helper):
    vector_db_helper.delete_class_if_exists("Message")
    vector_db_helper.delete_class_if_exists("MessageGroup")
    vector_db_helper.create_schema()
    slack_app.fetch_and_process_channel_history(config.test_channel_id, days_ago=2)


if __name__ == "__main__":
    slack_app = container.slack_app()
    channel_id = "G03MX3VE7"
    # prepare_data(vector_db_helper)
    # vector_db_helper.ungroup_all()
    # vector_db_helper.delete_message_groups()


    vector_db_helper = container.vector_db_helper()
    vector_db_helper.group_all_in_channel(channel_id)
    slack_app.start()
