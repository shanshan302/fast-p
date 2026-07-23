from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from fast_p import __version__
from fast_p import runtime


class RuntimePathsTest(unittest.TestCase):
    def test_package_version_matches_build_metadata(self):
        project = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["version"], __version__)

    def test_installed_runtime_is_selected_without_environment_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node = root / "runtime" / "node" / "node.exe"
            worker = root / "runtime" / "fast-cli" / "bin" / "fast-scrape-worker.js"
            chrome = (
                root / "runtime" / "ms-playwright" / "chromium-123"
                / "chrome-win64" / "chrome.exe"
            )
            for path in (node, worker, chrome):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"runtime")

            with patch.dict("os.environ", {}, clear=True), patch(
                "fast_p.runtime.resource_root", return_value=root,
            ):
                paths = runtime.default_runtime_paths()

            self.assertEqual(str(node), paths["node"])
            self.assertEqual(str(root / "runtime" / "fast-cli"), paths["fast_cli"])
            self.assertEqual(str(chrome), paths["chrome"])

    def test_environment_overrides_bundled_runtime(self):
        with patch.dict("os.environ", {
            "FAST_NODE_BIN": r"D:\tools\node.exe",
            "FAST_CLI_ROOT": r"D:\tools\fast-cli",
            "CHROME_BIN": r"D:\tools\chrome.exe",
        }, clear=True):
            paths = runtime.default_runtime_paths()

        self.assertEqual(r"D:\tools\node.exe", paths["node"])
        self.assertEqual(r"D:\tools\fast-cli", paths["fast_cli"])
        self.assertEqual(r"D:\tools\chrome.exe", paths["chrome"])


if __name__ == "__main__":
    unittest.main()
