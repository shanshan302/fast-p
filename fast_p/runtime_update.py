import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile


PACKAGE_NAME = "@ickey/fast-cli"
WORKER_API_VERSION = 1
MAX_FILES = 20_000
MAX_UNCOMPRESSED_BYTES = 600 * 1024 * 1024


class RuntimePackageError(RuntimeError):
    pass


def current_platform():
    if os.name != "nt":
        return "unsupported"
    return "win32-x64"


def _validated_members(archive: zipfile.ZipFile):
    members = archive.infolist()
    if len(members) > MAX_FILES:
        raise RuntimePackageError(f"更新包文件过多：{len(members)}")
    if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
        raise RuntimePackageError("更新包解压后超过 600MB")
    seen = set()
    for member in members:
        name = member.filename.replace("\\", "/")
        path = PurePosixPath(name)
        key = name.casefold()
        mode = (member.external_attr >> 16) & 0o170000
        if (
            not name
            or path.is_absolute()
            or ".." in path.parts
            or (path.parts and ":" in path.parts[0])
            or key in seen
            or mode == stat.S_IFLNK
        ):
            raise RuntimePackageError(f"更新包包含不安全路径：{member.filename}")
        seen.add(key)
    return members


def _load_manifest(archive: zipfile.ZipFile):
    try:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8-sig"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimePackageError("更新包缺少有效 manifest.json") from exc
    required = {"schemaVersion", "name", "version", "apiVersion", "platform", "node", "entry"}
    if not isinstance(manifest, dict) or not required.issubset(manifest):
        raise RuntimePackageError("manifest.json 字段不完整")
    if manifest["schemaVersion"] != 1 or manifest["name"] != PACKAGE_NAME:
        raise RuntimePackageError("不是 Fast-P 支持的 fast-cli 更新包")
    if manifest["apiVersion"] != WORKER_API_VERSION:
        raise RuntimePackageError(
            f"采集协议不兼容：{manifest['apiVersion']}，当前支持 {WORKER_API_VERSION}"
        )
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", str(manifest["version"])):
        raise RuntimePackageError("fast-cli 版本号无效")
    entry = PurePosixPath(str(manifest["entry"]).replace("\\", "/"))
    if entry.is_absolute() or ".." in entry.parts or not entry.parts:
        raise RuntimePackageError("fast-cli 入口路径无效")
    return manifest


def check_worker(node: Path, entry: Path, profile: Path, node_requirement: str):
    version = subprocess.run(
        [str(node), "--version"], capture_output=True, text=True, timeout=15, check=True,
    ).stdout.strip()
    match = re.fullmatch(r"v(\d+)(?:\.\d+){2}", version)
    required = re.fullmatch(r">=(\d+)", str(node_requirement).strip())
    if not match or not required or int(match.group(1)) < int(required.group(1)):
        raise RuntimePackageError(f"Node 版本不满足要求：已安装 {version}，需要 {node_requirement}")

    help_result = subprocess.run(
        [str(node), str(entry), "--help"], capture_output=True, text=True, timeout=30,
    )
    if help_result.returncode:
        raise RuntimePackageError(help_result.stderr.strip() or "fast-cli Worker --help 检查失败")

    request = json.dumps({"apiVersion": 1, "id": "health", "action": "shutdown"}) + "\n"
    handshake = subprocess.run(
        [str(node), str(entry), "--profile-dir", str(profile)],
        input=request,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if handshake.returncode:
        raise RuntimePackageError(handshake.stderr.strip() or "fast-cli Worker 握手失败")
    try:
        events = [json.loads(line) for line in handshake.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise RuntimePackageError("fast-cli Worker 握手输出不是有效 JSONL") from exc
    if not any(event.get("type") == "ready" and event.get("apiVersion") == 1 for event in events):
        raise RuntimePackageError("fast-cli Worker 未返回兼容的 ready 事件")


def install_runtime_zip(
    archive_path: Path,
    install_root: Path,
    node: Path,
    expected_platform: str | None = None,
    checker=check_worker,
):
    archive_path = Path(archive_path).expanduser().resolve()
    install_root = Path(install_root).expanduser().resolve()
    if not archive_path.is_file():
        raise RuntimePackageError(f"更新包不存在：{archive_path}")
    install_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".import-", dir=install_root))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = _validated_members(archive)
            manifest = _load_manifest(archive)
            platform = expected_platform or current_platform()
            if manifest["platform"] != platform:
                raise RuntimePackageError(
                    f"更新包平台不匹配：{manifest['platform']}，当前需要 {platform}"
                )
            archive.extractall(stage, members)

        entry = stage.joinpath(*PurePosixPath(manifest["entry"]).parts)
        if not entry.is_file():
            raise RuntimePackageError(f"更新包缺少 Worker 入口：{manifest['entry']}")
        profile = stage / ".health-profile"
        checker(Path(node), entry, profile, manifest["node"])
        shutil.rmtree(profile, ignore_errors=True)

        versions = install_root / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        target = versions / manifest["version"]
        if target.exists():
            raise RuntimePackageError(f"fast-cli {manifest['version']} 已经安装")
        os.replace(stage, target)
        stage = None

        active_file = install_root / "active.json"
        previous = None
        try:
            previous = json.loads(active_file.read_text(encoding="utf-8")).get("active")
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        state = {
            "active": manifest["version"],
            "previous": previous if previous != manifest["version"] else None,
            "entry": manifest["entry"],
        }
        temporary = install_root / f"active-{uuid.uuid4().hex}.json"
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, active_file)
        return target / "fast-cli"
    except (zipfile.BadZipFile, OSError, subprocess.SubprocessError) as exc:
        if isinstance(exc, RuntimePackageError):
            raise
        raise RuntimePackageError(str(exc)) from exc
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
