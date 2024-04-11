import weaviate
import weaviate.classes as wvc
import os
import requests
import json


class WeaviateConnector():
    CHANNELS_COLLECTION_NAME = "channels"

    def __init__(self, host, port, grpc_host, grpc_port, weaviate_api_key, openai_api_key):
        # Connect to a local Weaviate instance
        self.client = weaviate.connect_to_custom(
            http_host="localhost",
            http_port=8080,
            http_secure=False,
            grpc_host="localhost",
            grpc_port=50051,
            grpc_secure=False,
            auth_credentials=weaviate.auth.AuthApiKey(
                weaviate_api_key
            ),
            headers={
                "X-OpenAI-Api-Key": os.environ["OPENAI_APIKEY"]  # Replace with your inference API key
            }
        )
        self.channels = self.create_collection_if_not_exists(self.CHANNELS_COLLECTION_NAME)

    def create_collection_if_not_exists(self, name):
        self.channels = self.client.collections.create(
            name=name,
            vectorizer_config=wvc.config.Configure.Vectorizer.text2vec_openai(),
            generative_config=wvc.config.Configure.Generative.openai()
        )