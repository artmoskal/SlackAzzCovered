from dependency_injector import containers, providers
import redis
import weaviate
from jinja2 import Environment, BaseLoader
from langchain_openai import ChatOpenAI
from slack_bolt.async_app import AsyncApp

from api.app_manager import AppManager
from celery_scheduler.celery_provider import CeleryProvider
from config.config_manager import ConfigManager
from llm.llm_caller import LLMCaller, SatisfactionLevel
from n8n.n8n_provider import N8nProvider
from n8n.n8n_workflow_manager import N8nWorkflowManager
from slack.message_history_fetcher import MessageHistoryFetcher
from slack.role_assignment import RoleAssignment
from slack.slack_message_handler import SlackMessageHandler
from slack.slack_meta_info import SlackMetaInfo
from slack.slack_utilities import SlackUtilities
from vectordb.vector_db_helper import VectorDBHelper
from workflows.channel_state_manager import ChannelStateManager
from workflows.slack_state_manager import SlackStateManager
from weaviate.auth import AuthApiKey


class Container(containers.DeclarativeContainer):
    config_manager = ConfigManager()
    config = providers.Configuration()

    # Override with the configuration dictionary
    config.override(config_manager.load_config())


    celery_app = providers.Singleton(
        CeleryProvider,
        celery_main='celery_worker',
        config=config
    )

    redis_client = providers.Singleton(
        redis.Redis,
        host=config.redis_host,
        port=config.redis_port,
        db=config.redis_app_db_num,
        password=config.redis_password
    )
    weaviate_client = providers.Singleton(
        weaviate.use_async_with_custom,
        http_host=config.weaviate_host,
        http_port=config.weaviate_port,
        http_secure=config.weaviate_secure,
        grpc_host=config.weaviate_host,
        grpc_secure=config.weaviate_secure,
        grpc_port=config.weaviate_grpc_port,
        auth_credentials=providers.Singleton(
            AuthApiKey,
            api_key=config.weaviate_api_key
        ),
        headers=providers.Dict({"X-OpenAI-Api-Key": config.gpt_api_token}),
        additional_config=providers.Factory(
            weaviate.config.AdditionalConfig,
            timeout=(5, 15)
        )
    )


    vector_db_helper = providers.Singleton(
        VectorDBHelper,
        client=weaviate_client
    )

    slack_bolt_app = providers.Singleton(
        AsyncApp,
        token=config.slack_bot_token,
        signing_secret=config.slack_signing_secret,
        ignoring_self_events_enabled=True
    )

    message_history_fetcher = providers.Singleton(
        MessageHistoryFetcher,
        app=slack_bolt_app
    )

    slack_meta_info_provider = providers.Singleton(
        SlackMetaInfo,
        slack_app=slack_bolt_app,
        redis_client=redis_client,
        admin_user_ids=config.admin_user_ids
    )

    slack_utilities = providers.Singleton(
        SlackUtilities,
        vector_db_helper=vector_db_helper,
        message_history_fetcher=message_history_fetcher,
        slack_meta_info_provider=slack_meta_info_provider
    )

    template_env = providers.Singleton(Environment, loader=BaseLoader())

    stupid_model = providers.Singleton(
        ChatOpenAI,
        model="gpt-3.5-turbo",
        openai_api_key=config.gpt_api_token,
        max_tokens=600
    )

    smart_model = providers.Singleton(
        ChatOpenAI,
        model="gpt-4",
        openai_api_key=config.gpt_api_token,
        max_tokens=600
    )

    llm_caller = providers.Singleton(
        LLMCaller,
        stupid_model=stupid_model,
        smart_model=smart_model,
        template_env=template_env,
    )

    channel_state_manager_factory = providers.Factory(
        ChannelStateManager,
        llm_caller=llm_caller,
        scheduler=celery_app
    )

    state_manager = providers.Singleton(
        SlackStateManager,
        redis_client=redis_client,
        llm_caller=llm_caller,
        slack_meta_info_provider=slack_meta_info_provider,
        scheduler=celery_app,
        channel_state_manager_factory=channel_state_manager_factory.provider  # Inject the factory
    )

    role_assignment = providers.Factory(
        RoleAssignment,
        app=slack_bolt_app,
        slack_meta_info_provider=slack_meta_info_provider
    )

    n8n_provider = providers.Singleton(
        N8nProvider,
        base_url=config.n8n_base_url,
        api_key=config.n8n_api_key
    )

    n8n_manager = providers.Singleton(
        N8nWorkflowManager,
        n8n_provider=n8n_provider
    )

    slack_app = providers.Singleton(
        SlackMessageHandler,
        slack_bolt_app=slack_bolt_app,
        slack_utilities=slack_utilities,
        state_manager=state_manager,
        role_assignment=role_assignment,
        slack_app_token=config.slack_app_token,
        n8n_manager=n8n_manager
    )

    app_manager = providers.Singleton(
        AppManager,
        slack_app=slack_app,
        n8n_manager=n8n_manager,
        config=config
    )

