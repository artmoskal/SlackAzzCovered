
from celery import Celery
from dependency_injector import containers, providers
import redis
import weaviate
from slack_bolt import App

from celery_scheduler.celery_provider import CeleryProvider
from config.config_manager import ConfigManager
from llm.llm_caller import LlmCaller
from slack.message_history_fetcher import MessageHistoryFetcher
from slack.slack_message_handler import SlackMessageHandler
from slack.slack_meta_info import SlackMetaInfo
from slack.slack_utilities import SlackUtilities
from vectordb.vector_db_helper import VectorDBHelper
class Container(containers.DeclarativeContainer):
    config = providers.Configuration()

    config.override(ConfigManager().load_config())

    # Initialize the CeleryProvider with the 'celery_worker' main name and the configuration
    celery_app = providers.Singleton(
        CeleryProvider,
        celery_main='celery_worker',
        config=config  # Pass the configuration provider directly
    )
    redis_client = providers.Singleton(
        redis.Redis,
        host=config.redis_host,
        port=config.redis_port,
        db=config.redis_app_db_num,
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
        token=config.slack_bot_token,
        signing_secret=config.slack_signing_secret,
        ignoring_self_events_enabled=True
    )
    message_history_fetcher = providers.Factory(
        MessageHistoryFetcher,
        app=slack_bolt_app
    )

    slack_meta_info_provider = providers.Factory(SlackMetaInfo,
                                                 slack_bolt_app,
                                                 redis_client=redis_client)

    slack_utilities = providers.Factory(SlackUtilities,
                                        vector_db_helper=vector_db_helper,
                                        message_history_fetcher=message_history_fetcher,
                                        slack_meta_info_provider=slack_meta_info_provider)

    llm_caller = providers.Factory(LlmCaller, api_token=config.gpt_api_token)

    slack_app = providers.Factory(
        SlackMessageHandler,
        slack_bolt_app=slack_bolt_app,
        llm_caller=llm_caller,
        slack_utilities=slack_utilities,
        slack_app_token=config.slack_app_token,
        admin_user_ids=config.admin_user_ids
    )



