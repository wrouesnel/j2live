"""Shared logging configuration"""

import sys
import os
import json

import logging
import structlog

_log_level = os.environ.get("LOG_LEVEL", "debug")
_debug_logs = os.environ.get("LOG_FORMAT", "kv")

_logging_configured = False


def configure_logging():
    global _logging_configured
    global _log_level
    # Note: this is here because logging is weird and Python is GIL'd.
    if _logging_configured is True:
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


configure_logging()

get_logger = structlog.get_logger
"""
Alias get_logger in structlog to encourage structlog usage.
"""

getLogger = get_logger
"""
Alias getLogger and get_logger to this module to try and make people use it.
"""
