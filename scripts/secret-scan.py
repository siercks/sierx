#!/usr/bin/env python3
"""Offline, redacted high-confidence credential scan for source and web output."""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{8,}\b")),
)
ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|passwd|secret|token)\b"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9+/=_-]{32,})"
)
EXTENSIONS = {
    ".c", ".cc", ".css", ".go", ".h", ".html", ".js", ".json", ".md",
    ".mjs", ".py", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".txt",
    ".xml", ".yaml", ".yml",
}
EXCLUDED_PARTS = {".git", "node_modules", "vendor", "coverage"}


def entropy(value: str) -> float:
    counts = Counter(value)
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in counts.values())


def detect(text: str) -> set[str]:
    kinds = {name for name, pattern in PATTERNS if pattern.search(text)}
    for match in ASSIGNMENT.finditer(text):
        value = match.group(1).rstrip(".;,")
        if len(value) >= 32 and entropy(value) >= 3.7:
            kinds.add("high-entropy-credential-assignment")
    return kinds


def self_test() -> None:
    samples = {
        "-----BEGIN " + "PRIVATE KEY-----": "private-key",
        "AWS=" + "AKIA" + "ABCDEFGHIJKLMNOP": "aws-access-key",
        "GITHUB=" + "ghp_" + "abcdefghijklmnopqrstuvwxyz012345": "github-token",
        "SLACK=" + "xoxb-" + "123456789012345678901234": "slack-token",
        "GOOGLE=" + "AIza" + "01234567890123456789012345678901234": "google-api-key",
        "TOKEN=" + "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0" + ".signature12345678": "jwt",
        "secret=" + "6b9fdd25a1e760f51cedb3e904f2a0173c8a4b6e": "high-entropy-credential-assignment",
    }
    for sample, expected in samples.items():
        if expected not in detect(sample):
            raise RuntimeError(f"synthetic detector control failed: {expected}")
    if detect("password=test-password-12345"):
        raise RuntimeError("safe fixture control falsely detected a low-entropy test password")
    print(f"secret-scan: {len(samples)} synthetic detections and safe-fixture control passed")


def files_to_scan(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, check=True, stdout=subprocess.PIPE,
    )
    paths = {root / name.decode("utf-8", "surrogateescape") for name in result.stdout.split(b"\0") if name}
    web_dist = root / "web" / "dist"
    if web_dist.is_dir():
        paths.update(path for path in web_dist.rglob("*") if path.is_file())
    return sorted(
        path for path in paths
        if path.is_file()
        and path.suffix.lower() in EXTENSIONS
        and not any(part in EXCLUDED_PARTS for part in path.parts)
    )


def scan(root: Path) -> int:
    files = files_to_scan(root)
    findings: list[tuple[str, int, str]] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(content.splitlines(), 1):
            for kind in sorted(detect(line)):
                findings.append((str(path.relative_to(root)), number, kind))
    if findings:
        print("secret-scan: credential patterns found; matching content is redacted", file=sys.stderr)
        for path, line, kind in findings:
            print(f"  {path}:{line} ({kind})", file=sys.stderr)
        return 1
    print(f"secret-scan: {len(files)} source and built-artifact files scanned; no credential patterns")
    return 0


def scan_history(root: Path) -> int:
    listing = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        cwd=root, check=True, stdout=subprocess.PIPE,
    ).stdout
    blobs: dict[bytes, str] = {}
    for record in listing.splitlines():
        fields = record.split(b" ", 1)
        if len(fields) != 2:
            continue
        object_id, raw_path = fields
        path = raw_path.decode("utf-8", "replace")
        if Path(path).suffix.lower() not in EXTENSIONS:
            continue
        if any(part in EXCLUDED_PARTS for part in Path(path).parts):
            continue
        blobs.setdefault(object_id, path)
    if not blobs:
        print("secret-scan history: no source blobs found")
        return 0
    output = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root, check=True,
        input=b"".join(object_id + b"\n" for object_id in blobs), stdout=subprocess.PIPE,
    ).stdout
    offset = 0
    count = 0
    findings: list[tuple[str, str, int, str]] = []
    while offset < len(output):
        newline = output.find(b"\n", offset)
        if newline < 0:
            raise RuntimeError("git cat-file returned a malformed history record")
        header = output[offset:newline].split()
        if len(header) != 3:
            raise RuntimeError("git cat-file returned a malformed history header")
        object_id, object_type, size_text = header
        size = int(size_text)
        start, end = newline + 1, newline + 1 + size
        content = output[start:end]
        offset = end + 1
        if object_type != b"blob":
            continue
        count += 1
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        path = blobs.get(object_id, "unknown")
        for number, line in enumerate(decoded.splitlines(), 1):
            for kind in sorted(detect(line)):
                findings.append((object_id.decode(), path, number, kind))
    if findings:
        print("secret-scan history: credential patterns found; matching content is redacted", file=sys.stderr)
        for object_id, path, line, kind in findings:
            print(f"  {object_id[:12]}:{path}:{line} ({kind})", file=sys.stderr)
        return 1
    print(f"secret-scan history: {count} distinct source blobs across local refs scanned; no credential patterns")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--history", action="store_true", help="scan source blobs reachable from all local refs")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.self_test:
        self_test()
    result = scan(root)
    if args.history:
        result |= scan_history(root)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
