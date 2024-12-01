import logging
from datetime import datetime
from typing import Optional, ClassVar

from celery import Celery
from pydantic import BaseModel, Field

from celery_scheduler.celery_provider import CeleryProvider
from llm.context.input import DynamicContextInput, AnswerToQuestionContext, AnswerQualityEvaluationContext
from llm.context.out import MessageActionable, AnswerToQuestion
from llm.llm_caller import LLMCaller
from slack.struct.event_data import EventData
from slack.struct.message_history_data import MessageHistoryData
from slack.struct.send_message_action import SendMessageAction
from slack.struct.slack_user import SlackUser


class IssueState(BaseModel):
    kicker: MessageActionable
    ts: datetime
    initiator: SlackUser = Field(description="The user who initiated the conversation.")


class CustomerQuestion(IssueState):
    DEFAULT_SOFT_NOTIFICATION_TIMEOUT: ClassVar[int] = 10  # This is now properly annotated
    DEFAULT_HARD_NOTIFICATION_TIMEOUT: ClassVar[int] = 11  # Annotated with ClassVar
    next_event_celery_task_id: Optional[str] = None


class TeamQuestion(IssueState):
    pass


class ChannelState(BaseModel):
    workspace_name: str
    channel_id: str
    pending_issues: Optional[list[IssueState]] = []  # Default to empty list if not provided
    users: Optional[list[SlackUser]] = []            # Default to empty list if not provided
    team_questions: Optional[list[TeamQuestion]] = []  # Default to empty list if not provided
    customer_questions: Optional[list[CustomerQuestion]] = []  # Default to empty list if not provided

class ChannelStateManager:
    def __init__(self, channel_state: ChannelState, llm_caller: LLMCaller, scheduler: CeleryProvider):
        self.channel_state = channel_state
        self.scheduler = scheduler()
        self.llm_caller = llm_caller

    def handle_message(self, message_history_data: MessageHistoryData, event_data: EventData):
        llm_caller = self.llm_caller

        role = event_data.user.role
        if role == "customer":
            self.process_customer_message(event_data, llm_caller, message_history_data)

        else:
            context = AnswerToQuestionContext(
                last_messae=message_history_data.message_txt,
                last_message_history=message_history_data.last_messages_history,
                previous_context=message_history_data.previous_context_merged,
                pending_questions=[q.kicker.request for q in self.channel_state.customer_questions],
            )
            resp: AnswerToQuestion = llm_caller.is_answer_for_question(context)
            if resp.question_answered_num is not None and resp.probability_of_being_answered > 0.5:
                question = self.channel_state.customer_questions[resp.question_answered_num]
                logging.info(
                    f"Looks like question {question} was answered with probability {resp.probability_of_being_answered:.2f}%, evaluating quality of answer"
                )
                answer_quality_evaluation_context = AnswerQualityEvaluationContext(
                    last_message=message_history_data.message_txt,
                    last_messages_history=message_history_data.last_messages_history,
                    previous_context=message_history_data.previous_context_merged,
                    question_text=question.kicker.request,
                )
                answer_quality_evaluation = llm_caller.evaluate_answer_quality(answer_quality_evaluation_context, use_smart_model=True)
                logging.info(f"Evaluated {answer_quality_evaluation}")
                if answer_quality_evaluation.any_field_below_threshold():
                    logging.info(f"Does not seem that question is fully covered")
                    manager=self.get_first_manager()
#FIXME                    !!!!!!!!!!!!!!!!!!!!!!!!!!!!! send message instead!!!!!!!
                    return SendMessageAction(
                        channel_id=manager.id,
                        text=f"Hey, <@{manager.id}>! It looks like message {question.kicker.request} was not answered well, please check! \n {answer_quality_evaluation}",
                    )

                else:
                    scheduled_task_id = question.next_event_celery_task_id
                    self.scheduler.control.revoke(scheduled_task_id)
                    del self.channel_state.customer_questions[resp.question_answered_num]

    def process_customer_message(self, event_data, llm_caller, message_history_data):
        context = DynamicContextInput(
            last_message=message_history_data.message_txt,
            last_messages_history=message_history_data.last_messages_history,
        )
        resp: MessageActionable = llm_caller.is_customer_message_actionable(context)
        if resp.probability_of_being_actionable > 0.5:
            soft_ping_task = self.scheduler.send_task(
                "celery_scheduler.tasks.ping_manager_when_unanswered.soft",
                args=[self.channel_state.channel_id],
                countdown=CustomerQuestion.DEFAULT_SOFT_NOTIFICATION_TIMEOUT,
            )
            cq = CustomerQuestion(
                kicker=resp,
                initiator=event_data.user,
                ts=event_data.ts,
                next_event_celery_task_id=soft_ping_task.id,
            )
            self.channel_state.customer_questions.append(cq)

    def get_first_manager(self) -> Optional[SlackUser]:
        return next((u for u in self.channel_state.users if u.role == "manager"), None)

    def create_archive_message_url(self, ts):
        base_url = f"https://{self.channel_state.workspace_name}.slack.com/archives/"
        return f"{base_url}{self.channel_state.channel_id}/{ts}"

    def process_soft_ping(self, current_task_id: int) -> Optional[SendMessageAction]:
        for q in self.channel_state.customer_questions:
            if q.next_event_celery_task_id == current_task_id:
                manager = self.get_first_manager()
                if manager:
                    logging.info(f"Question {q.kicker.request} was not answered, sending soft to manager {manager}")
                    hard_ping_task = self.scheduler.send_task(
                        "celery_scheduler.tasks.ping_manager_when_unanswered.hard",
                        args=[self.channel_state.channel_id],
                        countdown=CustomerQuestion.DEFAULT_HARD_NOTIFICATION_TIMEOUT    ,
                    )
                    q.next_event_celery_task_id = hard_ping_task.id
                    archive_message_url = self.create_archive_message_url(q.ts)
                    return SendMessageAction(
                        channel_id=manager.id,
                        text=f"Hey, <@{manager.id}>! It looks like message {archive_message_url} was not answered, please check!",
                    )
        return None

    def process_hard_ping(self, current_task_id: int):
        for q in self.channel_state.customer_questions:
            if q.next_event_celery_task_id == current_task_id:
                manager = self.get_first_manager()
                if manager:
                    logging.info(f"Question {q.kicker.request} was not answered, sending ping to manager {manager}")
                    hard_ping_task = self.scheduler.send_task(
                        "celery_scheduler.tasks.ping_manager_when_unanswered.hard",
                        args=[self.channel_state.channel_id],
                        countdown=CustomerQuestion.DEFAULT_HARD_NOTIFICATION_TIMEOUT,
                    )
                    q.next_event_celery_task_id = hard_ping_task.id
                    archive_message_url = self.create_archive_message_url(q.ts)
                    return SendMessageAction(
                        channel_id=manager.id,
                        text=f"Hey, <@{manager.id}>! It looks like message {archive_message_url} was not answered, please check!",
                    )
