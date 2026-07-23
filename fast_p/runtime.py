import os
from pathlib import Path
import shutil
import sys


def resource_root():
    """Return the PyInstaller data root, or the source tree while developing."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]


def bundled_runtime_root():
    return resource_root() / "runtime"


def _first_file(paths):
    for path in paths:
        if path and Path(path).is_file():
            return str(Path(path))
    return ""


def bundled_node():
    root = bundled_runtime_root() / "node"
    return _first_file((root / "node.exe", root / "node"))


def bundled_fast_cli():
    root = bundled_runtime_root() / "fast-cli"
    return str(root) if (root / "bin" / "fast-scrape-worker.js").is_file() else ""


def bundled_chromium():
    root = bundled_runtime_root() / "ms-playwright"
    candidates = [
        *root.glob("chromium-*/chrome-win64/chrome.exe"),
        *root.glob("chromium-*/chrome-win/chrome.exe"),
        *root.glob("chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"),
        *root.glob("chromium-*/chrome-linux/chrome"),
    ]
    return _first_file(sorted(candidates, reverse=True))


def source_fast_cli():
    sibling = Path(__file__).resolve().parents[2] / "fast-cli"
    return str(sibling) if (sibling / "bin" / "fast-scrape-worker.js").is_file() else ""


def system_chrome():
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
        found = _first_file(candidates)
        return found or str(candidates[0])
    if sys.platform == "darwin":
        return _first_file((
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ))
    return shutil.which("google-chrome") or shutil.which("google-chrome-stable") or ""


def default_runtime_paths():
    return {
        "node": os.environ.get("FAST_NODE_BIN") or bundled_node() or shutil.which("node") or "",
        "fast_cli": os.environ.get("FAST_CLI_ROOT") or bundled_fast_cli() or source_fast_cli(),
        "chrome": os.environ.get("CHROME_BIN") or bundled_chromium() or system_chrome(),
    }
