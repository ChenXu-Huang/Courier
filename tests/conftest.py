from src._meta import ROOT_DIR, VERSION
from src.logger import LoggerManager

LoggerManager.configure(
    name="tests",
    log_dir=ROOT_DIR / "logs",
    level="DEBUG",
    console=False,
    json_file=False,
    text_file=True,
    error_file=True,
    max_bytes=10 * 1024 * 1024,
    backup_count=5,
    default_extra={"app_version": VERSION, "env": "dev"},
)
