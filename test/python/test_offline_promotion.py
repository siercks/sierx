import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import copy
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


promotion = module("offline_promotion", "offline-promotion.py")
from offline_host_fixture import full_host_report


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
                "release": {"image": self.images[arch], "revision": self.revision},
                'files':{'source.txt':{'size':9,'sha256':__import__('hashlib').sha256(b'candidate').hexdigest()}}}
        lock_bytes = json.dumps(lock, sort_keys=True).encode() + b"\n"
        archive = self.root / f"{stem}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            import io
            entry = tarfile.TarInfo(f"{stem}/bundle.lock.json")
            entry.size = len(lock_bytes)
            bundle.addfile(entry, io.BytesIO(lock_bytes))
            entry=tarfile.TarInfo(f'{stem}/source.txt')
            entry.size=9
            bundle.addfile(entry,io.BytesIO(b'candidate'))
        lock_digest = __import__("hashlib").sha256(lock_bytes).hexdigest()
        (self.root / f"{stem}.lock.sha256").write_text(lock_digest + "\n")
        import hashlib
        (self.root / f"{stem}.tar.gz.sha256").write_text(
            hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + str(archive) + "\n")
        (self.root / f"offline-acceptance-{arch}.json").write_text(json.dumps({
            "arch": arch, "release": lock["release"], "bundle_sha256": lock_digest,
            "external_interfaces": [], "result": "passed", "checks": offline.ACCEPTANCE_CHECKS}))
        approved=json.loads((ROOT/'deploy/ci/previous-offline-release.json').read_text())['architectures'][arch]
        suite=promotion._host_evidence.host.suite_digest()
        for profile in ('ubuntu24','rocky10') if arch=='amd64' else ('ubuntu24',):
            report=full_host_report({'arch':arch,'release':lock['release']},lock_digest,suite,
                'ubuntu-24.04' if profile=='ubuntu24' else 'rocky-10.2',approved)
            report['archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
            (self.root/f'host-acceptance-{profile}-{arch}.json').write_text(json.dumps(report))
            (self.root/f'host-input-{profile}-{arch}.json').write_text(json.dumps({
                'schema':1,'profile':profile,'arch':arch,'release':lock['release'],'bundle_sha256':lock_digest,
                'suite_sha256':suite,'rootfs_sha256':report['rootfs_sha256'],'archive_sha256':report['archive_sha256']}))

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

    def test_missing_host_profile_stale_suite_and_changed_candidate_block_promotion(self):
        for arch in self.images:self.make_bundle_evidence(arch)
        path=self.root/'host-acceptance-rocky10-amd64.json'
        original=json.loads(path.read_text())
        for field,value in (('coverage','development'),('suite_sha256','f'*64),('bundle_sha256','f'*64),('release',{})):
            report=copy.deepcopy(original)
            report[field]=value
            path.write_text(json.dumps(report))
            with self.subTest(field=field),self.assertRaises(ValueError):
                promotion.verify(self.root,self.repository,self.revision)
        path.unlink()
        with self.assertRaises(OSError):promotion.verify(self.root,self.repository,self.revision)

    def test_rehashed_archive_still_cannot_change_tested_inner_files(self):
        import hashlib,io
        for arch in self.images:self.make_bundle_evidence(arch)
        path=self.root/'sierx-offline-amd64.tar.gz'
        with tarfile.open(path,'r:gz') as source:
            lock=source.extractfile('sierx-offline-amd64/bundle.lock.json').read()
        with tarfile.open(path,'w:gz') as target:
            for name,content in (('bundle.lock.json',lock),('source.txt',b'modified!')):
                entry=tarfile.TarInfo('sierx-offline-amd64/'+name)
                entry.size=len(content)
                target.addfile(entry,io.BytesIO(content))
        path.with_suffix(path.suffix+'.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError,'contents differ'):
            promotion.verify(self.root,self.repository,self.revision)

    def test_stable_aggregate_distinguishes_doc_skips_from_missing_native_coverage(self):
        aggregate=promotion._host_evidence.aggregate
        aggregate('success','true','success')
        aggregate('success','false','skipped')
        for args in (('failure','false','skipped'),('success','true','skipped'),
                     ('success','true','cancelled'),('success','true','failure'),('success','','success')):
            with self.subTest(args=args),self.assertRaises(ValueError):aggregate(*args)

    def test_failed_host_job_reports_coverage_failure_without_reading_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/offline-host-evidence.py'),
                'aggregate','--directory',temporary],cwd=ROOT,capture_output=True,text=True,
                env={**os.environ,'SCOPE_RESULT':'success','HOST_REQUIRED':'true','HOST_RESULT':'failure'})
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Required native host coverage failed',result.stderr)
            self.assertNotIn('mismatched',result.stderr)
            self.assertEqual(list(Path(temporary).iterdir()),[])

    def test_scope_only_skips_documentation_and_never_skips_a_release(self):
        helper=promotion._host_evidence
        event={'pull_request':{'base':{'sha':'a'*40}}}
        for files,expected in (('docs/PHASE-2-ACCEPTANCE.md\nREADME.md',False),
                ('web/src/routes/List.tsx',True),('docs/schema.sql',True),('Makefile',True)):
            with self.subTest(files=files),mock.patch.object(helper.offline,'command',return_value=files):
                self.assertEqual(helper.required(event),expected)
                self.assertTrue(helper.required(event,staged=True))
        self.assertTrue(helper.required({}))

    def test_workflow_and_manifest_cannot_promote_before_offline_acceptance(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        offline_job = workflow.index("  offline-bundle:")
        promote_job = workflow.index("  promote:")
        self.assertLess(offline_job, promote_job)
        self.assertIn("  promote:\n    needs: [artifact-test, offline-bundle, host-acceptance]", workflow)
        self.assertIn('uses: ./.github/workflows/offline-host.yml',workflow)
        self.assertIn('pattern: host-evidence-*',workflow)
        host_workflow=(ROOT/'.github/workflows/offline-host.yml').read_text()
        self.assertIn('name: Offline delivery',host_workflow)
        self.assertIn('make offline-host-aggregate',host_workflow)
        self.assertIn('profile: rocky10',host_workflow)
        self.assertIn('runner: ubuntu-26.04-arm\n            profile: ubuntu24\n            arch: arm64',host_workflow)
        self.assertNotIn('packages: write',host_workflow)
        self.assertNotIn('secrets: inherit',host_workflow)
        release_script = (ROOT / "scripts/release.sh").read_text()
        proof = 'python3 scripts/offline-promotion.py verify --repository "$image" --revision "$revision"'
        self.assertIn(proof, release_script)
        self.assertLess(release_script.index(proof), release_script.index("podman manifest create"))


if __name__ == "__main__":
    unittest.main()
