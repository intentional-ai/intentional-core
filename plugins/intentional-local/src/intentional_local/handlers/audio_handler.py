# SPDX-FileCopyrightText: 2024-present ZanSara <github@zansara.dev>
# SPDX-License-Identifier: AGPL-3.0-or-later

# From https://github.com/run-llama/openai_realtime_client/blob/main/openai_realtime_client/handlers/audio_handler.py
# Original is MIT licensed.
"""
CLI handler for the bot's audio input and output.

Uses PyAudio for audio input and output, and runs a separate thread for recording and playing audio.

When playing audio, it uses a buffer to store audio data and plays it continuously to ensure smooth playback.
"""
from typing import Optional

import io
import wave
import queue
import asyncio
import threading

import pyaudio
from pydub import AudioSegment


class AudioHandler:
    """
    Handles audio input and output for the chatbot.

    Uses PyAudio for audio input and output, and runs a separate thread for recording and playing audio.

    When playing audio, it uses a buffer to store audio data and plays it continuously to ensure smooth playback.

    Args:
        audio_format:
            The audio format (paInt16).
        channels:
            The number of audio channels (1).
        rate:
            The sample rate (24000).
        chunk:
            The size of the audio buffer (1024).
    """

    def __init__(
        self,
        audio_format: int = pyaudio.paInt16,
        channels: int = 1,
        rate: int = 24000,
        chunk: int = 1024,
    ):
        # Audio parameters
        self.audio_format = audio_format
        self.channels = channels
        self.rate = rate
        self.chunk = chunk

        self.audio = pyaudio.PyAudio()

        # Recording attributes
        self.recording_stream: Optional[pyaudio.Stream] = None
        self.recording_thread = None
        self.recording = False

        # Model streaming attributes
        self.streaming = False
        self.model_stream = None

        # Playback attributes
        self.playback_stream = None
        self.playback_buffer = queue.Queue(maxsize=20)
        self.playback_event = threading.Event()
        self.playback_thread = None
        self.stop_playback = False

        self.frames = []
        self.currently_playing = False

    def start_recording(self) -> bytes:
        """Start recording audio from microphone and return bytes"""
        if self.recording:
            return b""

        self.recording = True
        self.recording_stream = self.audio.open(
            format=self.audio_format, channels=self.channels, rate=self.rate, input=True, frames_per_buffer=self.chunk
        )

        print("\nRecording... Press 'space' to stop.")

        self.frames = []
        self.recording_thread = threading.Thread(target=self._record)
        self.recording_thread.start()

        return b""  # Return empty bytes, we'll send audio later

    def _record(self):
        while self.recording:
            try:
                data = self.recording_stream.read(self.chunk)
                self.frames.append(data)
            except Exception as e:  # pylint: disable=broad-except
                print(f"Error recording: {e}")
                break

    def stop_recording(self) -> bytes:
        """Stop recording and return the recorded audio as bytes"""
        if not self.recording:
            return b""

        self.recording = False
        if self.recording_thread:
            self.recording_thread.join()

        # Clean up recording stream
        if self.recording_stream:
            self.recording_stream.stop_stream()
            self.recording_stream.close()
            self.recording_stream = None

        # Convert frames to WAV format in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf: wave.Wave_write
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.audio_format))
            wf.setframerate(self.rate)
            wf.writeframes(b"".join(self.frames))

        # Get the WAV data
        wav_buffer.seek(0)
        return wav_buffer.read()

    async def start_streaming(self, client_streaming_callback):
        """Start continuous audio streaming."""
        if self.streaming:
            return

        self.streaming = True
        self.model_stream = self.audio.open(
            format=self.audio_format, channels=self.channels, rate=self.rate, input=True, frames_per_buffer=self.chunk
        )

        print("\nStreaming audio... Press 'q' to stop.")

        while self.streaming:
            try:
                # Read raw PCM data
                data = self.model_stream.read(self.chunk, exception_on_overflow=False)
                # Stream directly without trying to decode
                await client_streaming_callback(data)
            except Exception as e:  # pylint: disable=broad-except
                print(f"Error streaming: {e}")
                break
            await asyncio.sleep(0.01)

    def stop_streaming(self):
        """Stop audio streaming."""
        self.streaming = False
        if self.model_stream:
            self.model_stream.stop_stream()
            self.model_stream.close()
            self.model_stream = None

    def play_audio(self, audio_data: bytes):
        """Add audio data to the buffer"""
        try:
            self.playback_buffer.put_nowait(audio_data)
        except queue.Full:
            # If the buffer is full, remove the oldest chunk and add the new one
            self.playback_buffer.get_nowait()
            self.playback_buffer.put_nowait(audio_data)

        if not self.playback_thread or not self.playback_thread.is_alive():
            self.stop_playback = False
            self.playback_event.clear()
            self.playback_thread = threading.Thread(target=self._continuous_playback)
            self.playback_thread.start()

    def _continuous_playback(self):
        """Continuously play audio from the buffer"""
        self.playback_stream = self.audio.open(
            format=self.audio_format, channels=self.channels, rate=self.rate, output=True, frames_per_buffer=self.chunk
        )

        while not self.stop_playback:
            try:
                audio_chunk = self.playback_buffer.get(timeout=0.1)
                self._play_audio_chunk(audio_chunk)
            except queue.Empty:
                continue

            if self.playback_event.is_set():
                break

        if self.playback_stream:
            self.playback_stream.stop_stream()
            self.playback_stream.close()
            self.playback_stream = None

    def _play_audio_chunk(self, audio_chunk):
        try:
            # Convert the audio chunk to the correct format
            audio_segment = AudioSegment(audio_chunk, sample_width=2, frame_rate=24000, channels=1)

            # Ensure the audio is in the correct format for playback
            audio_data = audio_segment.raw_data

            # Play the audio chunk in smaller portions to allow for quicker interruption
            chunk_size = 1024  # Adjust this value as needed
            for i in range(0, len(audio_data), chunk_size):
                if self.playback_event.is_set():
                    break
                chunk = audio_data[i : i + chunk_size]
                self.playback_stream.write(chunk)
        except Exception as e:  # pylint: disable=broad-except
            print(f"Error playing audio chunk: {e}")

    def stop_playback_immediately(self):
        """Stop audio playback immediately."""
        self.stop_playback = True
        self.playback_buffer.queue.clear()  # Clear any pending audio
        self.currently_playing = False
        self.playback_event.set()

    def cleanup(self):
        """Clean up audio resources"""
        self.stop_playback_immediately()

        self.stop_playback = True
        if self.playback_thread:
            self.playback_thread.join()

        self.recording = False
        if self.recording_stream:
            self.recording_stream.stop_stream()
            self.recording_stream.close()

        if self.model_stream:
            self.model_stream.stop_stream()
            self.model_stream.close()

        self.audio.terminate()