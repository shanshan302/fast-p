import os
from pathlib import Path
import re
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont
try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = TimeoutError
    sync_playwright = None

from .models import CaptureRequest


WIDTH, HEIGHT = 1366, 1100


def safe_name(value: str):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned or "screenshot"


class Screenshotter:
    def __init__(self, chrome: str, profile: str):
        self.chrome = chrome
        self.profile = profile
        self.playwright = None
        self.context = None

    def __enter__(self):
        if sync_playwright is None:
            raise RuntimeError("缺少 playwright，请先安装 requirements.txt")
        self.playwright = sync_playwright().start()
        headless = os.environ.get("FAST_P_HEADLESS", "1") != "0"
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(Path(self.profile).expanduser()),
            executable_path=str(Path(self.chrome).expanduser()),
            headless=headless,
            viewport={"width": WIDTH, "height": HEIGHT},
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-session-crashed-bubble",
                *([] if headless else ["--window-position=-4000,-4000", f"--window-size={WIDTH},{HEIGHT}"]),
            ],
        )
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()

    def capture(self, request: CaptureRequest, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{safe_name(request.filename)}.png"
        target = output_dir / filename
        raw = Path(tempfile.gettempdir()) / f"fast-p-{safe_name(request.item_id)}.png"
        page = self.context.new_page()
        try:
            try:
                page.goto(request.url, wait_until="networkidle", timeout=60_000)
            except PlaywrightTimeoutError:
                if not page.url or page.url == "about:blank":
                    raise
            time.sleep(3)
            page.evaluate("""() => {
                for (const element of [...document.querySelectorAll('*')]) {
                    try {
                        const style = getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        if (style.position === 'fixed' && rect.height <= 220 && rect.width > innerWidth * .6) {
                            element.style.display = 'none';
                        }
                    } catch (_) {}
                }
                document.querySelectorAll('.modal-mask,.mask,.popup,.dialog-mask,[class*="modal"],[class*="Modal"]')
                    .forEach(element => element.style.display = 'none');
                scrollTo(0, 0);
            }""")
            bottom = page.evaluate("""() => {
                const keys = ['型号','品牌','厂牌','库存','数量','价格','阶梯','单价','MOQ','SPQ','最小','起订'];
                let result = 850;
                for (const element of document.querySelectorAll('*')) {
                    const text = (element.innerText || '').trim();
                    if (!text || text.length > 400 || !keys.some(key => text.includes(key))) continue;
                    const rect = element.getBoundingClientRect();
                    if (rect.top + scrollY <= 1100) result = Math.max(result, rect.bottom + scrollY + 30);
                }
                return Math.max(650, Math.min(result, 1300));
            }""")
            page.screenshot(
                path=str(raw),
                clip={"x": 0, "y": 0, "width": WIDTH, "height": int(bottom)},
            )
            self._add_url_bar(raw, target, request.url)
            return filename
        finally:
            page.close()

    @staticmethod
    def _add_url_bar(raw: Path, target: Path, url: str):
        page = Image.open(raw).convert("RGB")
        bar_height = 78
        image = Image.new("RGB", (page.width, page.height + bar_height), "#e8eaed")
        image.paste(page, (0, bar_height))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((72, 17, page.width - 24, 60), radius=20, fill="white", outline="#c5c8cc")
        display_url = url if len(url) <= 170 else f"{url[:167]}..."
        draw.text((92, 31), display_url, fill="#202124", font=ImageFont.load_default())
        image.save(target, quality=95)
