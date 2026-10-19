"""Bind offline acceptance to staged image digests before release promotion."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tarfile
from pathlib import PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import offline  # noqa: E402
_spec = importlib.util.spec_from_file_location("release_evidence", ROOT / "scripts" / "release-evidence.py")
_release_evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_release_evidence)
validate_release = _release_evidence.validate
_host_spec=importlib.util.spec_from_file_location('host_evidence',ROOT/'scripts/offline-host-evidence.py')
_host_evidence=importlib.util.module_from_spec(_host_spec)
_host_spec.loader.exec_module(_host_evidence)


def candidate(directory: Path, repository: str, revision: str, arch: str) -> dict:
    images = validate_release(directory, repository, revision)
    if arch not in images:
        raise ValueError("Unsupported offline candidate architecture")
    return {"image": images[arch], "revision": revision}


def archive_contents(stream,stem,lock):
    """Bind every archived byte to the inventory accepted inside the guest."""
    files=lock.get('files')
    if not isinstance(files,dict) or not files:raise ValueError('Offline archive lacks its tested file inventory')
    seen=set()
    found=set()
    for entry in stream.getmembers():
        name=entry.name.rstrip('/') if entry.isdir() else entry.name
        parts=PurePosixPath(name).parts
        if (not parts or parts[0]!=stem or name.startswith('/') or '..' in parts
                or not (entry.isfile() or entry.isdir()) or name in seen):
            raise ValueError('Offline archive contains an unsafe, duplicate or untested member')
        seen.add(name)
        if entry.isdir():continue
        relative=name[len(stem)+1:]
        if relative=='bundle.lock.json':continue
        record=files.get(relative)
        if (not isinstance(record,dict) or entry.size!=record.get('size')
                or hashlib.file_digest(stream.extractfile(entry),'sha256').hexdigest()!=record.get('sha256')):
            raise ValueError('Offline archive contents differ from the tested bundle inventory')
        found.add(relative)
    if found!=set(files):raise ValueError('Offline archive omitted a tested bundle member')


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
            archive_contents(bundle,f'sierx-offline-{arch}',json.loads(lock_bytes))
        if hashlib.sha256(lock_bytes).hexdigest() != expected_lock:
            raise ValueError("Offline archive lock differs from accepted lock for " + arch)
        lock = json.loads(lock_bytes)
        if (lock.get("arch") != arch or lock.get("release") != expected_release):
            raise ValueError("Offline archive lock identity differs from tested candidate for " + arch)
        for profile in ('ubuntu24','rocky10') if arch=='amd64' else ('ubuntu24',):
            host=json.loads((directory/f'host-acceptance-{profile}-{arch}.json').read_text())
            if (host.get('release')!=expected_release or host.get('bundle_sha256')!=expected_lock
                    or host.get('archive_sha256')!=actual_archive):
                raise ValueError('Rootless host evidence differs from the staged native offline candidate')
    _host_evidence.verify(directory,repository,revision)


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
