import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid

from .models import CollectionRequest, PREFERRED_PLATFORM_IDS, Settings


WORKER_API_VERSION = 1


class CollectionError(RuntimeError):
    pass


def list_platforms(node: str, fast_cli: str, timeout=15):
    """通过 fast-cli 公共命令读取启用平台；新版运行包可直接扩展界面。"""
    if not node or not Path(node).expanduser().is_file():
        raise CollectionError("找不到 Node 可执行文件")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [str(Path(node).expanduser()), str(cli_entry(fast_cli)), "platforms"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectionError(f"无法读取 fast-cli 平台列表：{exc}") from exc
    if result.returncode:
        raise CollectionError(result.stderr.strip() or f"平台列表命令退出码：{result.returncode}")
    try:
        payload = json.loads(result.stdout)
        raw = payload["platforms"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CollectionError("fast-cli 返回的平台列表无效") from exc
    if not isinstance(raw, list):
        raise CollectionError("fast-cli 返回的平台列表无效")

    platforms = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        platform_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        if platform_id and name and platform_id not in seen:
            platforms.append((platform_id, name))
            seen.add(platform_id)
    if not platforms:
        raise CollectionError("fast-cli 没有返回可用平台")
    preferred = {platform_id: index for index, platform_id in enumerate(PREFERRED_PLATFORM_IDS)}
    discovered = {platform_id: index for index, (platform_id, _) in enumerate(platforms)}
    return tuple(sorted(
        platforms,
        key=lambda item: (
            0, preferred[item[0]],
        ) if item[0] in preferred else (
            1, discovered[item[0]],
        ),
    ))


def worker_entry(fast_cli: str) -> Path:
    path = Path(fast_cli).expanduser().resolve()
    if path.is_dir():
        path = path / "bin" / "fast-scrape-worker.js"
    elif path.name == "fast-scrape.js":
        path = path.with_name("fast-scrape-worker.js")
    if not path.is_file():
        raise CollectionError(f"找不到 fast-cli Worker：{path}")
    return path


def cli_entry(fast_cli: str) -> Path:
    path = Path(fast_cli).expanduser().resolve()
    if path.is_dir():
        path = path / "bin" / "fast-scrape.js"
    elif path.name == "fast-scrape-worker.js":
        path = path.with_name("fast-scrape.js")
    if not path.is_file():
        raise CollectionError(f"找不到 fast-cli 入口：{path}")
    return path


def open_platform_login(settings: Settings):
    environment = os.environ.copy()
    environment["FAST_SCRAPE_CHROME_PATH"] = settings.chrome
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [
                settings.node,
                str(cli_entry(settings.fast_cli)),
                "login", "--all-platforms",
                "--profile-dir", settings.chrome_profile,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=environment,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectionError(f"无法打开平台登录页：{exc}") from exc
    if result.returncode:
        raise CollectionError(result.stderr.strip() or f"登录命令退出码：{result.returncode}")
    return result.stdout.strip()


class CollectorWorker:
    """一个任务只启动一个 Node Worker；所有平台请求通过 JSONL 串行发送。"""

    def __init__(self, settings: Settings, timeout: int = 180, recycle_after: int = 100):
        self.settings = settings
        self.timeout = timeout
        self.recycle_after = recycle_after
        self.process = None
        self.events = queue.Queue()
        self.stderr_lines = []
        self.stdout_thread = None
        self.stderr_thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def _command(self):
        return [
            self.settings.node,
            str(worker_entry(self.settings.fast_cli)),
            "--profile-dir", self.settings.chrome_profile,
            "--recycle-after", str(self.recycle_after),
        ]

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.close()
        self.events = queue.Queue()
        self.stderr_lines = []
        environment = os.environ.copy()
        environment["FAST_SCRAPE_CHROME_PATH"] = self.settings.chrome
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=environment,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise CollectionError(f"无法启动采集 Worker：{exc}") from exc
        self.stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()
        ready = self._wait_for(lambda event: event.get("type") == "ready", 30)
        if ready.get("apiVersion") != WORKER_API_VERSION:
            self.close()
            raise CollectionError(
                f"fast-cli 协议版本不兼容：{ready.get('apiVersion')}，需要 {WORKER_API_VERSION}"
            )

    def _read_stdout(self):
        stream = self.process.stdout
        try:
            for line in stream:
                try:
                    self.events.put(json.loads(line))
                except json.JSONDecodeError:
                    self.events.put({"type": "protocol_error", "error": f"无效 JSON：{line[:200]}"})
        finally:
            self.events.put({"type": "eof"})

    def _read_stderr(self):
        for line in self.process.stderr:
            self.stderr_lines.append(line.rstrip())
            del self.stderr_lines[:-50]

    def _wait_for(self, predicate, timeout):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CollectionError(f"采集 Worker 响应超时；{self._diagnostic()}")
            try:
                event = self.events.get(timeout=remaining)
            except queue.Empty as exc:
                raise CollectionError(f"采集 Worker 响应超时；{self._diagnostic()}") from exc
            if event.get("type") == "eof":
                raise CollectionError(f"采集 Worker 已退出；{self._diagnostic()}")
            if event.get("type") == "protocol_error":
                raise CollectionError(event["error"])
            if predicate(event):
                return event

    def _diagnostic(self):
        if self.process:
            code = self.process.poll()
            suffix = f"退出码={code}" if code is not None else "进程仍在运行"
        else:
            suffix = "进程未启动"
        if self.stderr_lines:
            suffix += f"，stderr={self.stderr_lines[-1]}"
        return suffix

    def collect(self, request: CollectionRequest):
        last_error = None
        for attempt in range(2):
            request_id = uuid.uuid4().hex
            try:
                self.start()
                payload = {
                    "apiVersion": WORKER_API_VERSION,
                    "id": request_id,
                    "action": "collect",
                    "partNumber": request.model,
                    "platform": request.platform,
                    "brand": request.brand,
                    "brandVariants": list(request.brand_variants),
                    "minBuyQty": request.min_buy_qty,
                    "maxResults": request.max_results,
                }
                self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
                event = self._wait_for(
                    lambda item: item.get("id") == request_id and item.get("type") in {"result", "error"},
                    self.timeout,
                )
                if event.get("type") == "error":
                    raise CollectionError(event.get("error") or "采集 Worker 返回未知错误")
                return {"result": event["result"]}
            except (BrokenPipeError, OSError, CollectionError) as exc:
                last_error = exc
                self.close()
                if attempt == 0:
                    continue
        raise CollectionError(str(last_error or "采集 Worker 调用失败"))

    def close(self):
        process = self.process
        self.process = None
        if not process:
            return
        if process.poll() is None:
            try:
                request_id = uuid.uuid4().hex
                process.stdin.write(json.dumps({
                    "apiVersion": WORKER_API_VERSION,
                    "id": request_id,
                    "action": "shutdown",
                }) + "\n")
                process.stdin.flush()
                process.wait(timeout=10)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except (AttributeError, OSError):
                pass
