from pathlib import Path
import tempfile
import unittest
import zipfile

import openpyxl

from fast_p.engine import Store, export_results, fingerprint, load_rows, make_export
from fast_p.models import ItemResult


class JobStateTest(unittest.TestCase):
    def make_excel(self, root: Path):
        path = root / "input.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["敦煌SKU", "型号", "标准厂牌", "供货价", "最小起订量"])
        sheet.append(["SKU-1", "ABC123", "ACME", 1.0, 100])
        workbook.save(path)
        workbook.close()
        return path

    def test_excel_load_store_resume_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            excel = self.make_excel(root)
            rows = load_rows(excel)
            self.assertEqual(1, len(rows))
            self.assertEqual("ABC123", rows[0].model)

            store = Store(root / "job.sqlite3", fingerprint(excel, ["hqchip"]))
            result = ItemResult(
                2, "SKU-1", "ABC123", "OK", "matched",
                platform="hqchip", platform_name="华秋", url="https://example.test",
                matched_model="ABC123-A", matched_brand="ACME", quantity=100, price=2.0,
            )
            store.save(result)
            store.close()

            reopened = Store(root / "job.sqlite3", fingerprint(excel, ["hqchip"]))
            self.assertEqual("OK", reopened.get(2).status)
            results = reopened.all()
            reopened.close()

            output = export_results(excel, root, results)
            workbook = openpyxl.load_workbook(output, read_only=True)
            headers = [cell.value for cell in workbook.active[1]]
            self.assertIn("匹配平台", headers)
            self.assertIn("截图文件名", headers)
            workbook.close()

            screenshot_dir = root / "screenshots"
            screenshot_dir.mkdir()
            (screenshot_dir / "good.png").write_bytes(b"good")
            (screenshot_dir / "login-page.png").write_bytes(b"invalid")
            result.screenshot = "good.png"
            failed = ItemResult(
                3, "SKU-2", "XYZ789", "OK", "matched",
                url="https://example.test/login", screenshot="login-page.png",
                screenshot_error="页面要求登录",
            )
            archive = make_export(root, output, [result, failed])
            with zipfile.ZipFile(archive) as zipped:
                names = zipped.namelist()
            self.assertIn("screenshots/good.png", names)
            self.assertNotIn("screenshots/login-page.png", names)


if __name__ == "__main__":
    unittest.main()
