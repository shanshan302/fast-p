from pathlib import Path

try:
    import psutil
except ImportError:  # 安装包包含 psutil；源码最小环境仍可运行核心测试。
    psutil = None

from .collection import CollectorWorker
from .data import Store, export_results, fingerprint, load_capture_results, load_rows, make_export
from .models import CaptureRequest, CollectionRequest, Settings
from .rules import brand_variants, find_match


class Cancelled(Exception):
    pass


MODES = {"collect", "screenshot", "all"}


def cleanup_profile_chrome(profile: str):
    if psutil is None:
        return
    key = str(Path(profile).expanduser()).lower()
    targets = []
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (process.info["name"] or "").lower()
            command = " ".join(process.info["cmdline"] or []).lower()
            if "chrome" in name and key and key in command:
                process.terminate()
                targets.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    _, alive = psutil.wait_procs(targets, timeout=5)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass


class JobRunner:
    def __init__(self, settings: Settings, progress, cancelled):
        self.settings = settings
        self.progress = progress
        self.cancelled = cancelled

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise Cancelled("任务已取消，进度已保存")

    def collect_rows(self, rows, store: Store, platforms: list[str]):
        total = len(rows)
        with CollectorWorker(self.settings) as worker:
            for index, row in enumerate(rows, start=1):
                self.check_cancelled()
                existing = store.get(row.row_number)
                if existing and existing.status != "ERROR":
                    result = existing
                else:
                    hints = brand_variants(row.brand)

                    def collect(_model, platform):
                        return worker.collect(CollectionRequest(
                            model=row.model,
                            platform=platform,
                            brand=row.brand,
                            brand_variants=hints,
                            min_buy_qty=row.moq,
                        ))

                    result = find_match(row, platforms, collect, self.progress)
                    store.save(result)
                self.progress({
                    "phase": "collect", "current": index, "total": total,
                    "model": row.model, "status": result.status,
                })

    def capture_rows(self, store: Store, output: Path):
        matched = [result for result in store.all() if result.status == "OK"]
        if not matched:
            return
        cleanup_profile_chrome(self.settings.chrome_profile)
        from .screenshot import Screenshotter
        with Screenshotter(self.settings.chrome, self.settings.chrome_profile) as screenshotter:
            for index, result in enumerate(matched, start=1):
                self.check_cancelled()
                if result.screenshot and (output / "screenshots" / result.screenshot).exists():
                    pass
                else:
                    try:
                        request = CaptureRequest(
                            item_id=result.sku or result.model,
                            url=result.url,
                            filename=result.sku or result.model,
                        )
                        result.screenshot = screenshotter.capture(request, output / "screenshots")
                        result.screenshot_error = ""
                    except Exception as exc:
                        result.screenshot_error = str(exc)
                    store.save(result)
                self.progress({
                    "phase": "screenshot", "current": index, "total": len(matched),
                    "model": result.model, "status": "ERROR" if result.screenshot_error else "OK",
                })

    def run(self, excel: Path, output: Path, platforms: list[str], mode="all"):
        if mode not in MODES:
            raise ValueError(f"未知任务模式：{mode}")
        output.mkdir(parents=True, exist_ok=True)
        if mode == "screenshot":
            imported = load_capture_results(excel)
            store = Store(output / "job.sqlite3", fingerprint(excel, ["screenshot"]))
            for result in imported:
                existing = store.get(result.row_number)
                if not existing or existing.url != result.url:
                    store.save(result)
        else:
            rows = load_rows(excel)
            store = Store(output / "job.sqlite3", fingerprint(excel, platforms))
        try:
            if mode != "screenshot":
                self.collect_rows(rows, store, platforms)
            if mode != "collect":
                self.capture_rows(store, output)
            results = store.all()
            self.progress({"phase": "export", "current": 0, "total": 1})
            workbook = export_results(excel, output, results)
            archive = make_export(output, workbook, results)
            self.progress({"phase": "done", "current": 1, "total": 1, "archive": str(archive)})
            return workbook, archive
        finally:
            store.close()
