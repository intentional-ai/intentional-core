# SPDX-FileCopyrightText: 2024-present ZanSara <github@zansara.dev>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Functions to load model client classes from config files.
"""
from typing import Optional, Dict, Any

import logging
from abc import abstractmethod


logger = logging.getLogger(__name__)


# class Modality(Enum):
#     TEXT = "text"
#     TEXT_STREAMING = "text_streaming"
#     AUDIO = "audio"
#     AUDIO_STREAMING = "audio_streaming"
#     IMAGE = "image"
#     VIDEO = "video"
#     VIDEO_STREAMING = "video_streaming"


_MODELCLIENT_CLASSES = {}
""" This is a global dictionary that maps model client names to their classes """


class ModelClient:
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


class TurnBasedModelClient:
    """
    Base class for model clients that support turn-based message exchanges, as opposed to continuous streaming of data.
    """

    @abstractmethod
    async def send_message(self, message: Dict[str, Any]) -> None:
        """
        Send a message to the model.
        """


class ContinuousStreamModelClient:
    """
    Base class for model clients that support continuous streaming of data, as opposed to turn-based message exchanges.
    """

    @abstractmethod
    async def connect(self) -> None:
        """
        Connect to the model.
        """

    @abstractmethod
    async def stream_data(self, data: bytes) -> None:
        """
        Stream data to the model.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Disconnect from the model.
        """


def load_model_client_from_dict(config: Dict[str, Any]) -> ModelClient:
    """
    Load a model client from a dictionary configuration.

    Args:
        config: The configuration dictionary.

    Returns:
        The ModelClient instance.
    """
    # List all the subclasses of ModelClient for debugging purposes
    logger.debug("Known model client classes: %s", ModelClient.__subclasses__())

    # Get all the subclasses of ModelClient
    for subclass in ModelClient.__subclasses__():
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
    return _MODELCLIENT_CLASSES[class_](config)