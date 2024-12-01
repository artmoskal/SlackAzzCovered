from pydantic import BaseModel


class DynamicContextInput(BaseModel):
    last_message: str
    last_messages_history: str

    def to_prompt_variables(self):
        return self.dict()


class SatisfactionLevelContext(DynamicContextInput):
    pass


class MessageActionableContext(DynamicContextInput):
    previous_context: dict


class AnswerToQuestionContext(DynamicContextInput):
    previous_context: dict
    pending_questions: list[str]

class AnswerQualityEvaluationContext(DynamicContextInput):
    answer: str