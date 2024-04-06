import pytest
from datetime import datetime, timedelta
from weaviate import Client, AuthApiKey
from dotenv import load_dotenv

from vectordb.vector_db_helper import VectorDBHelper

load_dotenv()
import os

# Setup Weaviate client for testing
WEAVIATE_TEST_URL = os.environ.get("WEAVIATE_URL")  # Adjust to your test instance URL
WEAVIATE_TEST_API_KEY = os.environ.get("WEAVIATE_API_KEY")

client = Client(
    url=WEAVIATE_TEST_URL,
    auth_client_secret=AuthApiKey(WEAVIATE_TEST_API_KEY)
)

helper = VectorDBHelper(client)




@pytest.fixture(scope="module")
def setup_weaviate_schema():
    # Delete classes if they exist to ensure a fresh start
    helper.delete_class_if_exists("Message")
    helper.delete_class_if_exists("MessageGroup")


    helper.create_schema()
    yield  # This allows the test to run with the schema setup

    # Teardown logic to clean up schema
    client.schema.delete_class("Message")
    client.schema.delete_class("MessageGroup")


def test_message_chunking(setup_weaviate_schema):
    helper = VectorDBHelper(client)

    # Simulate Slack messages
    messages = [
        ("Message 1", datetime.now() - timedelta(days=31), "text", "uu", "artem"),
        ("Message 2", datetime.now() - timedelta(days=15), "text", "uu", "customer"),
        ("Message 3", datetime.now() - timedelta(seconds=3), "text", "", "artem"),
        ("Message 4", datetime.now()),
    ]

    for content, timestamp in messages:
        helper.add_message(content, timestamp)

    # Verify the creation of a new parent chunk due to time constraint
    query = """
    {
        Get {
            MessageGroup {
                createdAt
                containsMessage {
                    ... on Message {
                        content
                    }
                }
            }
        }
    }"""
    result = client.query.raw(query)
    message_groups = result['data']['Get']['MessageGroup']
    assert len(message_groups) > 1, "Expected more than one MessageGroup due to time constraint"

    # Verify the first MessageGroup contains only the first message due to the 30-day limit
    first_group_messages = message_groups[-1]['containsMessage']
    assert len(first_group_messages) == 1 and first_group_messages[0]['content'] == "Message 1", \
        "First MessageGroup did not contain exactly the first message as expected"
