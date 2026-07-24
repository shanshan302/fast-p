from contextlib import closing
import json
import logging
from logging.handlers import RotatingFileHandler
import platform
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import zipfile

from . import __version__


LOG_NAME = "fast-p.log"
SAFE_EVENT_FIELDS = {
    "type", "mode", "phase", "current", "total", "model", "platform", "status", "message",
}
SECRET_PATTERN = re.compile(
    r"(?i)(cookie|authorization|token|password|passwd|secret)(\s*[=:]\s*)([^\s,;]+)"
)
URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def redact(value):
    text = str(value or "")
    text = SECRET_PATTERN.sub(r"\1\2<redacted>", text)

    def strip_query(match):
        url = match.group(0)
        return url.split("?", 1)[0] + ("?<redacted>" if "?" in url else "")

    return URL_PATTERN.sub(strip_query, text)


def configure_logging(app_dir: Path):
    log_dir = Path(app_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = (log_dir / LOG_NAME).resolve()
    logger = logging.getLogger("fast_p")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename).resolve() == log_path
        for handler in logger.handlers
    ):
        handler = RotatingFileHandler(
            log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def safe_event(event):
    return {
        key: redact(value) if isinstance(value, str) else value
        for key, value in event.items()
        if key in SAFE_EVENT_FIELDS
    }


def record_event(app_dir: Path, event):
    app_dir = Path(app_dir)
    app_dir.mkdir(parents=True, exist_ok=True)
    target = app_dir / "last-event.json"
    temporary = app_dir / ".last-event.tmp"
    temporary.write_text(
        json.dumps(safe_event(event), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    temporary.replace(target)


def _version(command):
    if not command or not Path(command).expanduser().is_file():
        return "不可用"
    try:
        result = subprocess.run(
            [str(Path(command).expanduser()), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return redact((result.stdout or result.stderr).strip()) or f"退出码 {result.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"无法读取：{type(exc).__name__}"


def _fast_cli_info(path):
    root = Path(path).expanduser()
    if root.is_file():
        root = root.parent.parent
    package = root / "package.json"
    try:
        value = json.loads(package.read_text(encoding="utf-8"))
        return {"path": str(root), "version": value.get("version", "未知")}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {"path": str(root), "version": "未知"}


def _task_summary(output):
    summary = {"output": str(output or ""), "total": 0, "statusCounts": {}, "lastRow": None}
    database = Path(output) / "job.sqlite3" if output else None
    if not database or not database.is_file():
        return summary
    try:
        with closing(sqlite3.connect(database)) as connection:
            rows = connection.execute("SELECT row_number, result_json FROM items").fetchall()
        for row_number, raw in rows:
            status = json.loads(raw).get("status", "UNKNOWN")
            summary["statusCounts"][status] = summary["statusCounts"].get(status, 0) + 1
            summary["lastRow"] = max(summary["lastRow"] or row_number, row_number)
        summary["total"] = len(rows)
    except (OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        summary["readError"] = type(exc).__name__
    return summary


def export_diagnostics(destination: Path, app_dir: Path, settings, output=None, last_error=""):
    destination = Path(destination)
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    app_dir = Path(app_dir)
    environment = {
        "appVersion": __version__,
        "pythonVersion": platform.python_version(),
        "pythonExecutable": sys.executable,
        "os": platform.platform(),
        "machine": platform.machine(),
        "nodeVersion": _version(settings.node),
        "chromeVersion": _version(settings.chrome),
        "fastCli": _fast_cli_info(settings.fast_cli),
    }
    summary = _task_summary(output)
    try:
        summary["lastEvent"] = json.loads((app_dir / "last-event.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        summary["lastEvent"] = {}
    if last_error:
        summary["lastError"] = redact(last_error)

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("environment.json", json.dumps(environment, ensure_ascii=False, indent=2))
        archive.writestr("task-summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        for log in sorted((app_dir / "logs").glob(f"{LOG_NAME}*")):
            try:
                archive.writestr(f"logs/{log.name}", redact(log.read_text(encoding="utf-8")))
            except OSError:
                continue
    return destination
