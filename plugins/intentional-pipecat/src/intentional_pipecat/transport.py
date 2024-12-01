# SPDX-FileCopyrightText: 2024-present ZanSara <github@zansara.dev>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Pipecat transport class implementation that is compatible with Intentional.
"""
from typing import Callable

import asyncio
import structlog

from pipecat.frames.frames import Frame, InputAudioRawFrame, StartFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams, BaseTransport


log = structlog.get_logger(logger_name=__name__)


class AudioInputTransport(BaseInputTransport):
    """
    Pipecat input transport class implementation that is compatible with Intentional (supports audio only).

    This class' task is to take the user's input and convert it into frames that Pipecat can process.
    """

    def __init__(self, params: TransportParams):
        super().__init__(params)
        self.ready = False

    async def send_audio_frame(self, audio: bytes):
        """
        Public method used by the Intentional bot structure to publish audio of user's speech to the Pipecat pipeline.
        """
        if not self.ready:
            log.debug("Audio input transport not ready yet, won't send this audio frame")
            return
        frame = InputAudioRawFrame(
            audio=audio,
            sample_rate=16000,
            num_channels=self._params.audio_in_channels,
        )
        await self.push_audio_frame(frame)

    async def start(self, frame: StartFrame):
        """
        Starts the transport's resources.
        """
        log.debug("Starting audio input transport")
        await super().start(frame)
        self.ready = True

    async def cleanup(self):
        """
        Cleans up the transport's resources.
        """
        await super().cleanup()


class AudioOutputTransport(BaseOutputTransport):
    """
    Pipecat output transport class implementation that is compatible with Intentional (supports audio only).

    This class' task is to take the audio frames generated by the TTS and publish them through events that Intentional
    can understand.
    """

    def __init__(self, params: TransportParams, emitter_callback: Callable):
        super().__init__(params)
        self._emitter_callback = emitter_callback

    async def start(self, frame: StartFrame):
        """
        Starts the transport's resources.
        """
        await super().start(frame)

    async def cleanup(self):
        """
        Cleans up the transport's resources.
        """
        await super().cleanup()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """
        When it receives a TTSAudioRawFrame, makes the llm emit a `on_audio_message_from_llm` event with the content
        of the frame.
        """
        if isinstance(frame, TTSAudioRawFrame):
            await self._emitter_callback("on_audio_message_from_llm", {"delta": frame.audio})
        # return await super().process_frame(frame, direction)

    async def _audio_out_task_handler(self):
        """
        Internal: overrides the method of the base class to not perform a few actions we don't need.
        """
        try:
            async for frame in self._next_audio_frame():
                # Also, push frame downstream in case anyone else needs it.
                await self.push_frame(frame)
                # Send audio.
                await self.write_raw_audio_frames(frame.audio)
        except asyncio.CancelledError:
            pass
        except Exception as e:  # pylint: disable=broad-except
            log.exception(f"{self} error writing to microphone: {e}")


class AudioTransport(BaseTransport):
    """
    Pipecat transport class implementation that is compatible with Intentional (supports audio only).

    This class is a simple wrapper around AudioInputTransport and AudioOutputTransport, that makes sure both classes
    receive the same parameters at initialization.
    """

    def __init__(self, params: TransportParams, emitter_callback: Callable):
        super().__init__(params)
        self._emitter_callback = emitter_callback
        self._params = params
        self._input = AudioInputTransport(self._params)
        self._output = AudioOutputTransport(self._params, self._emitter_callback)

    def input(self) -> AudioInputTransport:
        return self._input

    def output(self) -> AudioOutputTransport:
        return self._output