"""Unified logging manager module.

Thread-safe logging manager built on Python logging, providing structured JSON
output, automatic rotation, an exception decorator, and ContextVar-based
Trace ID / Request ID tracking.

Features
--------
- Thread-safe singleton initialization
- Structured JSON log output (recommended for production)
- Multi-handler support: Console / JSON file / plain text / error-only file
- Automatic log rotation (by size or time)
- Exception auto-capture decorator (@log_exceptions)
- ContextVar distributed tracing (trace_id / request_id)
- Colored console output, runtime level hot-reload
- Environment variable configuration

Quick Start
-----------
>>> from src.logger import LoggerManager, LoggerConfig, get_logger, set_trace_id
>>> LoggerManager.configure(LoggerConfig(name="myapp", log_dir="logs", level="INFO"))
>>> logger = get_logger(__name__)
>>> logger.info("User logged in", extra={"user_id": 42})


See Also
--------
- LoggerManager.configure(): Initialize the logging system
- LoggerConfig: Log configuration dataclass
- log_exceptions: Exception capture decorator
- set_trace_id / set_request_id: Set tracing IDs
- get_context_ids: Get context IDs (for HTTP headers)
"""

__all__ = [
    "LoggerManager",
    "LoggerConfig",
    "get_logger",
    "log_exceptions",
    "set_trace_id",
    "set_request_id",
    "get_context_ids",
]

import copy
import logging
import logging.config
import os
import sys
import json
import functools
import threading
import traceback
from pathlib import Path
from typing import Optional, Any, Callable, Dict, Union, Self
from contextvars import ContextVar
from dataclasses import dataclass


_TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="N/A")
_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="N/A")


def set_trace_id(tid: str) -> None:
    """Set the Trace ID for the current coroutine/thread (micro-service: passed through from gateway)."""
    _TRACE_ID.set(tid)


def set_request_id(rid: str) -> None:
    """Set the Request ID for the current coroutine/thread (regenerated on each service entry)."""
    _REQUEST_ID.set(rid)


def get_context_ids() -> Dict[str, str]:
    """Get current context IDs, suitable for returning in HTTP response headers."""
    return {
        "X-Trace-ID": _TRACE_ID.get(),
        "X-Request-ID": _REQUEST_ID.get(),
    }


# _JsonFormatter whitelist: keep only these fields; everything else is merged as extra
_JSON_CORE_FIELDS = frozenset({
    "name", "msg", "args", "levelname", "levelno",
    "pathname", "filename", "module", "exc_info", "exc_text",
    "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName",
    "process", "asctime", "message", "taskName",
})  # fmt: skip

_ARG_REPR_MAX = 200


class _ColorFormatter(logging.Formatter):
    _COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    _RESET = "\033[0m"

    def __init__(self, fmt: str, datefmt: str) -> None:
        super().__init__(fmt, datefmt)

    def format(self, record: logging.LogRecord) -> str:
        record = copy.copy(record)
        record.trace_id = _TRACE_ID.get()
        record.request_id = _REQUEST_ID.get()
        if record.levelname in self._COLORS:
            record.levelname = f"{self._COLORS[record.levelname]}{record.levelname}{self._RESET}"
        return super().format(record)


class _PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record = copy.copy(record)
        record.trace_id = _TRACE_ID.get()
        record.request_id = _REQUEST_ID.get()
        return super().format(record)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.thread,
            "process": record.process,
            "trace_id": _TRACE_ID.get(),
            "request_id": _REQUEST_ID.get(),
        }

        if record.exc_info:
            log_obj["exception"] = traceback.format_exception(*record.exc_info)

        if record.stack_info:
            log_obj["stack_info"] = record.stack_info

        for key, val in record.__dict__.items():
            if key not in _JSON_CORE_FIELDS and not key.startswith("_"):
                log_obj[key] = val

        return json.dumps(log_obj, ensure_ascii=False, default=str)


class _LevelRangeFilter(logging.Filter):
    def __init__(self, low: int = logging.DEBUG, high: int = logging.CRITICAL) -> None:
        super().__init__()
        self.low = low
        self.high = high

    def filter(self, record: logging.LogRecord) -> bool:
        return self.low <= record.levelno <= self.high


@dataclass
class LoggerConfig:
    """Logging configuration.

    Attributes:
        name:          Logger / log file name prefix.
        level:         Global logging level; accepts string "DEBUG"/"INFO" or int.
        log_dir:       Log directory; None disables file output; str is auto-converted to Path.
        console:       Whether to output to the console.
        console_color: Whether to colorize the console (only effective when isatty()).
        json_file:     Whether to write structured JSON logs (recommended for production).
        text_file:     Whether to also write plain-text logs (legacy compatibility).
        error_file:    Whether to write a separate ERROR+ file (for quick alert triage).
        max_bytes:     Max bytes per file before rotation (default 10MB).
        backup_count:  Number of backups to retain.
        encoding:      File encoding.
        rotate_when:   Time-based rotation strategy: "midnight"/"H"/"D"/etc.; None = size-based.
        default_extra:   Default fields automatically attached to every log entry (e.g. app_version, env).
        ignored_loggers: List of logger names to force to WARNING level, suppressing their verbose output.
    """

    name: str = "app"
    level: Union[int, str] = "INFO"
    log_dir: Optional[Union[Path, str]] = None
    console: bool = True
    console_color: bool = True
    json_file: bool = True
    text_file: bool = False
    error_file: bool = False
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 10
    encoding: str = "utf-8"
    rotate_when: Optional[str] = None
    default_extra: Optional[Dict[str, Any]] = None
    ignored_loggers: Optional[list[str]] = None

    def __post_init__(self) -> None:
        if self.log_dir is not None:
            self.log_dir = Path(self.log_dir)

    @classmethod
    def from_env(cls) -> Self:
        """Load configuration from environment variables.

        Args:
            LOG_NAME:          Defaults to "app".
            LOG_LEVEL:         Defaults to "INFO".
            LOG_DIR:           Defaults to None (no file output).
            LOG_CONSOLE:       "1"=True, "0"=False, defaults to "1".
            LOG_JSON:          "1"=True, "0"=False, defaults to "1".
            LOG_TEXT:          "1"=True, "0"=False, defaults to "0".
            LOG_ERROR_FILE:    "1"=True, "0"=False, defaults to "0".
            LOG_ROTATE_WHEN:   Defaults to None (size-based rotation).
            LOG_BACKUP_COUNT:  Defaults to 10.
        """

        def _bool(key: str, default: str) -> bool:
            return os.environ.get(key, default).strip() == "1"

        return cls(
            name=os.environ.get("LOG_NAME", "app"),
            level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            log_dir=os.environ.get("LOG_DIR") or None,
            json_file=_bool("LOG_JSON", "1"),
            text_file=_bool("LOG_TEXT", "0"),
            error_file=_bool("LOG_ERROR_FILE", "0"),
            rotate_when=os.environ.get("LOG_ROTATE_WHEN") or None,
            backup_count=int(os.environ.get("LOG_BACKUP_COUNT", "10")),
            console=_bool("LOG_CONSOLE", "1"),
            ignored_loggers=None,
        )


class LoggerManager:
    """Production-grade logging manager (thread-safe singleton initialization).

    Examples:
    >>> from logger import LoggerManager, LoggerConfig, set_trace_id
        LoggerManager.configure(LoggerConfig(log_dir="logs", level="DEBUG"))
        set_trace_id("trace-abc")
        log = LoggerManager.get("service.order")
        log.info("Order created successfully", extra={"order_id": 42})
    """

    _cfg: Optional[LoggerConfig] = None
    _initialized: bool = False
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def configure(cls, cfg: Optional[LoggerConfig] = None, **kwargs: Any) -> None:
        """Initialize the logging system.

        Accepts a LoggerConfig instance or keyword arguments directly:
        >>> LoggerManager.configure(level="DEBUG", log_dir="logs")
        """
        with cls._lock:
            if cfg is None:
                cfg = LoggerConfig(**kwargs)
            cls._cfg = cfg
            cls._build(cfg)
            cls._initialized = True

        root = logging.getLogger()
        extra_info = ""
        if cfg.default_extra:
            extra_info = f" | extra={list(cfg.default_extra.keys())}"
        root.info(
            "Logging system initialized | level=%s | log_dir=%s%s",
            cfg.level,
            cfg.log_dir,
            extra_info,
        )
        cls._apply_ignored_loggers()

    @classmethod
    def get(cls, module_name: str) -> logging.LoggerAdapter[logging.Logger] | logging.Logger:
        if not cls._initialized:
            cls.configure()
        logger = logging.getLogger(module_name)
        if cls._cfg and cls._cfg.default_extra:
            return logging.LoggerAdapter(logger, cls._cfg.default_extra)
        return logger

    @classmethod
    def update_level(cls, level: Union[int, str]) -> None:
        root = logging.getLogger()
        root.setLevel(level)
        for handler in root.handlers:
            handler.setLevel(level)
        if cls._cfg is not None:
            cls._cfg.level = level
        root.info(f"Log level hot-updated to {level}")
        cls._apply_ignored_loggers()

    @classmethod
    def shutdown(cls) -> None:
        logging.shutdown()
        cls._initialized = False

    @classmethod
    def _apply_ignored_loggers(cls) -> None:
        """Force ignored loggers to WARNING so they don't flood output."""
        if cls._cfg and cls._cfg.ignored_loggers:
            for name in cls._cfg.ignored_loggers:
                logging.getLogger(name).setLevel(logging.WARNING)

    @classmethod
    def _build(cls, cfg: LoggerConfig) -> None:
        """Build dictConfig from LoggerConfig and apply it."""
        handlers: Dict[str, Any] = {}
        formatters: Dict[str, Any] = {}

        fmt_str = "[%(asctime)s] [%(levelname)s] [%(trace_id)s] [%(request_id)s] [%(name)s] %(message)s"
        datefmt = "%Y-%m-%d %H:%M:%S"

        # -- Console --
        if cfg.console:
            use_color = cfg.console_color and sys.stdout.isatty()
            if use_color:
                formatters["color"] = {
                    "()": f"{__name__}._ColorFormatter",
                    "fmt": fmt_str,
                    "datefmt": datefmt,
                }
                fmt_key = "color"
            else:
                formatters["plain"] = {
                    "()": f"{__name__}._PlainFormatter",
                    "format": fmt_str,
                    "datefmt": datefmt,
                }
                fmt_key = "plain"
            handlers["console"] = {
                "class": "logging.StreamHandler",
                "level": cfg.level,
                "formatter": fmt_key,
                "stream": "ext://sys.stdout",
            }

        # -- Log File --
        if cfg.log_dir is not None:
            log_dir = Path(cfg.log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)

            formatters["json"] = {
                "()": f"{__name__}._JsonFormatter",
                "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            }
            formatters["text"] = {
                "()": f"{__name__}._PlainFormatter",
                "format": fmt_str,
                "datefmt": datefmt,
            }

            if cfg.json_file:
                handlers["json_file"] = cls._rotating_handler(cfg, log_dir / f"{cfg.name}.json.log", "json")

            if cfg.text_file:
                handlers["text_file"] = cls._rotating_handler(cfg, log_dir / f"{cfg.name}.log", "text")

            if cfg.error_file:
                handlers["error_file"] = cls._rotating_handler(cfg, log_dir / f"{cfg.name}.error.log", "json")
                handlers["error_file"]["filters"] = ["error_only"]

        config: Dict[str, Any] = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": formatters,
            "filters": {
                "error_only": {
                    "()": f"{__name__}._LevelRangeFilter",
                    "low": logging.ERROR,
                    "high": logging.CRITICAL,
                }
            },
            "handlers": handlers,
            "root": {
                "level": cfg.level,
                "handlers": list(handlers.keys()),
            },
        }
        logging.config.dictConfig(config)

    @staticmethod
    def _rotating_handler(cfg: LoggerConfig, path: Path, formatter: str) -> Dict[str, Any]:
        if cfg.rotate_when:
            return {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": cfg.level,
                "formatter": formatter,
                "filename": str(path),
                "when": cfg.rotate_when,
                "backupCount": cfg.backup_count,
                "encoding": cfg.encoding,
            }
        return {
            "class": "logging.handlers.RotatingFileHandler",
            "level": cfg.level,
            "formatter": formatter,
            "filename": str(path),
            "maxBytes": cfg.max_bytes,
            "backupCount": cfg.backup_count,
            "encoding": cfg.encoding,
        }


def get_logger(module_name: str) -> logging.LoggerAdapter[logging.Logger] | logging.Logger:
    """Module-level convenience getter for a logger.

    Examples:
    >>> logger = get_logger(__name__)
    """
    return LoggerManager.get(module_name)


def log_exceptions(
    logger: Optional[logging.Logger] = None,
    level: int = logging.ERROR,
    reraise: bool = True,
    default_return: Any = None,
    max_arg_len: int = _ARG_REPR_MAX,
) -> Callable:
    """Decorator: automatically catch function exceptions and log the full stack trace.

    Parameters:
        logger:         Specific logger; None uses the function's module logger.
        level:          Logging level, defaults to ERROR.
        reraise:        Whether to re-raise the exception, defaults to True.
        default_return: Return value when reraise=False.
        max_arg_len:    Argument repr truncation threshold (bytes), to prevent large objects from blowing up logs.

    Examples:
    >>> @log_exceptions(reraise=False, default_return=[])
        def fetch_data(user_id: int) -> list: ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            _logger = logger or logging.getLogger(func.__module__)
            try:
                return func(*args, **kwargs)
            except Exception as exc:

                def _safe_repr(v: Any) -> str:
                    r = repr(v)
                    return r if len(r) <= max_arg_len else r[:max_arg_len] + "...<truncated>"

                _logger.log(
                    level,
                    "Exception in %s.%s: %s",
                    func.__module__,
                    func.__qualname__,
                    exc,
                    exc_info=True,
                    extra={
                        "function_args": [_safe_repr(a) for a in args],
                        "function_kwargs": {k: _safe_repr(v) for k, v in kwargs.items()},
                    },
                )
                if reraise:
                    raise
                return default_return

        return wrapper

    return decorator


if __name__ == "__main__":
    import uuid

    LoggerManager.configure(
        name="demo",
        log_dir=Path("logs"),
        level="DEBUG",
        console_color=True,
        json_file=True,
        text_file=True,
        error_file=True,
        max_bytes=10 * 1024 * 1024,
        default_extra={"app_version": "2.0.0", "env": "dev"},
        ignored_loggers=["matplotlib"],
    )

    set_trace_id(f"trace-{uuid.uuid4().hex[:8]}")
    set_request_id(f"req-{uuid.uuid4().hex[:8]}")

    log = LoggerManager.get("demo.main")

    log.debug("DEBUG message", extra={"detail": "debug info"})
    log.info("INFO message")
    log.warning("WARNING message")
    log.error("ERROR message")
    log.critical("CRITICAL message")

    @log_exceptions(level=logging.ERROR, reraise=False, default_return="fallback")
    def risky(data: dict) -> str:
        raise ValueError(f"Simulated exception, data keys={list(data.keys())}")

    result = risky({"user_id": 1, "payload": "x" * 300})
    log.info("risky() returned: %s", result)

    LoggerManager.update_level(logging.WARNING)
    log.info("This message will not be printed (level raised)")
    log.warning("This message is visible")

    ids = get_context_ids()
    log.warning("Response headers should include: %s", ids)

    LoggerManager.shutdown()
