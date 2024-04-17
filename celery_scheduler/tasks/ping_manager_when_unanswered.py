# celery_scheduler/tasks/ping_manager_when_unanswered.py
from celery import shared_task

from config.container import Container


@shared_task(name='celery_scheduler.tasks.ping_manager_when_unanswered.exec')
def exec(channel_id):
    container = Container()
    container.slack_bolt_app().client.chat_postMessage(channel=channel_id, text="helloaa")

