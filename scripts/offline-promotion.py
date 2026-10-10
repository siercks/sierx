"""Bind offline acceptance to staged image digests before release promotion."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tarfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import offline  # noqa: E402
_spec = importlib.util.spec_from_file_location("release_evidence", ROOT / "scripts" / "release-evidence.py")
_release_evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_release_evidence)
validate_release = _release_evidence.validate


def candidate(directory: Path, repository: str, revision: str, arch: str) -> dict:
    images = validate_release(directory, repository, revision)
    if arch not in images:
        raise ValueError("Unsupported offline candidate architecture")
    return {"image": images[arch], "revision": revision}


def verify(directory: Path, repository: str, revision: str) -> None:
    images = validate_release(directory, repository, revision)
    for arch, image in images.items():
        stem = f"sierx-offline-{arch}"
        report = json.loads((directory / f"offline-acceptance-{arch}.json").read_text())
        expected_lock = (directory / f"{stem}.lock.sha256").read_text().strip()
        archive_line = (directory / f"{stem}.tar.gz.sha256").read_text().split()
        archive = directory / f"{stem}.tar.gz"
        with archive.open("rb") as stream:
            actual_archive = hashlib.file_digest(stream, "sha256").hexdigest()
        if not re.fullmatch(r"[a-f0-9]{64}", expected_lock):
            raise ValueError("Missing offline bundle lock digest for " + arch)
        expected_release = {"image": image, "revision": revision}
        if (report != {"arch": arch, "release": expected_release,
                       "bundle_sha256": expected_lock, "external_interfaces": [],
                       "result": "passed", "checks": offline.ACCEPTANCE_CHECKS}):
            raise ValueError("Offline acceptance is missing, stale or incomplete for " + arch)
        if (len(archive_line) < 1 or archive_line[0] != actual_archive
                or not re.fullmatch(r"[a-f0-9]{64}", archive_line[0])):
            raise ValueError("Offline archive digest mismatch for " + arch)
        with tarfile.open(archive, "r:gz") as bundle:
            member = f"sierx-offline-{arch}/bundle.lock.json"
            entry = bundle.getmember(member)
            if not entry.isfile():
                raise ValueError("Offline archive has no regular bundle lock for " + arch)
            lock_bytes = bundle.extractfile(entry).read()
        if hashlib.sha256(lock_bytes).hexdigest() != expected_lock:
            raise ValueError("Offline archive lock differs from accepted lock for " + arch)
        lock = json.loads(lock_bytes)
        if (lock.get("arch") != arch or lock.get("release") != expected_release):
            raise ValueError("Offline archive lock identity differs from tested candidate for " + arch)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("candidate", "verify"))
    parser.add_argument("--arch", choices=("amd64", "arm64"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--directory", type=Path, default=Path("dist"))
    args = parser.parse_args()
    if args.operation == "candidate":
        if not args.arch:
            raise ValueError("Candidate manifest requires --arch")
        release = candidate(args.directory, args.repository, args.revision, args.arch)
        (args.directory / "release.json").write_text(json.dumps(release, indent=2) + "\n")
    else:
        verify(args.directory, args.repository, args.revision)
        print("offline-promotion: both native bundles match tested candidate digests")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        sys.exit("offline-promotion: " + str(error))
