"""Shared logging configuration"""

import sys
import os
import json

import logging

try:
    import structlog
except ImportError:
    # Not packaged on every distribution; fall back to the stdlib
    structlog = None

_log_level = os.environ.get("LOG_LEVEL", "info")
_debug_logs = os.environ.get("LOG_FORMAT", "kv")

_logging_configured = False


def configure_logging():
    global _logging_configured
    global _log_level
    # Note: this is here because logging is weird and Python is GIL'd.
    if _logging_configured is True:
        return

    if structlog is None:
        _configure_stdlib_logging()
        _logging_configured = True
        return

    structlog.configure_once(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(remove_positional_args=False),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    pre_chain = [
        # Add the log level and a timestamp to the event_dict if the log entry
        # is not from structlog.
        structlog.stdlib.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # The rules: all logs go to stdout and all logs are formatted as JSON.
    if _debug_logs.lower() == "kv" or _debug_logs.lower() == "keyvalue":
        processor = structlog.processors.KeyValueRenderer(
            key_order=["event"], drop_missing=True, sort_keys=True
        )
    else:
        processor = structlog.processors.JSONRenderer(serializer=json.dumps)
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=processor, foreign_pre_chain=pre_chain
    )


    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging._nameToLevel[_log_level.upper()])

    root_logger.info("Logging configured")

    _logging_configured = True


def _configure_stdlib_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging._nameToLevel[_log_level.upper()])


class _KeyValueLogger:
    """The subset of structlog's logger interface used here, on the stdlib.

    log.info("event", key=value) is rendered as: event key='value'
    """

    def __init__(self, name=None):
        self._logger = logging.getLogger(name)

    def _log(self, level, event, *args, exc_info=None, **kw):
        if not self._logger.isEnabledFor(level):
            return
        message = event % args if args else event
        if kw:
            message += " " + " ".join("%s=%r" % item for item in sorted(kw.items()))
        self._logger.log(level, message, exc_info=exc_info)

    def debug(self, event, *args, **kw):
        self._log(logging.DEBUG, event, *args, **kw)

    def info(self, event, *args, **kw):
        self._log(logging.INFO, event, *args, **kw)

    def warning(self, event, *args, **kw):
        self._log(logging.WARNING, event, *args, **kw)

    warn = warning

    def error(self, event, *args, **kw):
        self._log(logging.ERROR, event, *args, **kw)

    def exception(self, event, *args, **kw):
        kw.setdefault("exc_info", True)
        self._log(logging.ERROR, event, *args, **kw)

    def critical(self, event, *args, **kw):
        self._log(logging.CRITICAL, event, *args, **kw)


configure_logging()

get_logger = structlog.get_logger if structlog is not None else _KeyValueLogger
"""
Alias get_logger in structlog to encourage structlog usage.
"""

getLogger = get_logger
"""
Alias getLogger and get_logger to this module to try and make people use it.
"""
