"""
TTS Provider Abstraction for Dengbej Daily Audio.

This module defines the interface that any TTS provider must implement.
When a Kurdish TTS provider becomes available, implement the TTSProvider
interface and configure the daily_audio Lambda to use it.

Current status: No production TTS provider (Kurdish not supported by Polly).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class TTSResult:
    """Result from a TTS synthesis operation."""
    audio_data: bytes
    duration_seconds: float
    provider: str
    voice_id: str
    language: str
    format: str  # e.g., "mp3"
    chars_synthesized: int


class TTSProvider(ABC):
    """Abstract base class for TTS providers."""

    @abstractmethod
    def synthesize(self, text: str, language: str = "ku", voice_id: Optional[str] = None) -> TTSResult:
        """
        Synthesize text to speech.

        Args:
            text: The text to synthesize (Kurdish Kurmanji)
            language: Language code (default "ku" for Kurmanji)
            voice_id: Optional specific voice identifier

        Returns:
            TTSResult with audio data and metadata

        Raises:
            TTSError: If synthesis fails
        """
        pass

    @abstractmethod
    def supports_language(self, language: str) -> bool:
        """Check if the provider supports the given language."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'polly', 'google', 'custom')."""
        pass


class TTSError(Exception):
    """Raised when TTS synthesis fails."""
    pass


class NoTTSProvider(TTSProvider):
    """
    Placeholder provider when no Kurdish TTS is available.
    Returns graceful "unavailable" responses.
    """

    def synthesize(self, text: str, language: str = "ku", voice_id: Optional[str] = None) -> TTSResult:
        raise TTSError("No Kurdish TTS provider is currently configured. Audio generation is deferred.")

    def supports_language(self, language: str) -> bool:
        return False

    @property
    def provider_name(self) -> str:
        return "none"


# Future implementations would look like:
#
# class KurdishTTSProvider(TTSProvider):
#     """Example future Kurdish TTS implementation."""
#
#     def __init__(self, api_key: str, endpoint: str):
#         self.api_key = api_key
#         self.endpoint = endpoint
#
#     def synthesize(self, text, language="ku", voice_id=None):
#         # Call the Kurdish TTS API
#         # Return TTSResult with audio bytes
#         pass
#
#     def supports_language(self, language):
#         return language in ("ku", "kmr")  # Kurmanji codes
#
#     @property
#     def provider_name(self):
#         return "kurdish-tts-service"


def get_tts_provider() -> TTSProvider:
    """
    Factory function to get the configured TTS provider.

    To plug in a new provider:
    1. Implement TTSProvider interface
    2. Update this function to return the new provider
    3. Add any required env vars / credentials
    """
    # Currently: no Kurdish TTS available
    return NoTTSProvider()
