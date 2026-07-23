from pathlib import Path
import tempfile
import unittest

from fast_p.screenshot import login_required, verified_capture_exists, _capture_receipt


class ScreenshotTest(unittest.TestCase):
    def test_detects_full_login_page_without_treating_header_login_as_blocked(self):
        self.assertTrue(login_required(
            "https://item.hqchip.com/2500420369.html",
            "微信登录 验证码登录 密码登录 注册新账号",
        ))
        self.assertTrue(login_required("https://passport.example.test/login", ""))
        self.assertFalse(login_required(
            "https://item.hqchip.com/2500420369.html",
            "登录 注册 商品型号 BAV99 库存 1000 阶梯价格",
        ))

    def test_only_verified_current_screenshots_are_resumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            filename = "SKU-1.png"
            url = "https://example.test/item/1"
            (output / filename).write_bytes(b"old screenshot")
            self.assertFalse(verified_capture_exists(output, filename, url))
            receipt = _capture_receipt(output, filename, url)
            receipt.parent.mkdir(parents=True)
            receipt.write_text("2", encoding="utf-8")
            self.assertTrue(verified_capture_exists(output, filename, url))
            self.assertFalse(verified_capture_exists(output, filename, f"{url}?changed=1"))


if __name__ == "__main__":
    unittest.main()
