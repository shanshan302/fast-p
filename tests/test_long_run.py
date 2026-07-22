from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fast_p.collection import CollectionError
from fast_p.data import Store
from fast_p.models import InputRow, Settings
from fast_p.workflow import Cancelled, JobRunner


class LongRunCollector:
    instances = []
    failed_once = set()

    def __init__(self, settings):
        self.calls = 0
        self.closed = False
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def collect(self, request):
        self.calls += 1
        number = int(request.model.removeprefix("PN"))
        if number % 50 == 0 and request.model not in self.failed_once:
            self.failed_once.add(request.model)
            raise CollectionError("模拟临时超时")
        return {"result": {"platforms": [{
            "platformId": request.platform,
            "success": True,
            "noData": False,
            "data": [{
                "part_number": request.model,
                "manufacturer": "ACME",
                "product_url": f"https://example.test/{request.model}",
                "price_tiers": [{"quantity": 100, "unit_price": 2.0}],
            }],
        }]}}


class LongRunTest(unittest.TestCase):
    def test_1000_rows_cancel_resume_and_retry_transient_failures(self):
        LongRunCollector.instances = []
        LongRunCollector.failed_once = set()
        rows = [InputRow(index + 2, f"SKU-{index}", f"PN{index:04}", "ACME", 1.0, 100)
                for index in range(1, 1001)]
        cancelled = threading.Event()

        def progress(event):
            if event.get("phase") == "collect" and event.get("current") == 300:
                cancelled.set()

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "job.sqlite3", "long-run")
            settings = Settings("", "", "", "")
            with patch("fast_p.workflow.CollectorWorker", LongRunCollector):
                with self.assertRaises(Cancelled):
                    JobRunner(settings, progress, cancelled).collect_rows(rows, store, ["hqchip"])
                self.assertEqual(300, len(store.all()))
                cancelled.clear()
                JobRunner(settings, lambda event: None, cancelled).collect_rows(
                    rows, store, ["hqchip"],
                )
                JobRunner(settings, lambda event: None, cancelled).collect_rows(
                    rows, store, ["hqchip"],
                )

            results = store.all()
            store.close()

        self.assertEqual(1000, len(results))
        self.assertTrue(all(result.status == "OK" for result in results))
        self.assertEqual(3, len(LongRunCollector.instances))
        self.assertEqual(300, LongRunCollector.instances[0].calls)
        self.assertEqual(706, LongRunCollector.instances[1].calls)
        self.assertEqual(14, LongRunCollector.instances[2].calls)
        self.assertTrue(all(worker.closed for worker in LongRunCollector.instances))


if __name__ == "__main__":
    unittest.main()
