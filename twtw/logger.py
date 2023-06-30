from __future__ import annotations

import enum
import logging
import sys

import loguru
from loguru import logger as loguru_logger
from rich.console import Console
from rich.logging import RichHandler

from loguru._defaults import LOGURU_FORMAT  # noqa

console = Console(
    emoji=True,
    markup=True,
    color_system="truecolor",
    stderr=False,
)


handler = RichHandler(
    markup=True,
    rich_tracebacks=True,
    console=console,
    show_path=True,
    tracebacks_show_locals=True,
    tracebacks_suppress=("click",),
)


class InterceptHandler(logging.Handler):
    """Logging intercept handler."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        """Log the message."""
        try:
            level: int | str = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _get_logger() -> loguru.Logger:
    """Set up the logger."""
    loguru_logger.remove()
    loguru_logger.add(
        handler,
        format=lambda record: "{message}",
        enqueue=True,
        level=logging.INFO,
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=0)

    return loguru_logger


logger = _get_logger()


class VerbosityLevel(int, enum.Enum):
    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()
    DEBUG = enum.auto()
    TRACE = enum.auto()
    ALL = enum.auto()


def configure_log(verb_level: VerbosityLevel):
    verb_level = VerbosityLevel(verb_level)
    log_level = logging.getLevelName(
        "DEBUG"
        if verb_level
        in (
            VerbosityLevel.TRACE,
            VerbosityLevel.ALL,
        )
        else verb_level.name
    )
    fmt = "[bold dim cyan]{name}[/] {message}"
    for log in (logging.getLogger(n) for n in logging.root.manager.loggerDict):
        if "twtw" in log.name:
            log.setLevel(log_level)
        if (
            verb_level
            in (
                VerbosityLevel.TRACE,
                VerbosityLevel.ALL,
            )
            and "sh" not in log.name
        ):
            log.setLevel(logging.DEBUG)
        if verb_level == VerbosityLevel.ALL:
            log.setLevel(logging.DEBUG)
    logger.remove()
    loguru_level = "TRACE" if verb_level.name == "ALL" else verb_level.name
    logger.add(
        handler,
        format=fmt,
        level=loguru_level,
    )
    logging.basicConfig(handlers=[InterceptHandler()], level=0)
