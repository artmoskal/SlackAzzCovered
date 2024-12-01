from icecream import ic
from transitions.extensions import HierarchicalMachine as Machine
import json
import logging

from config.container import Container

# Set up logging
logging.basicConfig(level=logging.INFO)


class SlackHSM:
    def __init__(self, name, redis_client):
        self.name = name
        self.redis_client = redis_client
        self.state = 'initialized'  # Default initial state
        self.load_state()

        states = ['initialized',
                  {'name': 'channel-info-received', 'children': [
                      {'name': 'message_arrived', 'children': [
                          {'name': 'customer_message', 'children': [
                              'no_action',
                              {'name': 'parallel', 'parallel': True, 'children': [
                                  {'name': 'action_needed', 'children': [
                                      'organizational',
                                      'technical',
                                      'frustration',
                                      'status'
                                  ]},
                                  {'name': 'waiting_for_team_answer', 'children': [
                                      {'name': 'team_response', 'children': [
                                          {'name': 'issue_covered', 'children': [
                                              {'name': 'waiting_for_confirmation', 'children': [
                                                  'confirmation_received'
                                              ]},
                                              'idle'
                                          ]}
                                      ]}
                                  ]}
                              ]}
                          ]},
                          {'name': 'team_initiated_message', 'children': [
                              {'name': 'interaction_required', 'children': [
                                  'issue_addressed',  # This can be expanded similarly to 'issue_covered'
                                  'idle'
                              ]}
                          ]}
                      ]}
                  ]}
                  ]

        self.machine = Machine(model=self, states=states, initial='initialized', ignore_invalid_triggers=True)

        # Adding transitions
        self.machine.add_transition('receive_channel_info', 'initialized', 'channel_info_received')
        self.machine.add_transition('message_received', 'channel_info_received', 'message_arrived')
        self.machine.add_transition('classify_message', 'message_arrived', 'customer_message', conditions=['is_customer_message'])

        # Adding transitions to handle customer message categorization and resolution
        self.machine.add_transition('require_no_action', 'customer_message', 'no_action')
        self.machine.add_transition('require_action', 'customer_message', 'action_needed_organizational', conditions=['is_organizational'], prepare='prepare_action')
        self.machine.add_transition('receive_team_response', 'waiting_for_team_answer', 'team_response_issue_covered')
        self.machine.add_transition('confirm_issue', 'waiting_for_confirmation', 'confirmation_received', after='action_completed')

    def is_customer_message(self, message):
        return message['type'] == 'customer'

    def is_organizational(self, message):
        return message.get('category') == 'organizational'

    def prepare_action(self, message):
        logging.info(f"Preparing action for message: {message['content']}")

    def action_completed(self):
        logging.info(f"Action completed successfully for state: {self.state}")

    def on_enter(self, state):
        logging.info(f"Entering state: {state}")
        self.save_state()

    def save_state(self):
        state_data = json.dumps(self.state)
        self.redis_client.set(f'state:{self.name}', state_data)
        logging.info(f"State saved: {self.state}")

    def load_state(self):
        state_data = self.redis_client.get(f'state:{self.name}')
        if state_data:
            self.state = json.loads(state_data)
            logging.info(f"State loaded: {self.state}")
        else:
            self.state = 'initialized'
            logging.info("No state found. Initialized state set.")


# Example usage
if __name__ == "__main__":
    container = Container()
    redis_client = container.redis_client()
    slack_hsm = SlackHSM("example_hsm", redis_client)
    slack_hsm.machine.message_received({"content": "Hello World"})
    ic(slack_hsm.machine)