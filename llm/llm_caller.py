import logging
from typing import Any, Callable

from langchain.output_parsers import PydanticOutputParser, OutputFixingParser
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain.schema import OutputParserException

from llm.context.input import DynamicContextInput, SatisfactionLevelContext
from llm.context.out import SatisfactionLevel, MessageActionable, AnswerToQuestion, EvaluateAnswerQuality

# Configure logging
logging.basicConfig(level=logging.DEBUG)


class LLMCaller:
    def __init__(self, stupid_model: Any, smart_model: Any, template_env: Any) -> None:
        self.stupid_model = stupid_model
        self.smart_model = smart_model
        self.template_env = template_env

    def construct_sentiment_prompt(self, parser: PydanticOutputParser) -> ChatPromptTemplate:
        template = """
You are a project manager, and a customer wrote into slack: "{{ last_message }}". 
Note the customer username and check for it in previous conversations, basing on it figure out how frustrated 
customer is on the scale 1 (extremely frustrated) to 10 (very satisfied).  
Context of previous 5 messages:
{{ last_messages_history }}
RULES:
- Do not add or assume anything not provided.
- Consider the latest messages most heavily to determine the context.
- Always give two numbers (current satisfaction and overall satisvation)!
- Output directly in JSON format:
  ```json
  {
      "rationale": "<Brief rationale>",
      "current_satisfaction": <integer 1-10>,
      "overall_satisfaction": <integer 1-10>
  }
  
{{format_instructions}}
        """
        input_variables = ["last_message", "last_messages_history"]
        prompt = self._get_prompt_template(template, parser, input_variables)
        return prompt

    def construct_is_actionable_customer_message_prompt(self, parser: PydanticOutputParser) -> ChatPromptTemplate:
        template = """
You are PMO, and manager wrote into slack: "{{ last_message }}". 
Determine if it is something actionable (e.g., question, complain, anything that might require reply) or not. 
Context of previous 5 messages:
{{ last_messages_history }}
---
---
---
And potentially relevant previous parts of conversation:
{% for convo in previous_context %}
{{ convo }}
{% endfor %}
RULES:
Do not add anything to conversation! 
Do not imagine additional data!
Last messages are most important to build proper context.
Use only the provided data to assess and reformulate the customer's message (that refined question will be used out of context further on so if there are important bits in context then incorporate them).
Give question and after give only number representing the probability of message to be actionable (range 0-1).  
{{format_instructions}}
        """
        input_variables = ["last_message", "last_messages_history", "previous_context"]
        prompt = self._get_prompt_template(template, parser, input_variables)
        return prompt

    def construct_is_answer_for_question_prompt(self, parser: PydanticOutputParser) -> ChatPromptTemplate:
        template = """
You are a project manager, and a customer wrote into slack: "{{ last_message }}". 
Context of previous 5 messages:
{{ last_messages_history }}
---
---
---
And potentially relevant previous parts of conversation:
{% for convo in previous_context %}
{{ convo }}
{% endfor %}
---

You need to determine whether that answers any of following pending questions from customer:
{% for question in pending_questions %}
{{ loop.index }}. {{ question }}
{% endfor %}

RULES:
Do not add anything to conversation! 
Do not imagine additional data!
Last messages are most important to build proper context.
Output is one relevant question number and probability it is answered.
{{format_instructions}}
        """
        input_variables = ["last_message", "last_messages_history", "previous_context", "pending_questions"]
        prompt = self._get_prompt_template(template, parser, input_variables)
        return prompt

    def construct_evaluate_answer_quality_prompt(self, parser: PydanticOutputParser) -> ChatPromptTemplate:
            template = """
    You are PMO, and a manager wrote into slack: "{{ last_message }}". 
    Context of previous 5 messages:
    {{ last_messages_history }}
    ---
    ---
    ---
    And potentially relevant previous parts of conversation:
    {% for convo in previous_context %}
    {{ convo }}
    {% endfor %}
    ---

    You need to determine quality of the answer to the question from customer:
    {{ question_text }}
    
    RULES:
    Do not add anything to conversation! 
    Do not imagine additional data!
    Last messages are most important to build proper context.

    {{format_instructions}}
    Do not include any schema information, properties wrapper, or additional fields in your response.
            """
            input_variables = ["last_message", "last_messages_history", "previous_context", "question_text"]

            prompt = self._get_prompt_template(template, parser, input_variables)
            return prompt

    def _get_prompt_template(
        self,
        template: str,
        parser: PydanticOutputParser,
        input_variables: list[str]
    ) -> ChatPromptTemplate:
        return ChatPromptTemplate(
            messages=[
                HumanMessagePromptTemplate.from_template(template, template_format="jinja2")
            ],
            input_variables=input_variables,
            partial_variables={
                "format_instructions": parser.get_format_instructions(),
            },
        )

    def get_satisfaction_level(
        self,
        context: SatisfactionLevelContext,
        use_smart_model: bool = False
    ) -> SatisfactionLevel:
        return self._get_gpt_response(
            self.construct_sentiment_prompt,
            context,
            SatisfactionLevel,
            use_smart_model
        )

    def is_customer_message_actionable(
        self,
        context: DynamicContextInput,
        use_smart_model: bool = False
    ) -> MessageActionable:
        return self._get_gpt_response(
            self.construct_is_actionable_customer_message_prompt,
            context,
            MessageActionable,
            use_smart_model
        )

    def is_answer_for_question(
        self,
        context: DynamicContextInput,
        use_smart_model: bool = False
    ) -> AnswerToQuestion:
        return self._get_gpt_response(
            self.construct_is_answer_for_question_prompt,
            context,
            AnswerToQuestion,
            use_smart_model
        )

    def evaluate_answer_quality(
        self,
        context: DynamicContextInput,
        use_smart_model: bool = False
    ) -> EvaluateAnswerQuality:
        return self._get_gpt_response(
            self.construct_evaluate_answer_quality_prompt,
            context,
            EvaluateAnswerQuality,
            use_smart_model
        )

    def _get_gpt_response(
        self,
        prompt_method: Callable[[PydanticOutputParser], ChatPromptTemplate],
        context: DynamicContextInput,
        pydantic_object: type,
        use_smart_model: bool = False
    ) -> Any:
        parser = PydanticOutputParser(pydantic_object=pydantic_object)
        prompt = prompt_method(parser)
        model = self.smart_model if use_smart_model else self.stupid_model
        logging.debug(f"Prompt Template: {prompt}")
        output = None
        try:
            formatted_prompt = prompt.format_prompt(**context.to_prompt_variables())
            logging.debug(f"Formatted Prompt: {formatted_prompt}")
            output = model(formatted_prompt.to_messages())
            logging.debug(f"Model Output: {output}")
            parsed = parser.parse(output.content)
        except OutputParserException as e:
            logging.error(f"Parsing Error: {e}")
            new_parser = OutputFixingParser.from_llm(parser=parser, llm=model)
            if not output:
                logging.error("No output")
                raise e
            try:
                parsed = new_parser.parse(output.content)
            except Exception as ex:
                logging.error(f"Failed to fix output: {ex}")
                raise
        except Exception as ex:
            logging.error(f"An error occurred: {ex}")
            raise
        logging.debug(f"Parsed Output: {parsed}")
        return parsed
