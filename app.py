import argparse

from config.config_manager import ConfigManager
from config.container import Container
from vectordb import vector_db_helper

from api.app_manager import AppManager
import asyncio

from icecream import ic
config = ConfigManager()

container = Container()

async def prepare_data(vector_db_helper):
    vector_db_helper.delete_class_if_exists("Message")
    vector_db_helper.delete_class_if_exists("MessageGroup")
    vector_db_helper.create_schema()
    slack_utils = container.slack_utilities()
    await slack_utils.fetch_and_process_channel_history(config.load_config().get("test_channel_id"), days_ago=2)


celery = container.celery_app()()

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--recreate-workflows', action='store_true')
    args = parser.parse_args()

    container = Container()
    app_manager = container.app_manager()
    await container.n8n_manager().setup_workflows()
    app_manager.run_slack_and_api()

async def init_vector_db(container):
    channel_id = "G03MX3VE7"
    vdh = container.vector_db_helper()
    await prepare_data(vdh)
    vdh.ungroup_all()
    vdh.delete_message_groups()
    vector_db_helper = container.vector_db_helper()
    vector_db_helper.group_all_in_channel(channel_id)


if __name__ == "__main__":
    asyncio.run(main())
