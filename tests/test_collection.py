import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from fast_p.collection import CollectorWorker, list_platforms
from fast_p.models import CollectionRequest, PLATFORMS, Settings


FAKE_WORKER = r'''
import json
import sys

print(json.dumps({"apiVersion": 1, "type": "ready"}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("action") == "shutdown":
        print(json.dumps({"apiVersion": 1, "type": "stopped", "id": request["id"]}), flush=True)
        break
    platform = request["platform"]
    result = {
        "platforms": [{
            "platformId": platform,
            "success": True,
            "noData": False,
            "data": [{"part_number": request["partNumber"]}],
        }]
    }
    print(json.dumps({
        "apiVersion": 1,
        "type": "result",
        "id": request["id"],
        "ok": True,
        "result": result,
    }), flush=True)
'''

SLOW_ONCE_WORKER = r'''
import json
from pathlib import Path
import sys
import time

profile = Path(sys.argv[sys.argv.index("--profile-dir") + 1])
marker = profile / "slow-once"
print(json.dumps({"apiVersion": 1, "type": "ready"}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("action") == "shutdown":
        break
    if not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1")
        time.sleep(.2)
    result = {"platforms": [{
        "platformId": request["platform"], "success": True, "noData": True, "data": []
    }]}
    print(json.dumps({"type": "result", "id": request["id"], "result": result}), flush=True)
'''

CRASH_ONCE_WORKER = r'''
import json
from pathlib import Path
import sys

profile = Path(sys.argv[sys.argv.index("--profile-dir") + 1])
marker = profile / "crash-once"
print(json.dumps({"apiVersion": 1, "type": "ready"}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("action") == "shutdown":
        break
    if not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1")
        print("simulated crash", file=sys.stderr, flush=True)
        raise SystemExit(7)
    result = {"platforms": [{
        "platformId": request["platform"], "success": True, "noData": True, "data": []
    }]}
    print(json.dumps({"type": "result", "id": request["id"], "result": result}), flush=True)
'''

FAKE_PLATFORM_CLI = r'''
import json
print(json.dumps({"ok": True, "platforms": [
    {"id": "digikey", "name": "Digi-Key"},
    {"id": "hqchip", "name": "华秋商城"},
    {"id": "new-platform", "name": "新平台"},
    {"id": "ichunt", "name": "猎芯网"},
]}))
'''


class CollectorWorkerTest(unittest.TestCase):
    def test_reads_platforms_from_fast_cli_and_preserves_business_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "platforms.py"
            script.write_text(FAKE_PLATFORM_CLI, encoding="utf-8")
            platforms = list_platforms(sys.executable, str(script))
        self.assertEqual(
            ["hqchip", "ichunt", "digikey", "new-platform"],
            [platform for platform, _ in platforms],
        )
        self.assertEqual(12, len(PLATFORMS))

    def test_reuses_one_worker_and_returns_fast_cli_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_script = root / "fake_worker.py"
            worker_script.write_text(FAKE_WORKER, encoding="utf-8")
            settings = Settings(
                node=sys.executable,
                fast_cli=str(worker_script),
                chrome=sys.executable,
                chrome_profile=str(root / "profile"),
            )
            with CollectorWorker(settings, timeout=5) as worker:
                first_process = worker.process.pid
                payload = worker.collect(CollectionRequest("ABC123", "hqchip"))
                second = worker.collect(CollectionRequest("XYZ789", "ichunt"))
                self.assertEqual(first_process, worker.process.pid)

            self.assertEqual("ABC123", payload["result"]["platforms"][0]["data"][0]["part_number"])
            self.assertEqual("ichunt", second["result"]["platforms"][0]["platformId"])

    def test_one_worker_handles_1000_serial_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_script = root / "fake_worker.py"
            worker_script.write_text(FAKE_WORKER, encoding="utf-8")
            settings = Settings(
                node=sys.executable,
                fast_cli=str(worker_script),
                chrome=sys.executable,
                chrome_profile=str(root / "profile"),
            )
            with CollectorWorker(settings, timeout=2) as worker:
                process_id = worker.process.pid
                for index in range(1000):
                    worker.collect(CollectionRequest(f"PN{index:04}", "hqchip"))
                    self.assertEqual(process_id, worker.process.pid)
            self.assertIsNone(worker.process)

    def test_recovers_after_worker_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_script = root / "slow_worker.py"
            worker_script.write_text(SLOW_ONCE_WORKER, encoding="utf-8")
            settings = Settings(
                node=sys.executable,
                fast_cli=str(worker_script),
                chrome=sys.executable,
                chrome_profile=str(root / "profile"),
            )
            started = time.monotonic()
            with CollectorWorker(settings, timeout=.05) as worker:
                payload = worker.collect(CollectionRequest("ABC123", "hqchip"))
            self.assertLess(time.monotonic() - started, 2)
            self.assertTrue(payload["result"]["platforms"][0]["noData"])

    def test_recovers_after_worker_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_script = root / "crash_worker.py"
            worker_script.write_text(CRASH_ONCE_WORKER, encoding="utf-8")
            settings = Settings(
                node=sys.executable,
                fast_cli=str(worker_script),
                chrome=sys.executable,
                chrome_profile=str(root / "profile"),
            )
            with CollectorWorker(settings, timeout=1) as worker:
                payload = worker.collect(CollectionRequest("ABC123", "hqchip"))
            self.assertTrue(payload["result"]["platforms"][0]["noData"])


if __name__ == "__main__":
    unittest.main()
