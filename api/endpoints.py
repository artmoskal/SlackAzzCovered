import asyncio
import json
from functools import partial

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError, create_model
from typing import Any, Optional, Dict, TypeVar, Type
from llm.context.input import SatisfactionLevelContext
from llm.context.out import EvaluateAnswerQuality
from slack.struct.send_message_action import SendMessageAction
import importlib
import inspect
import logging
logger = logging.getLogger(__name__)

router = APIRouter()

# Generic type for dynamic Pydantic parsing
T = TypeVar("T", bound=BaseModel)

# General transformer utility
def transform_to_pydantic(data: Dict[str, Any], model: Type[T]) -> T:
    """
    Transforms a dictionary into a Pydantic model.
    This method validates the data and raises an exception if it doesn't match the model.
    """
    try:
        return model(**data)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Validation error: {e}")

# Pydantic models for incoming data
class User(BaseModel):
    id: str
    name: str
    role: str


class Message(BaseModel):
    text: str
    history: str
    channel_id: str
    user: User
    thread_ts: Optional[str]
    ts: str


class Body(BaseModel):
    message: Message


class N8nData(BaseModel):
    headers: Dict[str, Any]
    params: Dict[str, Any]
    query: Dict[str, Any]
    body: Body
    webhookUrl: str
    executionMode: str


class N8nRequest(BaseModel):
    data: N8nData


class SlackMessageRequest(BaseModel):
    channel_id: str
    text: EvaluateAnswerQuality
    thread_ts: Optional[str] = None


def discover_models(module_path: str) -> Dict[str, Type[BaseModel]]:
    """Discover all Pydantic models in a module"""
    module = importlib.import_module(module_path)
    return {
        name: obj for name, obj in inspect.getmembers(module)
        if inspect.isclass(obj)
           and issubclass(obj, BaseModel)
           and obj != BaseModel
    }

class TemplateRequest(BaseModel):
    template: str
    input_model: str
    output_model: str  # Changed from output_class
    variables: Dict[str, Any]


def get_type_from_string(type_str: str) -> Type:
    """Convert string type representation to actual type"""
    if type_str == 'str':
        return str
    elif type_str == 'int':
        return int
    elif type_str == 'float':
        return float
    elif type_str == 'List[str]':
        from typing import List
        return List[str]
    raise ValueError(f"Unsupported type: {type_str}")


def find_pydantic_class(class_name: str) -> Type[BaseModel]:
    """Find Pydantic class by name in available modules"""
    # Add your modules that contain Pydantic models here
    modules_to_check = [
        'llm.context.out',  # Add your modules here
        'llm.context.input'
    ]

    for module_name in modules_to_check:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, class_name):
                cls = getattr(module, class_name)
                if isinstance(cls, type) and issubclass(cls, BaseModel):
                    return cls
        except ImportError:
            continue

    raise ValueError(f"Pydantic class {class_name} not found")

@router.get("/models")
async def get_models():
    # Discover models from input and output modules
    input_models = discover_models("llm.context.input")
    output_models = discover_models("llm.context.out")

    models_info = {}

    # Get schema for each model
    for name, model in input_models.items():
        models_info[name] = {
            "name": name,
            "module_type": "input",
            "schema": model.model_json_schema(),  # Get complete schema including field descriptions
        }

    for name, model in output_models.items():
        models_info[name] = {
            "name": name,
            "module_type": "output",
            "schema": model.model_json_schema(),
        }

    return models_info


@router.post("/process-template")
async def process_template(request: TemplateRequest):
    try:
        # Get input model class
        input_model = find_pydantic_class(request.input_model)

        # Validate input variables using the existing model
        input_data = input_model(**request.variables)
        # Get output model
        output_model = find_pydantic_class(request.output_model)  # Changed from output_class

        # Process with LLM
        from config.container import Container
        container = Container()
        state_manager = container.state_manager()

        result = state_manager.llm_caller._get_gpt_response(
            lambda parser: state_manager.llm_caller._get_prompt_template(
                request.template,
                parser,
                list(request.variables.keys())
            ),
            input_data,
            output_model
        )

        return {
            "result": result.model_dump(),
            "input": request.variables
        }

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/analyze-satisfaction")
async def analyze_satisfaction(request: N8nRequest):
    """
    Analyze satisfaction using a generalized data transformation.
    """
    try:
        from config.container import Container  # Import here to avoid circular dependencies

        # Transform the `message` data into a SatisfactionLevelContext
        message_data = request.data.body.message.dict()
        satisfaction_context = transform_to_pydantic(message_data, SatisfactionLevelContext)

        # Call LLMCaller to analyze satisfaction
        container = Container()
        state_manager = container.state_manager()
        result = state_manager.llm_caller.get_satisfaction_level(satisfaction_context)

        return {
            "satisfaction_result": result.json(),
            "message": message_data
        }
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Validation error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
@router.get("/test")
async def test():
    from config.container import Container
    import asyncio

    container = Container()
    try:
        # Create a new event loop for the thread
        def init_slack():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return container.slack_app()

        # Run in thread pool with proper event loop
        slack_app = await asyncio.get_event_loop().run_in_executor(None, init_slack)
        return {"status": "sent"}
    except Exception as e:
        return {"error": str(e)}

@router.post("/send-slack-message")
async def send_slack_message(request: SlackMessageRequest):
    from config.container import Container
    import asyncio

    container = Container()
    try:
        # Create a new event loop for the thread
        def init_slack():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return container.slack_app()

        # Run in thread pool with proper event loop
        slack_app = await asyncio.get_event_loop().run_in_executor(None, init_slack)
        slack_message = request.text

        # Send the Slack message
        message_action = SendMessageAction(
            channel_id=request.channel_id,
            text=str(slack_message),
        )

        await slack_app.app.client.chat_postMessage(
            channel=message_action.channel_id,
            text=message_action.text,
        )

        return {"status": "sent"}
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Validation error: {e}")
  #  except Exception as e:
  #      raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

