"""
Provider-abstracted vision client.

Chain: Pioneer (when configured) → Gemini (always available as fallback).
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path

import google.genai as genai

from src.common.config import config

logger = logging.getLogger(__name__)


class VisionProviderError(Exception):
    pass


class NotSupported(VisionProviderError):
    """Raised when the provider does not support the requested capability."""


class VisionProvider(ABC):
    @abstractmethod
    async def analyze_frames(self, frames: list[Path], prompt: str) -> dict:
        """Send frames + prompt, return parsed JSON dict."""


class GeminiVisionAdapter(VisionProvider):
    def __init__(self) -> None:
        self._client = genai.Client(api_key=config.gemini.api_key)

    async def analyze_frames(self, frames: list[Path], prompt: str) -> dict:
        if not frames:
            raise VisionProviderError("No frames provided to GeminiVisionAdapter")

        parts: list = [prompt]
        for frame in frames:
            uploaded = await self._client.aio.files.upload(file=frame)
            parts.append(uploaded)

        response = await self._client.aio.models.generate_content(
            model=config.gemini.model_name,
            contents=parts,
        )
        raw = response.text
        cleaned = re.sub(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", r"\1", raw.strip(), flags=re.DOTALL).strip()
        return json.loads(cleaned)


class PioneerVisionAdapter(VisionProvider):
    """Stub — multimodal endpoint not yet confirmed. Falls through to Gemini."""

    async def analyze_frames(self, frames: list[Path], prompt: str) -> dict:
        raise NotSupported("Pioneer multimodal not yet confirmed; falling back to Gemini")


def build_vision_chain() -> list[VisionProvider]:
    """Return ordered list of providers per VISION_PROVIDER config."""
    import os
    primary = os.getenv("VISION_PROVIDER", "gemini").lower()
    if primary == "pioneer":
        return [PioneerVisionAdapter(), GeminiVisionAdapter()]
    return [GeminiVisionAdapter()]


async def analyze_frames_with_fallback(frames: list[Path], prompt: str) -> dict:
    """Try providers in order; raise VisionProviderError only if all fail."""
    chain = build_vision_chain()
    last_exc: Exception | None = None
    for provider in chain:
        try:
            return await provider.analyze_frames(frames, prompt)
        except NotSupported as exc:
            logger.debug("Provider %s not supported: %s", type(provider).__name__, exc)
            last_exc = exc
        except Exception as exc:
            logger.warning("Provider %s failed: %s", type(provider).__name__, exc)
            last_exc = exc
    raise VisionProviderError(f"All vision providers failed: {last_exc}")
