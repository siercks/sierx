import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


promotion = module("offline_promotion", "offline-promotion.py")


class OfflinePromotionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = "example.test/sierx"
        self.revision = "a" * 40
        self.images = {}
        for arch, letter in (("amd64", "b"), ("arm64", "c")):
            image = self.repository + "@sha256:" + letter * 64
            self.images[arch] = image
            (self.root / f"image-{arch}.txt").write_text(image)
            (self.root / f"acceptance-{arch}.json").write_text(json.dumps({
                "image": image, "revision": self.revision, "platform": "linux/" + arch,
                "status": "passed", "checks": ["image-policy", "bootstrap", "partitions",
                "http-write", "deep-link", "graceful-stop", "restart-persistence"]}))

    def test_candidate_manifest_uses_tested_native_child(self):
        self.assertEqual(promotion.candidate(self.root, self.repository, self.revision, "arm64"),
                         {"image": self.images["arm64"], "revision": self.revision})
        with self.assertRaises(ValueError):
            promotion.candidate(self.root, self.repository, "d" * 40, "amd64")

    def make_bundle_evidence(self, arch):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import offline

        stem = f"sierx-offline-{arch}"
        lock = {"schema": 1, "arch": arch,
                "release": {"image": self.images[arch], "revision": self.revision}}
        lock_bytes = json.dumps(lock, sort_keys=True).encode() + b"\n"
        archive = self.root / f"{stem}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            import io
            entry = tarfile.TarInfo(f"{stem}/bundle.lock.json")
            entry.size = len(lock_bytes)
            bundle.addfile(entry, io.BytesIO(lock_bytes))
        lock_digest = __import__("hashlib").sha256(lock_bytes).hexdigest()
        (self.root / f"{stem}.lock.sha256").write_text(lock_digest + "\n")
        import hashlib
        (self.root / f"{stem}.tar.gz.sha256").write_text(
            hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + str(archive) + "\n")
        (self.root / f"offline-acceptance-{arch}.json").write_text(json.dumps({
            "arch": arch, "release": lock["release"], "bundle_sha256": lock_digest,
            "external_interfaces": [], "result": "passed", "checks": offline.ACCEPTANCE_CHECKS}))

    def test_both_native_offline_acceptances_are_required(self):
        for arch in self.images:
            self.make_bundle_evidence(arch)
        promotion.verify(self.root, self.repository, self.revision)
        (self.root / "offline-acceptance-arm64.json").unlink()
        with self.assertRaises((ValueError, OSError)):
            promotion.verify(self.root, self.repository, self.revision)

    def test_stale_candidate_and_tampered_bundle_are_rejected(self):
        for arch in self.images:
            self.make_bundle_evidence(arch)
        path = self.root / "offline-acceptance-amd64.json"
        stale = json.loads(path.read_text())
        stale["release"]["image"] = self.images["arm64"]
        path.write_text(json.dumps(stale))
        with self.assertRaises(ValueError):
            promotion.verify(self.root, self.repository, self.revision)
        self.make_bundle_evidence("amd64")
        with (self.root / "sierx-offline-amd64.tar.gz").open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaises(ValueError):
            promotion.verify(self.root, self.repository, self.revision)

    def test_workflow_and_manifest_cannot_promote_before_offline_acceptance(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        offline_job = workflow.index("  offline-bundle:")
        promote_job = workflow.index("  promote:")
        self.assertLess(offline_job, promote_job)
        self.assertIn("  promote:\n    needs: [artifact-test, offline-bundle]", workflow)
        release_script = (ROOT / "scripts/release.sh").read_text()
        proof = 'python3 scripts/offline-promotion.py verify --repository "$image" --revision "$revision"'
        self.assertIn(proof, release_script)
        self.assertLess(release_script.index(proof), release_script.index("podman manifest create"))


if __name__ == "__main__":
    unittest.main()
