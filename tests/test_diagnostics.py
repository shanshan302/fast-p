import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from fast_p.data import Store
from fast_p.diagnostics import export_diagnostics, record_event
from fast_p.models import ItemResult, Settings


class DiagnosticsTest(unittest.TestCase):
    def test_exports_summary_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / "app"
            log_dir = app_dir / "logs"
            log_dir.mkdir(parents=True)
            log_dir.joinpath("fast-p.log").write_text(
                "token=TOPSECRET https://example.test/item?session=TOPSECRET\n", encoding="utf-8",
            )
            output = root / "output"
            output.mkdir()
            store = Store(output / "job.sqlite3", "test")
            store.save(ItemResult(8, "SKU", "ABC", "OK", "matched"))
            store.close()
            record_event(app_dir, {
                "type": "failed", "phase": "collect", "model": "ABC", "ignored": "cookie=bad",
            })

            runtime = root / "fast-cli"
            runtime.mkdir()
            runtime.joinpath("package.json").write_text('{"version":"0.1.7"}', encoding="utf-8")
            settings = Settings("", str(runtime), "", str(root / "profile"))
            target = export_diagnostics(
                root / "diagnostic.zip", app_dir, settings, output, "password=TOPSECRET",
            )

            with zipfile.ZipFile(target) as archive:
                self.assertEqual(
                    {"environment.json", "task-summary.json", "logs/fast-p.log"},
                    set(archive.namelist()),
                )
                combined = "\n".join(
                    archive.read(name).decode("utf-8") for name in archive.namelist()
                )
                summary = json.loads(archive.read("task-summary.json"))
            self.assertNotIn("TOPSECRET", combined)
            self.assertNotIn("cookie=bad", combined)
            self.assertEqual(1, summary["total"])
            self.assertEqual({"OK": 1}, summary["statusCounts"])
            self.assertEqual("ABC", summary["lastEvent"]["model"])


if __name__ == "__main__":
    unittest.main()
