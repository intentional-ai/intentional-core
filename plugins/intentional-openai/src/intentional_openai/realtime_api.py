# SPDX-FileCopyrightText: 2024-present ZanSara <github@zansara.dev>
# SPDX-License-Identifier: AGPL-3.0-or-later

# Inspired from
# https://github.com/run-llama/openai_realtime_client/blob/main/openai_realtime_client/client/realtime_client.py
# Original is MIT licensed.
"""
Client for OpenAI's Realtime API.
"""

from typing import Optional, Callable, List, Dict, Any

import io
import os
import json
import base64
import logging
import websockets

from pydub import AudioSegment
from intentional_core import Tool


logger = logging.getLogger(__name__)


class RealtimeAPIClient:
    """
    A client for interacting with the OpenAI Realtime API that lets you manage the WebSocket connection, send text and
    audio data, and handle responses and events.
    """

    def __init__(
        self,
        api_key: str = os.environ.get("OPENAI_API_KEY", None),
        model: str = "gpt-4o-realtime-preview-2024-10-01",
        voice: str = "alloy",
        instructions: str = "You are a helpful assistant. Start the conversation with a greeting.",
        tools: Optional[List[Tool]] = None,
        event_handlers: Dict[str, Callable[[Dict[str, Any]], None]] = None,
    ):
        """
        A client for interacting with the OpenAI Realtime API that lets you manage the WebSocket connection, send text
        and audio data, and handle responses and events.

        Args:
            api_key (str):
                The API key for authentication.
            model (str):
                The model to use for text and audio processing.
            voice (str):
                The voice to use for audio output.
            instructions (str):
                The instructions for the chatbot.
            tools (List[Tool]):
                The tools to use for function calling.
            event_handlers:
                After initialization you can add event handlers to this client to handle several types of events.
                These event handlers are stored in the `event_handler` dictionary and will be invoked when the
                corresponding event occurs.

                Expected handlers:

                - `response.text.delta` (Callable[[str], None]):
                    Callback for text delta events, which mean that the model is sending text.
                    Takes in a string and returns nothing.

                - `response.audio.delta` (Callable[[bytes], None]):
                    Callback for audio delta events, which mean that the model is sending an audio snippet.
                    Takes in bytes and returns nothing.

                - `user.interruption` (Callable[[], None]):
                    Callback for user interrupt events, should be used to stop audio playback.

                More event handlers can be added to handle events triggered by functions that process the event payload.

        """
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.tools = tools or []
        self.event_handlers = {
            "response.text.delta": None,
            "response.audio.delta": None,
            "interruption": None,
            **(event_handlers or {}),
        }

        self.ws = None
        self.base_url = "wss://api.openai.com/v1/realtime"

        # Track current response state
        self._current_response_id = None
        self._current_item_id = None
        self._is_responding = False

    async def connect(self) -> None:
        """
        Establish WebSocket connection with the Realtime API.
        """
        url = f"{self.base_url}?model={self.model}"
        headers = {"Authorization": f"Bearer {self.api_key}", "OpenAI-Beta": "realtime=v1"}
        self.ws = await websockets.connect(url, extra_headers=headers)

        # Set up default session configuration
        tools = [t.to_openai_tool()["function"] for t in self.tools]
        for t in tools:
            t["type"] = "function"  # TODO: OpenAI docs didn't say this was needed, but it was

        await self._update_session(
            {
                "modalities": ["text", "audio"],
                "instructions": self.instructions,
                "voice": self.voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 500,
                    "silence_duration_ms": 200,
                },
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.8,
            }
        )

    async def handle_messages(self) -> None:
        """
        Handles events coming from the WebSocket connection.

        This method is an infinite loop that listens for messages from the WebSocket connection and processes them
        accordingly. It also triggers the event handlers for the corresponding event types.

        To react to a specific event, simply add a handler to the `event_handlers` dictionary with the event type as
        the key. To see what events are being processed, enable debug logging or add a generic handler with a "*" key.
        Keep in mind that this will run on all events and won't prevent any other event handler to run.
        """
        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")
                logger.debug("Received event: %s", event_type)

                if event_type == "error":
                    logger.error("An error response was returned: %s", event)

                # Track response state
                elif event_type == "response.created":
                    self._current_response_id = event.get("response", {}).get("id")
                    self._is_responding = True

                elif event_type == "response.output_item.added":
                    self._current_item_id = event.get("item", {}).get("id")

                elif event_type == "response.done":
                    self._is_responding = False
                    self._current_response_id = None
                    self._current_item_id = None

                # Handle interruptions
                elif event_type == "input_audio_buffer.speech_started":
                    logger.debug("Speech detected")
                    if self._is_responding:
                        await self._handle_interruption()
                    if "user.interruption" in self.event_handlers:
                        self.event_handlers["user.interruption"]()

                elif event_type == "input_audio_buffer.speech_stopped":
                    logger.debug("Speech ended")

                # Now run user defined event handlers
                if "*" in self.event_handlers:
                    self.event_handlers["*"](event)

                if event_type in self.event_handlers:
                    self.event_handlers[event_type](event)

        except websockets.exceptions.ConnectionClosed:
            logging.info("Connection closed")
        except Exception as e:  # pylint: disable=broad-except
            logging.exception("Error in message handling: %s", str(e))

    async def _update_session(self, config: Dict[str, Any]) -> None:
        """
        Update session configuration.

        Args:
            config (Dict[str, Any]):
                The new session configuration.
        """
        event = {"type": "session.update", "session": config}
        await self.ws.send(json.dumps(event))

    async def _send_text(self, text: str) -> None:
        """
        Send text message to the API.

        Args:
            text (str):
                The text message to send.
        """
        event = {
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]},
        }
        await self.ws.send(json.dumps(event))
        await self._create_response()

    async def _send_audio(self, audio_bytes: bytes) -> None:
        """
        Send audio data to the API.

        Args:
            audio_bytes (bytes):
                The audio data to send.
        """
        # Convert audio to required format (24kHz, mono, PCM16)
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        pcm_data = base64.b64encode(audio.raw_data).decode()

        # Append audio to buffer
        append_event = {"type": "input_audio_buffer.append", "audio": pcm_data}
        await self.ws.send(json.dumps(append_event))

        # Commit the buffer
        commit_event = {"type": "input_audio_buffer.commit"}
        await self.ws.send(json.dumps(commit_event))

    async def _stream_audio(self, audio_chunk: bytes) -> None:
        """
        Stream raw audio data to the API.

        Args:
            audio_chunk (bytes):
                The audio data to stream.
        """
        audio_b64 = base64.b64encode(audio_chunk).decode()
        append_event = {"type": "input_audio_buffer.append", "audio": audio_b64}
        await self.ws.send(json.dumps(append_event))

    async def _send_function_result(self, call_id: str, result: Any) -> None:
        """
        Send function call result back to the API.

        Args:
            call_id (str):
                The ID of the function call.
            result (Any):
                The result of the function call.
        """
        event = {
            "type": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": call_id, "output": result},
        }
        await self.ws.send(json.dumps(event))

        # functions need a manual response
        await self._create_response()

    async def _create_response(self, functions: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Request a response from the API.
        Needed for all messages that are not streamed in a continuous flow like the audio.

        Args:
            functions (Optional[List[Dict[str, Any]]]):
                The functions to call on the response, if any.
        """
        event = {"type": "response.create", "response": {"modalities": ["text", "audio"]}}
        if functions:
            event["response"]["tools"] = functions
        await self.ws.send(json.dumps(event))

    async def _handle_interruption(self) -> None:
        """
        Handle user interruption of the current response.
        """
        if not self._is_responding:
            return

        logging.info("\n[Handling interruption]")

        # Cancel the current response
        if self._current_response_id:
            await self._cancel_response()

        # Truncate the conversation item to what was actually played
        if self._current_item_id:
            await self._truncate_response()

        self._is_responding = False
        self._current_response_id = None
        self._current_item_id = None

    async def _cancel_response(self) -> None:
        """Cancel the current response."""
        event = {"type": "response.cancel"}
        await self.ws.send(json.dumps(event))

    async def _truncate_response(self) -> None:
        """
        Truncate the conversation item to match what was actually played.
        Necessary to correctly handle interruptions.
        """
        if self._current_item_id:
            event = {"type": "conversation.item.truncate", "item_id": self._current_item_id}
            await self.ws.send(json.dumps(event))

    # async def call_tool(self, event: Dict[str, Any] ) -> None:
    #     call_id = event["call_id"]
    #     tool_name = event['name']
    #     tool_arguments = json.loads(event['arguments'])

    #     tool_selection = ToolSelection(
    #         tool_id="tool_id",
    #         tool_name=tool_name,
    #         tool_kwargs=tool_arguments
    #     )

    #     # avoid blocking the event loop with sync tools
    #     # by using asyncio.to_thread
    #     tool_result = await asyncio.to_thread(
    #         call_tool_with_selection,
    #         tool_selection,
    #         self.tools,
    #         verbose=True
    #     )
    #     await self.send_function_result(call_id, str(tool_result))

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self.ws:
            await self.ws.close()
