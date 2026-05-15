from src._meta import VERSION, LOG_DIR
from src.logger import LoggerManager

LoggerManager.configure(
    name="tests",
    log_dir=LOG_DIR,
    level="DEBUG",
    console=False,
    json_file=False,
    text_file=True,
    error_file=True,
    max_bytes=10 * 1024 * 1024,
    backup_count=5,
    default_extra={"app_version": VERSION, "env": "dev"},
)
