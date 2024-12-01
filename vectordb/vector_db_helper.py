import logging
import re
from typing import Any
import dateutil.relativedelta
from langchain_core.retrievers import BaseRetriever
import weaviate.classes as wvc
import uuid
from datetime import datetime, timezone
import math
from utils.date_utils import ts_to_rfc3339

logger = logging.getLogger(__name__)


class CustomWeaviateRetriever(BaseRetriever):
    def __init__(self, client, **kwargs: Any):
        super().__init__(**kwargs)
        self.client = client

    async def _get_relevant_documents(self, query: str, *, run_manager = None):
        # Implement your retrieval logic here
        raise Exception("Not Implemented")

    async def retrieve(self, query, **kwargs):
        raise Exception("not implemented")


class VectorDBHelper:

    def __init__(self, client):
        self.client = client
        self.parent_chunk_max_days = 30  # Max days a conversation can span in a parent chunk
        self.parent_chunk_max_size = 10  # Max number of child chunks in a parent

    def as_retriever(self):
        return CustomWeaviateRetriever(self.client)

    async def fetch_ungrouped_messages(self, channel_id, limit=100):
        async with self.client as c:
            messages = self.get_messages_collection(c)
            result = await messages.query.fetch_objects(
                limit=limit,
                filters=wvc.query.Filter.by_property("channel_id").equal(channel_id) & wvc.query.Filter.by_ref_count(
                    link_on="hasMessageGroup").equal(0) & wvc.query.Filter.by_property("ref_count").equal(0),
                sort=wvc.query.Sort.by_property("ts", ascending=True),
                return_references=wvc.query.QueryReference(link_on="hasMessageGroup"),
            )
        return [msg for msg in result.objects if
                not msg.properties.get('thread_ts') or self.is_thread_starter(msg)]

    async def fetch_entire_thread(self, thread_ts, channel_id):
        async with self.client as c:
            messages = self.get_messages_collection(c)
            result = await messages.query.fetch_objects(
                filters=wvc.query.Filter.by_property('channel_id').equal(channel_id)
                        & wvc.query.Filter.by_property('thread_ts').equal(thread_ts),
                sort=wvc.query.Sort.by_property("ts", ascending=True)
            )
        return result.objects

    async def fetch_messages_last_3_months(self, search_text, top_k, channel_id):
        three_months_ago = datetime.now(timezone.utc) - dateutil.relativedelta.relativedelta(months=30)
        # Convert to RFC 3339 format with timezone information
        three_months_ago_iso = three_months_ago.isoformat()

        async with self.client as c:
            messages = self.get_messages_collection(c)
            result = await messages.query.near_text(
                query=search_text,
                distance=0.5,
                return_metadata=wvc.query.MetadataQuery(distance=True),
                limit=top_k,
                filters=wvc.query.Filter.by_property("channel_id").equal(channel_id) & wvc.query.Filter.by_property(
                    "ts").greater_or_equal(three_months_ago_iso)
            )
        return result

    async def delete_class_if_exists(self, class_name):
        """
        Delete a class from the Weaviate schema if it exists.
        """
        async with self.client as client:
            await client.collections.delete(class_name)
        logging.info(f"Deleted existing class '{class_name}' from schema.")

    async def add_messages(self, cleaned_messages, channel_id):
        to_insert = list()
        for message in cleaned_messages:
            rfc_3339_timestamp = ts_to_rfc3339(message['ts'])
            message['ts'] = rfc_3339_timestamp
            tts = message.get("thread_ts", None)
            message['thread_ts'] = ts_to_rfc3339(tts) if tts else None
            message['channel_id'] = channel_id
            message['ref_count'] = 0
            to_insert.append(message)

        def split_into_chunks(data, chunk_size):
            """Split the data into chunks of specified size."""
            for i in range(0, len(data), chunk_size):
                yield data[i:i + chunk_size]

        bulk_insert_size = 10  # Define the size of each chunk
        total_chunks = math.ceil(len(to_insert) / bulk_insert_size)

        async with self.client as c:
            messages = self.get_messages_collection(c)

            for i, chunk in enumerate(split_into_chunks(to_insert, bulk_insert_size), start=1):
                try:
                    await messages.data.insert_many(chunk)
                    logging.info(f"Successfully inserted chunk {i}/{total_chunks}")
                except Exception as e:
                    logging.info(f"Error inserting chunk {i}/{total_chunks}: {e}")

    async def create_schema(self):
        async with self.client as client:
            # Create the "MessageGroup" class with a reference to "Message"
            await client.collections.create(
                name="MessageGroup",
                vectorizer_config=wvc.config.Configure.Vectorizer.text2vec_transformers(),
                properties=[
                    wvc.config.Property(name="ts", data_type=wvc.config.DataType.DATE, skip_vectorization=True),
                    wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT,
                                      vectorize_property_name=False,
                                      tokenization=wvc.config.Tokenization.LOWERCASE
                                      ),
                    wvc.config.Property(name="channel_id", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                ],
            )
            # Create the "Message" class
            await client.collections.create(
                name="Message",
                vectorizer_config=wvc.config.Configure.Vectorizer.text2vec_transformers(),
                generative_config=wvc.config.Configure.Generative.cohere(),
                properties=[
                    wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT,
                                      vectorize_property_name=False,
                                      tokenization=wvc.config.Tokenization.LOWERCASE
                                      ),
                    wvc.config.Property(name="type", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                    wvc.config.Property(name="ref_count", data_type=wvc.config.DataType.INT, skip_vectorization=True),
                    wvc.config.Property(name="channel_id", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                    wvc.config.Property(name="user_id", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                    wvc.config.Property(name="user_name", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                    wvc.config.Property(name="role", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                    wvc.config.Property(name="ts", data_type=wvc.config.DataType.DATE, skip_vectorization=True),
                    wvc.config.Property(name="thread_ts", data_type=wvc.config.DataType.DATE, skip_vectorization=True),
                ],
                references=[
                    wvc.config.ReferenceProperty(
                        name="hasMessageGroup",
                        target_collection="MessageGroup",
                        inverted_index_config=wvc.config.Configure.inverted_index(
                            index_null_state=True,
                            index_property_length=False,
                            index_timestamps=True,
                        ),
                    )
                ],
            )

    def tokenize(self, text):
        """Simple tokenizer to count words in a text."""
        return len(re.findall(r'\w+', text))

    def _group_messages(self, ungrouped_messages, max_tokens=200, max_days=3):
        formed_groups = []

        current_group, current_tokens, last_ts = [], 0, None
        for message_obj in ungrouped_messages:
            message = message_obj.properties
            # FIXME add proper tokenization
            message_tokens = self.tokenize(message['text'])
            current_ts = message['ts']

            # TODO Add overlap?
            # Check token count and time gap
            if current_tokens + message_tokens > max_tokens or (last_ts and (current_ts - last_ts).days > max_days):
                if current_group:
                    formed_groups.append(current_group)
                current_group, current_tokens = [message_obj], message_tokens
            else:
                current_group.append(message_obj)
                current_tokens += message_tokens

            last_ts = current_ts
        return formed_groups

    async def ungroup(self, message_objs, client):
        unbound_message_group_ids = []
        obj_count = len(message_objs.objects)
        if 0 == obj_count:
            logging.debug("No messages to unbound, exiting")
            return unbound_message_group_ids

        logging.debug(f"Found {obj_count} messages to be unbound from message group.")
        for message_obj in message_objs.objects:
            if not message_obj.references:
                continue
            for ref in message_obj.references['hasMessageGroup'].objects:
                group_uuid = ref.uuid
                messages = self.get_messages_collection(client)
                message_uuid = message_obj.uuid
                await messages.data.update(
                    uuid=message_uuid,
                    properties={
                        "ref_count": 0,
                    }
                )
                await messages.data.reference_delete(
                    from_uuid=message_uuid,
                    from_property='hasMessageGroup',
                    to=group_uuid
                )
                unbound_message_group_ids.append(group_uuid)
        return unbound_message_group_ids

    async def ungroup_all(self):
        async with self.client as c:
            await self._ungroup_all(c)

    async def _ungroup_all(self, client):
        messages = self.get_messages_collection(client)

        message_objs = await messages.query.fetch_objects(
            limit=10,
            filters=wvc.query.Filter.by_ref_count("hasMessageGroup").greater_or_equal(1) & wvc.query.Filter.by_property(
                "ref_count").greater_or_equal(1),
            sort=wvc.query.Sort.by_property("ts", ascending=True),
            return_references=wvc.query.QueryReference(link_on="hasMessageGroup"),
        )
        deleted_message_groups = await self.ungroup(message_objs, client)
        if len(deleted_message_groups) == 0:
            return
        await self._ungroup_all(client)

    async def create_message_group_with_messages(self, message_group_object):
        """
        Creates a MessageGroup entity from the given group of messages and updates
        each message to include a reference to this MessageGroup.
        """
        # Combine texts of all messages in the group
        combined_text = self.msg_array_to_text(message_group_object)
        # TODO Think if that is correct ts
        ts_latest_message = max(msg.properties['ts'] for msg in message_group_object)

        # Create MessageGroup object
        message_group_data = {
            "text": combined_text,
            "ts": ts_latest_message.isoformat(),
            "channel_id": message_group_object[0].properties['channel_id'],
            # Assuming all messages in a group share the same channel_id
        }

        async with self.client as c:
            message_groups = self.get_message_groups_collection(c)

            message_group_uuid = uuid.uuid4()
            await message_groups.data.insert(
                properties=message_group_data,
                uuid=message_group_uuid
            )

            # Update each Message with a reference to the newly created MessageGroup
            for message in message_group_object:
                message_uuid = message.uuid
                messages = self.get_messages_collection(c)
                await messages.data.reference_add(
                    from_property="hasMessageGroup",
                    from_uuid=message_uuid,
                    to=message_group_uuid
                )

                await messages.data.update(
                    uuid=message_uuid,
                    properties={
                        "ref_count": 1,
                    }
                )

    def msg_array_to_text(self, message_group_object, include_dates=False, is_db_object=True):
        def props(msg):
            return msg.properties if is_db_object else msg

        def format_ts(ts):
            # If 'ts' is a string, parse it into a datetime object first
            if isinstance(ts, str):
                ts = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ')
            # Format the datetime object to the desired string format
            return ts.strftime('%m-%d %H:%M')

        messages = []
        for msg in message_group_object:
            # Construct the base message string with safe .get access
            base_msg = f"{props(msg).get('role', 'Unknown role')} ({props(msg).get('user_name', 'Unknown user')}): {props(msg).get('text', '')}"

            # Prepend date if needed
            if include_dates:
                formatted_date = format_ts(props(msg).get('ts', ''))  # Default to Unix epoch start if 'ts' is missing
                message = f"[{formatted_date}] {base_msg}"
            else:
                message = base_msg

            messages.append(message)

        return " \n ".join(messages)

    async def get_relevant_message_groups(self, channel_id, query, distance=0.5, limit=3):
        async with self.client as c:
            message_groups = self.get_message_groups_collection(c)
            response = await message_groups.query.near_text(
                query=query,
                distance=distance,
                filters=wvc.query.Filter.by_property("channel_id").equal(channel_id),
                limit=limit,
                return_metadata=wvc.query.MetadataQuery(distance=True)
            )
            return response

    async def get_last_x_messages(self, channel_id, limit=5):
        # TODO fetches also thread messages if these are recent. Not sure what is correct behavior here.
        async with self.client as c:
            messages = self.get_messages_collection(c)
            fetched_messages = await messages.query.fetch_objects(
                limit=limit,
                filters=wvc.query.Filter.by_property("channel_id").equal(channel_id),
                sort=wvc.query.Sort.by_property("ts", ascending=False),  # Fetch the latest messages first
                return_references=wvc.query.QueryReference(link_on="hasMessageGroup"),
            )

        # Assuming 'fetched_messages' needs to be processed to extract message objects
        # and that it's reversed to maintain the old-to-new conversational order
        messages_list = list(reversed(fetched_messages.objects)) if fetched_messages.objects else []

        return self.msg_array_to_text(messages_list, include_dates=True)

    def get_messages_collection(self, client):
        return client.collections.get("Message")

    async def delete_message_groups(self):
        async with self.client as c:
            await self.get_message_groups_collection(c).data.delete_many(
                where=wvc.query.Filter.by_property("text").like("*")
            )

    def get_message_groups_collection(self, client):
        return client.collections.get("MessageGroup")

    async def group_all_in_channel(self, channel_id):
        limit = 100  # Maximum number of messages to fetch in each call

        while True:
            logger.info("Fetching ungrouped messages...")
            res = await self.fetch_ungrouped_messages(limit=limit, channel_id=channel_id)
            ungrouped_messages = res if res else []

            # Log the outcome of the fetch
            if not ungrouped_messages:
                logger.info("No ungrouped messages found. Exiting process.")
                break
            else:
                logger.info(f"Fetched {len(ungrouped_messages)} ungrouped messages.")
            for message_obj in ungrouped_messages:
                # Check if the message is a thread starter
                if self.is_thread_starter(message_obj):
                    # Fetch the entire thread excluding the starter as it's already fetched
                    thread_messages = await self.fetch_entire_thread(message_obj.properties['thread_ts'], channel_id)

                    # Immediately create a MessageGroup for the thread
                    if thread_messages:  # Ensure the thread_messages is not empty
                        logger.info(
                            f"Creating MessageGroup for thread {message_obj.properties['thread_ts']} with {len(thread_messages)} messages.")
                        await self.create_message_group_with_messages(thread_messages)
                    continue
            logger.info("Grouping messages...")
            grouped_messages = self._group_messages(ungrouped_messages)

            if not grouped_messages:
                logger.info("No messages were grouped. Exiting process.")
                break

            # Iterate over each group of messages and create a MessageGroup for them
            for index, group in enumerate(grouped_messages):
                if group:  # Ensure the group is not empty
                    logger.info(f"Creating MessageGroup for group {index + 1} with {len(group)} messages.")
                    await self.create_message_group_with_messages(group)
                else:
                    logger.info(f"Group {index + 1} is empty. Skipping.")

            logger.info("Completed a grouping cycle. Checking for more ungrouped messages...")

    def is_thread(self, message_obj):
        return message_obj.properties.get('thread_ts') is not None

    def is_thread_starter(self, message_obj):
        return message_obj.properties.get('thread_ts') == message_obj.properties.get('ts')


    async def delete_message_group_by_thread_ts(self, mes):
        async with self.client as c:
            messages = self.get_messages_collection(c)
            thread_starter_ts = mes.get('thread_ts')
            thread_starter = await messages.query.fetch_objects(
                limit=1,
                filters=wvc.query.Filter.by_property('thread_ts').equal(thread_starter_ts) &
                        wvc.query.Filter.by_ref_count("hasMessageGroup").greater_or_equal(
                            1) & wvc.query.Filter.by_property("ref_count").greater_or_equal(
                    1),
                return_references=wvc.query.QueryReference(link_on="hasMessageGroup"),
            )
            group_uuids_to_delete = await self.ungroup(thread_starter, c)
            await self.get_message_groups_collection(c).data.delete_many(
                where=wvc.query.Filter.by_id().contains_any(group_uuids_to_delete)
            )
