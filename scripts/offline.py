"""Connected bundle assembly and fail-closed, native Linux offline operations.

The expected lock digest must arrive through an independently trusted channel.
Checksums supplied alongside an untrusted bundle are not publisher signatures.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
HEX = r"[a-f0-9]{64}"
ROLES = {"app", "postgres", "caddy"}
GOOSE = {
    "amd64": ("x86_64", "ab073515b78ef345f64f018c0d79aa7db50106806efc686dda7181253765ae13"),
    "arm64": ("arm64", "3968855c11b4093af271c5226909789ea294468f6e50203d738b7504995b6247"),
}


def native_arch():
    arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    if platform.system() != "Linux" or arch not in GOOSE:
        raise ValueError("Use a native Linux amd64 or arm64 host")
    return arch


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def command(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.PIPE).strip()


def image_id(value):
    value = value.removeprefix("sha256:")
    if not re.fullmatch(HEX, value):
        raise ValueError("Invalid image configuration digest")
    return "sha256:" + value


def pinned(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:/-]+@sha256:" + HEX, value)


def safe_file(root, name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Invalid bundle path")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(name).is_absolute():
        raise ValueError("Invalid bundle path")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Bundle symlinks are not permitted")
    if not path.is_file():
        raise ValueError("Required bundle file is missing: " + name)
    return path


def verify(root, expected, arch=None):
    root = Path(root).resolve()
    if not re.fullmatch(HEX, expected or ""):
        raise ValueError("Supply the independently approved bundle.lock.json SHA-256")
    lock = safe_file(root, "bundle.lock.json")
    if lock.stat().st_size > 4 * 1024 * 1024 or digest(lock) != expected:
        raise ValueError("Bundle lock does not match the approved digest")
    data = json.loads(lock.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or set(data) != {"schema", "arch", "release", "images", "files"}
            or data["schema"] != 1 or data["arch"] != (arch or native_arch())):
        raise ValueError("Unsupported bundle schema or wrong native architecture")
    release = data["release"]
    if (not isinstance(release, dict) or set(release) != {"image", "revision"}
            or not pinned(release["image"]) or not isinstance(release["revision"], str)
            or not re.fullmatch(r"[a-f0-9]{40}", release["revision"])):
        raise ValueError("Invalid bundled release")
    if not isinstance(data["images"], dict) or set(data["images"]) != ROLES:
        raise ValueError("Bundle must include app, postgres and caddy images")
    for role, info in data["images"].items():
        if (not isinstance(info, dict) or set(info) != {"source", "id", "archive"}
                or not pinned(info["source"]) or info["archive"] != "images/" + role + ".tar"
                or not isinstance(info["id"], str) or image_id(info["id"]) != info["id"]):
            raise ValueError("Invalid bundled image record")
    if data["images"]["app"]["source"] != release["image"]:
        raise ValueError("Application image differs from accepted release")
    files = data["files"]
    required = {"release.json", "bin/goose", "bin/sierxctl", "LICENSE", "NOTICE",
                "scripts/offline.py", "scripts/deploy.py", "scripts/db.sh", "scripts/migrate.sh",
                "inventory/application.cdx.json", *("images/" + role + ".tar" for role in ROLES)}
    if not isinstance(files, dict) or not required.issubset(files) or not any(n.startswith("migrations/") and n.endswith(".sql") for n in files):
        raise ValueError("Incomplete bundle inventory")
    for name, record in files.items():
        if (name == "bundle.lock.json" or not isinstance(record, dict) or set(record) != {"sha256", "size"}
                or not isinstance(record["sha256"], str) or not re.fullmatch(HEX, record["sha256"])
                or type(record["size"]) is not int or record["size"] < 0):
            raise ValueError("Invalid bundle file record")
        path = safe_file(root, name)
        if path.stat().st_size != record["size"] or digest(path) != record["sha256"]:
            raise ValueError("Bundle file failed verification: " + name)
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError("Bundle contains a link or special file")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(files) | {"bundle.lock.json"}:
        raise ValueError("Bundle contains unlisted files; keep configuration and data outside it")
    if json.loads((root / "release.json").read_text()) != release:
        raise ValueError("Bundled release manifest differs from lock")
    return data


def inspect_image(info, arch, revision=None):
    metadata = json.loads(command("podman", "image", "inspect", info["id"]))[0]
    if image_id(metadata["Id"]) != info["id"] or metadata.get("Architecture") != arch or metadata.get("Os") != "linux":
        raise ValueError("Loaded image identity or platform differs from approved bundle")
    if revision and (metadata.get("Labels") or {}).get("org.opencontainers.image.revision") != revision:
        raise ValueError("Loaded application revision differs from approved release")


def from_environment():
    root = Path(os.environ.get("SIERX_OFFLINE_BUNDLE", ""))
    if not root.is_absolute():
        raise ValueError("SIERX_OFFLINE_BUNDLE must be an absolute directory")
    return root, verify(root, os.environ.get("SIERX_OFFLINE_SHA256", ""))


def prepare(release_path, caddy, output, sbom):
    arch = native_arch()
    release = json.loads(Path(release_path).read_text())
    if (not isinstance(release, dict) or set(release) != {"image", "revision"}
            or not pinned(release["image"]) or not pinned(caddy)):
        raise ValueError("Use the promoted release.json and a digest-pinned Caddy image")
    revision = command("git", "rev-parse", "HEAD", cwd=ROOT)
    if release["revision"] != revision or command("git", "status", "--porcelain", cwd=ROOT):
        raise ValueError("Assemble from a clean committed checkout at the exact release revision")
    inventory = json.loads(Path(sbom).read_text())
    properties = inventory.get("metadata", {}).get("component", {}).get("properties", [])
    if inventory.get("bomFormat") != "CycloneDX" or {"name": "vcs:commit", "value": revision} not in properties:
        raise ValueError("Application SBOM must identify the exact release revision")
    output = Path(output).absolute()
    if output.exists():
        raise ValueError("Bundle output must not exist; incomplete bundles are never overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Failed assembly leaves no apparently complete destination.
    with tempfile.TemporaryDirectory(prefix="sierx-bundle-", dir=output.parent) as temporary:
        root = Path(temporary) / "bundle"
        root.mkdir()
        for line in command("git", "ls-files", "--stage", cwd=ROOT).splitlines():
            metadata, name = line.split("\t", 1)
            mode, blob, stage = metadata.split()
            if mode not in {"100644", "100755"} or stage != "0" or name.startswith('"'):
                raise ValueError("Bundle source must contain only regular tracked files")
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(subprocess.check_output(["git", "cat-file", "blob", blob], cwd=ROOT))
            path.chmod(0o755 if mode == "100755" else 0o644)
        (root / "images").mkdir()
        (root / "bin").mkdir()
        (root / "inventory").mkdir()
        shutil.copyfile(sbom, root / "inventory/application.cdx.json")
        (root / "release.json").write_text(json.dumps(release, indent=2) + "\n")
        postgres = re.search(r"^Image=(.+)$", (root / "deploy/quadlet/sierx-postgres.container").read_text(), re.M)[1]
        if not pinned(postgres):
            raise ValueError("PostgreSQL image must be digest pinned")
        images = {}
        for role, source in (("app", release["image"]), ("postgres", postgres), ("caddy", caddy)):
            command("podman", "pull", "--arch", arch, source)
            metadata = json.loads(command("podman", "image", "inspect", source))[0]
            info = {"source": source, "id": image_id(metadata["Id"]), "archive": "images/" + role + ".tar"}
            inspect_image(info, arch, revision if role == "app" else None)
            command("podman", "save", "--format", "oci-archive", "--output", str(root / info["archive"]), info["id"])
            images[role] = info
        container = command("podman", "create", "--pull=never", images["app"]["id"])
        try:
            command("podman", "cp", container + ":/usr/local/bin/sierxctl", str(root / "bin/sierxctl"))
        finally:
            command("podman", "rm", container)
        # This is the only non-image download. Pin and verify before execution.
        import urllib.request
        goose_arch, checksum = GOOSE[arch]
        with urllib.request.urlopen("https://github.com/pressly/goose/releases/download/v3.28.0/goose_linux_" + goose_arch, timeout=60) as response:
            with (root / "bin/goose").open("wb") as destination:
                shutil.copyfileobj(response, destination)
        if digest(root / "bin/goose") != checksum:
            raise ValueError("Goose download failed its pinned checksum")
        with urllib.request.urlopen("https://raw.githubusercontent.com/pressly/goose/v3.28.0/LICENSE", timeout=60) as response:
            license_text = response.read(65537)
        if len(license_text) > 65536 or not license_text:
            raise ValueError("Invalid Goose license document")
        (root / "inventory/goose-LICENSE").write_bytes(license_text)
        (root / "inventory/operator-tools.json").write_text(json.dumps({
            "goose": {"version": "v3.28.0", "sha256": checksum, "license": "goose-LICENSE"},
            "sierxctl": {"source": release["image"], "revision": revision, "sha256": digest(root / "bin/sierxctl")},
            "runtime_images": images}, indent=2) + "\n")
        for name in ("goose", "sierxctl"):
            (root / "bin" / name).chmod(0o755)
        files = {p.relative_to(root).as_posix(): {"sha256": digest(p), "size": p.stat().st_size}
                 for p in sorted(root.rglob("*")) if p.is_file()}
        lock = root / "bundle.lock.json"
        lock.write_text(json.dumps({"schema": 1, "arch": arch, "release": release, "images": images, "files": files}, indent=2, sort_keys=True) + "\n")
        expected = digest(lock)
        verify(root, expected, arch)
        root.rename(output)
    print("offline: bundle assembled for " + arch + "; approved lock SHA-256: " + expected)


def run_operation(root, data, operation):
    if operation == "import":
        for role, info in sorted(data["images"].items()):
            command("podman", "load", "--input", str(root / info["archive"]))
            inspect_image(info, data["arch"], data["release"]["revision"] if role == "app" else None)
        print("offline: all three native images imported and verified; no services changed")
        return
    if operation == "image-postgres":
        info = data["images"]["postgres"]
        inspect_image(info, data["arch"])
        print(info["id"])
        return
    commands = {
        "db-up": ["bash", "scripts/db.sh", "up"],
        "migrate-up": ["bash", "scripts/migrate.sh", "up"],
        "migrate-status": ["bash", "scripts/migrate.sh", "status"],
        "bootstrap": ["bin/sierxctl", "bootstrap"],
        "plan": ["python3", "-B", "scripts/deploy.py", "plan"],
        "apply": ["python3", "-B", "scripts/deploy.py", "apply"],
        "smoke": ["python3", "-B", "scripts/release-smoke.py"],
        "restore-test": ["bin/sierxctl", "restore-test"],
        "backup": ["bash", "scripts/backup/run.sh"],
    }
    if operation not in commands:
        raise ValueError("Unknown offline operation")
    if operation in {"backup", "restore-test"}:
        destination = Path(os.environ.get("SIERX_DUMP_DIR", ""))
        if not destination.is_absolute() or destination.resolve().is_relative_to(root.resolve()):
            raise ValueError("Set SIERX_DUMP_DIR to an absolute data directory outside the immutable bundle")
    for tool in ("goose", "sierxctl"):
        if not os.access(root / "bin" / tool, os.X_OK):
            raise ValueError("Restore executable permissions on bin/goose and bin/sierxctl")
    environment = {**os.environ, "SIERX_NETWORK_MODE": "offline", "PYTHONDONTWRITEBYTECODE": "1",
                   "SIERX_DEPLOY_MANIFEST_FILE": str(root / "release.json"),
                   "SIERX_IMAGE_REPOSITORY": data["release"]["image"].split("@")[0],
                   "SIERX_CADDY_IMAGE": data["images"]["caddy"]["source"], "GOOSE": str(root / "bin/goose")}
    environment.pop("SIERX_DEPLOY_MANIFEST_URL", None)
    if operation == "restore-test":
        default_state = Path(os.path.expanduser("~")) / ".local/share/sierx/restore"
        directory = Path(os.environ.get("SIERX_RESTORE_STATE_DIR") or default_state)
        if not directory.is_absolute() or directory.resolve().is_relative_to(root.resolve()):
            raise ValueError("Restore state must be an absolute directory outside the immutable bundle")
        environment["SIERX_RESTORE_STATE_DIR"] = str(directory)
    subprocess.run(commands[operation], cwd=root, env=environment, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    build = sub.add_parser("prepare")
    for name in ("release", "caddy-image", "output", "sbom"):
        build.add_argument("--" + name, required=True)
    check = sub.add_parser("verify")
    check.add_argument("--bundle", required=True)
    check.add_argument("--expected-sha256", required=True)
    for name in ("import", "image-postgres", "db-up", "migrate-up", "migrate-status", "bootstrap", "plan", "apply", "smoke", "restore-test", "backup"):
        sub.add_parser(name)
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare(args.release, args.caddy_image, args.output, args.sbom)
    elif args.operation == "verify":
        verify(Path(args.bundle), args.expected_sha256)
        print("offline: approved inventory, checksums and native architecture verified")
    else:
        root, data = from_environment()
        run_operation(root, data, args.operation)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        # Never include commands, private environment values, or response bodies.
        detail = str(error) if isinstance(error, ValueError) else "operation failed; check prerequisites and private service logs"
        sys.exit("offline: " + detail)
