from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import ConfigError, FetchError


def retry_transient(operation: Callable[[], Any]) -> Any:
    try:
        from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
    except ImportError as exc:
        raise ConfigError("Core dependency tenacity is missing; install with: python3 -m pip install .") from exc
    wrapped = retry(
        retry=retry_if_exception_type(FetchError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
        reraise=True,
    )(operation)
    return wrapped()

