# SPDX-FileCopyrightText: 2024-present ZanSara <github@zansara.dev>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Functions to load model client classes from config files.
"""
from typing import Optional, Dict, Any, Set, TYPE_CHECKING

import logging
from abc import ABC, abstractmethod

from intentional_core.utils import inheritors
from intentional_core.events import EventEmitter
from intentional_core.intent_routing import IntentRouter

if TYPE_CHECKING:
    from intentional_core.bot_structure import BotStructure


logger = logging.getLogger("intentional")


_MODELCLIENT_CLASSES = {}
""" This is a global dictionary that maps model client names to their classes """

KNOWN_MODEL_EVENTS = [
    "*",
    "on_error",
    "on_model_connection",
    "on_model_disconnection",
    "on_system_prompt_updated",
    "on_model_starts_generating_response",
    "on_model_stops_generating_response",
    "on_text_message_from_model",
    "on_audio_message_from_model",
    "on_user_speech_started",
    "on_user_speech_ended",
    "on_user_speech_transcribed",
    "on_model_speech_transcribed",
    "on_conversation_ended",
]


class ModelClient(ABC, EventEmitter):
    """
    Tiny base class used to recognize Intentional model clients.

    In order for your client to be usable, you need to assign a value to the `_name` class variable
    in the client class' definition.
    """

    name: Optional[str] = None
    """
    The name of the client. This should be a unique identifier for the client type.
    This string will be used in configuration files to identify the type of client to serve a model from.
    """

    def __init__(self, parent: "BotStructure", intent_router: IntentRouter) -> None:
        """
        Initialize the model client.

        Args:
            parent: The parent bot structure.
        """
        super().__init__(parent)
        self.intent_router = intent_router

    async def connect(self) -> None:
        """
        Connect to the model.
        """
        await self.emit("on_model_connection", {})

    async def disconnect(self) -> None:
        """
        Disconnect from the model.
        """
        await self.emit("on_model_disconnection", {})

    @abstractmethod
    async def run(self) -> None:
        """
        Handle events from the model by either processing them internally or by translating them into higher-level
        events that the BotStructure class can understand, then re-emitting them.
        """

    @abstractmethod
    async def send(self, data: Dict[str, Any]) -> None:
        """
        Send a unit of data to the model. The response is streamed out as an async generator.
        """

    @abstractmethod
    async def update_system_prompt(self) -> None:
        """
        Update the system prompt in the model.
        """

    @abstractmethod
    async def handle_interruption(self, lenght_to_interruption: int) -> None:
        """
        Handle an interruption while rendering the output to the user.

        Args:
            lenght_to_interruption: The length of the data that was produced to the user before the interruption.
                This value could be number of characters, number of words, milliseconds, number of audio frames, etc.
                depending on the bot structure that implements it.
        """


class TurnBasedModelClient(ModelClient):
    """
    Base class for model clients that support turn-based message exchanges, as opposed to continuous streaming of data.
    """


class ContinuousStreamModelClient(ModelClient):
    """
    Base class for model clients that support continuous streaming of data, as opposed to turn-based message exchanges.
    """


def load_model_client_from_dict(
    parent: "BotStructure", intent_router: IntentRouter, config: Dict[str, Any]
) -> ModelClient:
    """
    Load a model client from a dictionary configuration.

    Args:
        config: The configuration dictionary.

    Returns:
        The ModelClient instance.
    """
    # Get all the subclasses of ModelClient
    subclasses: Set[ModelClient] = inheritors(ModelClient)
    logger.debug("Known model client classes: %s", subclasses)
    for subclass in subclasses:
        if not subclass.name:
            logger.error(
                "Model client class '%s' does not have a name. This model client type will not be usable.", subclass
            )
            continue

        if subclass.name in _MODELCLIENT_CLASSES:
            logger.warning(
                "Duplicate model client type '%s' found. The older class (%s) "
                "will be replaced by the newly imported one (%s).",
                subclass.name,
                _MODELCLIENT_CLASSES[subclass.name],
                subclass,
            )
        _MODELCLIENT_CLASSES[subclass.name] = subclass

    # Identify the type of bot and see if it's known
    class_ = config.pop("client")
    logger.debug("Creating model client of type '%s'", class_)
    if class_ not in _MODELCLIENT_CLASSES:
        raise ValueError(
            f"Unknown model client type '{class_}'. Available types: {list(_MODELCLIENT_CLASSES)}. "
            "Did you forget to install your plugin?"
        )

    # Handoff to the subclass' init
    return _MODELCLIENT_CLASSES[class_](parent=parent, intent_router=intent_router, config=config)
