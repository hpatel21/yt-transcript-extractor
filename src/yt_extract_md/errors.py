from __future__ import annotations

from .models import Reason


class ExtractorError(Exception):
    reason: Reason
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        both_caption_paths_blocked: bool = False,
        stop_batch: bool = False,
    ):
        super().__init__(message)
        self.both_caption_paths_blocked = both_caption_paths_blocked
        self.stop_batch = stop_batch


class InvalidInputError(ExtractorError):
    reason = Reason.INVALID_INPUT


class UnavailableError(ExtractorError):
    reason = Reason.UNAVAILABLE


class MissingCaptionsError(ExtractorError):
    reason = Reason.MISSING_CAPTIONS


class IpBlockedError(ExtractorError):
    reason = Reason.IP_BLOCKED
    retryable = True


class FetchError(ExtractorError):
    reason = Reason.FETCH_ERROR
    retryable = True


class ConfigError(ExtractorError):
    reason = Reason.CONFIG_ERROR


class WriteError(ExtractorError):
    reason = Reason.WRITE_ERROR
