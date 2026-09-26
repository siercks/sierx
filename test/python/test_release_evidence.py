import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "release_evidence", Path(__file__).parents[2] / "scripts/release-evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class ReleaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = "example.test/sierx"
        self.revision = "a" * 40
        self.images = {}
        for arch, digest in (("amd64", "b"), ("arm64", "c")):
            image = self.repository + "@sha256:" + digest * 64
            self.images[arch] = image
            (self.root / f"image-{arch}.txt").write_text(image)
            (self.root / f"acceptance-{arch}.json").write_text(json.dumps({
                "image": image, "revision": self.revision, "platform": "linux/" + arch,
                "status": "passed", "checks": ["image-policy", "bootstrap", "partitions",
                "http-write", "deep-link", "graceful-stop", "restart-persistence"]}))

    def test_requires_both_successful_exact_candidates(self):
        self.assertEqual(evidence.validate(self.root, self.repository, self.revision), self.images)
        path = self.root / "acceptance-arm64.json"
        original = json.loads(path.read_text())
        for key, value in (("status", "failed"), ("revision", "d" * 40),
                           ("image", self.images["amd64"]), ("platform", "linux/amd64"),
                           ("checks", [])):
            changed = {**original, key: value}
            path.write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence.validate(self.root, self.repository, self.revision)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            evidence.validate(self.root, self.repository, self.revision)

    def test_index_must_preserve_tested_children_and_platforms(self):
        manifest = {"manifests": [{"digest": image.split("@")[1],
                    "platform": {"os": "linux", "architecture": arch}}
                    for arch, image in self.images.items()]}
        evidence.manifest_matches(manifest, self.images)
        wrong_digest = copy.deepcopy(manifest)
        wrong_digest["manifests"][0]["digest"] = "sha256:" + "e" * 64
        duplicate = {"manifests": [manifest["manifests"][0]] * 2}
        wrong_os = copy.deepcopy(manifest)
        wrong_os["manifests"][0]["platform"]["os"] = "windows"
        for bad in ({}, {"manifests": manifest["manifests"][:1]}, wrong_digest, duplicate, wrong_os):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                evidence.manifest_matches(bad, self.images)


if __name__ == "__main__":
    unittest.main()
