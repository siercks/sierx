import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


sbom = module("sbom_check", "sbom_check.py")
snapshot = module("ci_snapshot", "ci-snapshot.py")


class SBOMTests(unittest.TestCase):
    def setUp(self):
        self.fresh = {
            "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "serialNumber": "urn:uuid:11111111-1111-4111-8111-111111111111",
            "metadata": {"timestamp": "2026-09-18T00:00:00Z", "component": {
                "name": "sierx", "version": "fixture", "properties": [
                    {"name": "vcs:commit", "value": "fixture-commit"}]}},
            "components": [{"bom-ref": "pkg:golang/example.test/lib@v1.0.0",
                "name": "example.test/lib", "version": "v1.0.0", "type": "library",
                "licenses": [{"license": {"id": "MIT"}}],
                "properties": [{"name": "go:mod:h1", "value": "h1:fixture"}]}],
        }

    def test_uuid_and_timestamp_may_change(self):
        existing = copy.deepcopy(self.fresh)
        existing["serialNumber"] = "urn:uuid:22222222-2222-4222-8222-222222222222"
        existing["metadata"]["timestamp"] = "2026-09-19T00:00:00Z"
        sbom.check(existing, self.fresh)

    def test_stale_license_hash_and_commit_rejected(self):
        for field in ("licenses", "properties", "type", "version", "bom-ref"):
            with self.subTest(field=field):
                existing = copy.deepcopy(self.fresh)
                existing["components"][0][field] = "stale"
                with self.assertRaises(ValueError):
                    sbom.check(existing, self.fresh)
        existing = copy.deepcopy(self.fresh)
        existing["metadata"]["component"]["properties"][0]["value"] = "stale"
        with self.assertRaises(ValueError):
            sbom.check(existing, self.fresh)

    def test_missing_fields_invalid_types_and_duplicates_rejected(self):
        for field in self.fresh:
            with self.subTest(missing=field):
                existing = copy.deepcopy(self.fresh)
                del existing[field]
                with self.assertRaises(ValueError):
                    sbom.check(existing, self.fresh)
        for key, value in (("version", True), ("serialNumber", "bad"),
                           ("components", []), ("specVersion", "1.4")):
            existing = copy.deepcopy(self.fresh)
            existing[key] = value
            with self.assertRaises(ValueError):
                sbom.check(existing, self.fresh)
        existing = copy.deepcopy(self.fresh)
        existing["components"] *= 2
        with self.assertRaises(ValueError):
            sbom.check(existing, self.fresh)
        with self.assertRaises(ValueError):
            json.loads('{"version":1,"version":2}', object_pairs_hook=sbom.unique_object)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.previous = Path.cwd()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.chdir(self.root)
        subprocess.run(["git", "init", "-q"], check=True)
        Path(".gitignore").write_text(".env\nbin/\n")
        Path(".env").write_text("PRIVATE_VALUE=fixture-only\n")
        Path("tracked.txt").write_text("original")
        Path("deleted.txt").write_text("delete me")
        subprocess.run(["git", "add", "."], check=True)

    def tearDown(self):
        os.chdir(self.previous)
        self.temp.cleanup()

    def test_working_changes_included_host_environment_excluded(self):
        Path("tracked.txt").write_text("edited")
        Path("deleted.txt").unlink()
        Path("new.txt").write_text("untracked")
        Path("bin").mkdir()
        Path("bin/output.tar").touch()
        snapshot.snapshot("bin/output.tar")
        with tarfile.open("bin/output.tar") as archive:
            names = archive.getnames()
            self.assertNotIn(".env", names)
            self.assertNotIn("deleted.txt", names)
            self.assertNotIn("bin/output.tar", names)
            self.assertIn("new.txt", names)
            self.assertEqual(archive.extractfile("tracked.txt").read(), b"edited")

    def test_tracked_host_environment_rejected(self):
        subprocess.run(["git", "add", "-f", ".env"], check=True)
        Path("bin").mkdir()
        with self.assertRaisesRegex(ValueError, "configuration"):
            snapshot.snapshot("bin/output.tar")

    def test_dependency_coverage_source_included_but_root_report_excluded(self):
        Path(".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
        source = Path("vendor/library/coverage.go")
        source.parent.mkdir(parents=True)
        source.write_text("package library\n")
        Path("coverage-summary.txt").write_text("test report")
        Path("bin").mkdir()
        snapshot.snapshot("bin/output.tar")
        with tarfile.open("bin/output.tar") as archive:
            self.assertIn(source.as_posix(), archive.getnames())
            self.assertNotIn("coverage-summary.txt", archive.getnames())


if __name__ == "__main__":
    unittest.main()
