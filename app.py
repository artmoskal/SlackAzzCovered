
from config.config_manager import ConfigManager
from config.container import Container

config = ConfigManager()

container = Container()


def prepare_data(vector_db_helper):
    vector_db_helper.delete_class_if_exists("Message")
    vector_db_helper.delete_class_if_exists("MessageGroup")
    vector_db_helper.create_schema()
    slack_utils = container.slack_utilities()
    slack_utils.fetch_and_process_channel_history(config.load_config().get("test_channel_id"), days_ago=2)


celery = container.celery_app()()
if __name__ == "__main__":
#    slack_app = container.slack_app()
    channel_id = "G03MX3VE7"
    # prepare_data(vector_db_helper)
    # vector_db_helper.ungroup_all()
    # vector_db_helper.delete_message_groups()

    result = celery.send_task('celery_scheduler.tasks.ping_manager_when_unanswered.exec', args=[channel_id], countdown=2)
    print(result)

    # vector_db_helper = container.vector_db_helper()
    # vector_db_helper.group_all_in_channel(channel_id)
    # slack_app.start()
