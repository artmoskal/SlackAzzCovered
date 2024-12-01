from pydantic import BaseModel, Field

class SatisfactionLevel(BaseModel):
    rationale: str = Field(description="AI's philosophy about what is going on in context of the last message.")
    current_satisfaction: int = Field(description="Current satisfaction level of the customer number (1-10).")
    overall_satisfaction: int = Field(description="Overall satisfaction level of the customer based on the trend.")


class MessageActionable(BaseModel):
    request: str = Field(
        description="Customer's question, request or complaint. Reformulated to include all relevant context. Don't insert any reply here, just reformulate input wording assuming context!")
    probability_of_being_actionable: float = Field(
        ge=0, le=1,
        description="""How likely this is being actionable versus being just 
        a general statement which will not require 
        any action from the team (probability)."""
    )

class AnswerToQuestion(BaseModel):
    question_answered_num: int = Field(ge=0, le=10, description="Number of question addressed by this message.")
    probability_of_being_answered: float = Field(ge=0, le=1, description="How likely this question is being answered.")

class EvaluateAnswerQuality(BaseModel):
    question_fully_answered: int = Field(ge=0, le=10, description="Determines whether this specifiic question is being answered and answer is fully and clear.")
    is_deadline_needed_and_set: int = Field(ge=0, le=10, description="If question assumes that it might require any delivery timeline or implementation timeframe then answer should point it. Determines if timeframe is clearly defined.")
    politeness_level: int = Field(ge=0, le=10, description="Determines how polite answer is.")
    general_suggestions: str = Field(description="If you would answer the question what could be improved here?")
    def any_field_below_threshold(self, threshold: int = 8) -> bool:
        """Checks if any integer field has a value less than the threshold."""
        return any(
            getattr(self, field) < threshold
            for field in self.__fields__
            if isinstance(getattr(self, field), int)
        )

    def __str__(self):
        """Custom string representation for better readability."""
        fields = [
            f"Question Fully Answered: {self.question_fully_answered}",
            f"Deadline Needed & Set: {self.is_deadline_needed_and_set}",
            f"Politeness Level: {self.politeness_level}",
            f"General Suggestions: {self.general_suggestions}"
        ]
        return "\n".join(fields)