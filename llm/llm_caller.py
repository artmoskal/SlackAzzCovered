import os
from openai import OpenAI

from jinja2 import Environment, BaseLoader


class LlmCaller:
    def __init__(self, api_token, model_name="gpt-3.5-turbo", max_tokens=600):
        """
        Initializes the LlmCaller with an API token for GPT-3.5-turbo and sets up Jinja2 for templating.
        """
        self.client = OpenAI(api_key=api_token)
        self.max_tokens = max_tokens
        self.model_name = model_name
        self.template_env = Environment(loader=BaseLoader())

    def construct_prompt(self, last_message, last_messages_history, previous_context):
        """
        Constructs the prompt to send to GPT based on the provided message information using Jinja2 for templating.
        """
        template_str = """
        You are a project manager, and a customer wrote into slack: "{{ last_message }}". 
        Note the customer username and check for it in previous conversations, basing on it figure out how frustrated customer is on the scale 1 (extremely frustrated) to 10 (very satisfied).  
        Given previous 5 messages:
        {{ last_messages_history }}
        ---
        And potentially relevant previous conversation:
        {% for convo in previous_context %}
        {{ convo }}
        {% endfor %}
        RULES:
        Do not add anything to conversation! 
        Do not imagine additional data!
        Last messages are most important to build proper context.
        Give rationale but after give only current satisfaction level (number) after ||| separator and then overall satisfaction level. E.g.:
        Now conversation is fine and customer looks satisfied, but overall he uses bad words and consider our work sloppy
        ||| 6 ||| 2 |||
        Always give two numbers!
        """
        template = self.template_env.from_string(template_str)
        return template.render(
            last_message=last_message,
            last_messages_history=last_messages_history,
            previous_context=previous_context
        )

    def get_gpt_response(self, last_message, last_messages_history, previous_context):
        """
        Uses the constructed prompt to get a response from GPT using the chat completions endpoint.
        """
        prompt = self.construct_prompt(last_message, last_messages_history, previous_context)

        chat_response = self.client.chat.completions.create(model=self.model_name,
                                                            messages=[
                                                                {"role": "system", "content": prompt}
                                                            ],
                                                            max_tokens=self.max_tokens)

        # Extracting the text of the last response
        if chat_response.choices:
            last_response = chat_response.choices[0].message.content
            return last_response.strip()
        return "No response."
