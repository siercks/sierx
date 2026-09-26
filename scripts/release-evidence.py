"""Bind release promotion to successful tests of both exact image digests."""
import json
from pathlib import Path
import re
import sys


def validate(directory, repository, revision):
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Release requires a full revision")
    images = {}
    for arch in ("amd64", "arm64"):
        image = (directory / f"image-{arch}.txt").read_text().strip()
        if not re.fullmatch(re.escape(repository) + r"@sha256:[a-f0-9]{64}", image):
            raise ValueError("Missing immutable candidate reference for " + arch)
        evidence = json.loads((directory / f"acceptance-{arch}.json").read_text())
        expected = {"image": image, "revision": revision, "platform": "linux/" + arch,
                    "status": "passed", "checks": ["image-policy", "bootstrap", "partitions",
                    "http-write", "deep-link", "graceful-stop", "restart-persistence"]}
        if evidence != expected:
            raise ValueError("Candidate acceptance is missing, stale or incomplete for " + arch)
        images[arch] = image
    return images


def manifest_matches(manifest, images):
    entries = manifest.get("manifests", [])
    if len(entries) != 2:
        raise ValueError("Release index must contain exactly two image platforms")
    actual = {}
    for entry in entries:
        platform = entry.get("platform", {})
        arch = platform.get("architecture")
        if platform.get("os") != "linux" or arch not in images or arch in actual:
            raise ValueError("Unexpected or repeated image platform")
        actual[arch] = entry.get("digest")
    if actual != {arch: image.split("@", 1)[1] for arch, image in images.items()}:
        raise ValueError("Release index differs from the tested image digests")


if __name__ == "__main__":
    try:
        images = validate(Path("dist"), sys.argv[1], sys.argv[2])
        if len(sys.argv) == 4:
            manifest_matches(json.loads(Path(sys.argv[3]).read_text()), images)
        print("release-evidence: both exact architecture digests accepted")
    except (ValueError, OSError, IndexError) as error:
        sys.exit("release-evidence: " + str(error))
