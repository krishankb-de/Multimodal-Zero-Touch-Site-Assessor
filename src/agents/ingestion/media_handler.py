"""
File format validation for the Ingestion Agent.

Validates that uploaded files match the expected media type before
sending them to Gemini for processing.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

ALLOWED_VIDEO = {".mp4", ".mov", ".webm"}
ALLOWED_PHOTO = {".jpeg", ".jpg", ".png", ".heic"}
ALLOWED_PDF = {".pdf"}


class MediaType(str, Enum):
    VIDEO = "video"
    PHOTO = "photo"
    PDF = "pdf"


class UnsupportedFormatError(ValueError):
    """Raised when a file format is not supported."""
    pass


def validate_video_format(file_path: Path) -> None:
    """Raises UnsupportedFormatError if not MP4, MOV, or WEBM."""
    suffix = file_path.suffix.lower()
    if suffix not in ALLOWED_VIDEO:
        raise UnsupportedFormatError(
            f"Unsupported video format '{suffix}'. "
            f"Allowed formats: {', '.join(sorted(ALLOWED_VIDEO))}"
        )


def validate_photo_format(file_path: Path) -> None:
    """Raises UnsupportedFormatError if not JPEG, JPG, PNG, or HEIC."""
    suffix = file_path.suffix.lower()
    if suffix not in ALLOWED_PHOTO:
        raise UnsupportedFormatError(
            f"Unsupported photo format '{suffix}'. "
            f"Allowed formats: {', '.join(sorted(ALLOWED_PHOTO))}"
        )


def validate_pdf_format(file_path: Path) -> None:
    """Raises UnsupportedFormatError if not PDF."""
    suffix = file_path.suffix.lower()
    if suffix not in ALLOWED_PDF:
        raise UnsupportedFormatError(
            f"Unsupported format '{suffix}'. Only PDF files are accepted."
        )


def validate_file_format(file_path: Path, media_type: MediaType) -> None:
    """Dispatches to the appropriate validator based on media_type."""
    validators = {
        MediaType.VIDEO: validate_video_format,
        MediaType.PHOTO: validate_photo_format,
        MediaType.PDF: validate_pdf_format,
    }
    validators[media_type](file_path)
