from langchain_community.chat_models.openai import ChatOpenAI
from pydantic.v1 import BaseModel, Field
from langchain.llms import OpenAI
from langchain.output_parsers import PydanticOutputParser
from jinja2 import Environment, BaseLoader
import logging
from langchain.llms import OpenAI as LangChainOpenAI
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain.output_parsers import OutputFixingParser
from langchain.schema import OutputParserException
from icecream import ic
# Step 1: Define your Pydantic model
class SatisfactionLevels(BaseModel):
    rationale: str = Field(description="AI's phylosophy about what is going on in context of the last message.")
    current_satisfaction: int = Field(description="Current satisfaction level of the customer.")
    overall_satisfaction: int = Field(description="Overall satisfaction level of the customer based on the trend.")


class LlmCaller:
    def __init__(self, api_token, model_name="gpt-3.5-turbo", max_tokens=600):
        """
        Initializes the LlmCaller with an API token for GPT-3.5-turbo and sets up Jinja2 for templating.
        """
        self.llm = ChatOpenAI(
            model=model_name,
            openai_api_key=api_token,
            max_tokens=max_tokens
        )
        # LangChainOpenAI(model=model_name, openai_api_key=api_token, max_tokens=max_tokens)

        self.max_tokens = max_tokens
        self.model_name = model_name
        self.template_env = Environment(loader=BaseLoader())
        # Initialize the parser with your Pydantic model
        self.parser = PydanticOutputParser(pydantic_object=SatisfactionLevels)

    def construct_prompt(self, last_message, last_messages_history, previous_context):
        prompt = ChatPromptTemplate(
            messages=[
                HumanMessagePromptTemplate.from_template("""
You are a project manager, and a customer wrote into slack: "{{ last_message }}". 
Note the customer username and check for it in previous conversations, basing on it figure out how frustrated 
customer is on the scale 1 (extremely frustrated) to 10 (very satisfied).  
Given previous 5 messages:
{{ last_messages_history }}
---
---
---
And potentially relevant previous conversation:
{% for convo in previous_context %}
{{ convo }}
{% endfor %}
RULES:
Do not add anything to conversation! 
Do not imagine additional data!
Last messages are most important to build proper context.
Give rationale but after give only current satisfaction level (number) and then overall satisfaction level.
Always give two numbers!
{{format_instructions}}
        """, template_format="jinja2")
            ],
            input_variables=["last_message", "last_messages_history", "previous_context"],
            partial_variables={
                "format_instructions": self.parser.get_format_instructions(),
            },
        )
        return prompt

    def get_gpt_response(self, last_message, last_messages_history, previous_context):
        """
        Uses the constructed prompt to get a response from GPT using the chat completions endpoint.
        """
        prompt = self.construct_prompt(last_message, last_messages_history, previous_context)

        logging.debug(prompt)
        # TODO Is one system role and content good approach?
        _input = prompt.format_prompt(last_message=last_message, last_messages_history=last_messages_history,
                                      previous_context=previous_context)
        ic(_input)
        output = self.llm(_input.to_messages())
        logging.debug(f"Response: {output.content}")
        try:
            parsed = self.parser.parse(output.content)
        except OutputParserException as e:
            new_parser = OutputFixingParser.from_llm(
                parser=self.parser,
                llm=self.llm
            )
            parsed = new_parser.parse(output.content)

        logging.debug(f"Parsed: {parsed}")
        # The parsed_response is now an instance of SatisfactionLevels
        return parsed
