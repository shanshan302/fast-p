import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from fast_p.runtime_update import RuntimePackageError, install_runtime_zip


def make_package(path: Path, version="0.1.8", extra=None):
    manifest = {
        "schemaVersion": 1,
        "name": "@ickey/fast-cli",
        "version": version,
        "apiVersion": 1,
        "platform": "win32-x64",
        "node": ">=20",
        "entry": "fast-cli/bin/fast-scrape-worker.js",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("fast-cli/bin/fast-scrape-worker.js", "// worker")
        for name, value in (extra or {}).items():
            archive.writestr(name, value)


class RuntimeUpdateTest(unittest.TestCase):
    def test_installs_and_atomically_switches_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.zip"
            second = root / "second.zip"
            make_package(first, "0.1.8")
            make_package(second, "0.1.9")
            checked = []

            def checker(node, entry, profile, requirement):
                checked.append((entry, requirement))

            installed = install_runtime_zip(
                first, root / "runtime", Path("node"), "win32-x64", checker,
            )
            install_runtime_zip(second, root / "runtime", Path("node"), "win32-x64", checker)

            self.assertTrue((installed / "bin" / "fast-scrape-worker.js").is_file())
            active = json.loads((root / "runtime" / "active.json").read_text(encoding="utf-8"))
            self.assertEqual("0.1.9", active["active"])
            self.assertEqual("0.1.8", active["previous"])
            self.assertEqual(2, len(checked))

    def test_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "bad.zip"
            make_package(package, extra={"../outside.txt": "bad"})
            with self.assertRaises(RuntimePackageError):
                install_runtime_zip(
                    package, root / "runtime", Path("node"), "win32-x64", lambda *args: None,
                )
            self.assertFalse((root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
