"""Offline delivery boundaries, including rejection before any host mutation."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import hashlib
import urllib.request
import shutil
from unittest import mock

ROOT = Path(__file__).parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ("scripts/" + name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


offline, deploy = load("offline"), load("deploy")


def fixture(root):
    release = {"image": "example.test/sierx@sha256:" + "a" * 64, "revision": "b" * 40}
    names = ["bin/goose", "bin/sierxctl", "LICENSE", "NOTICE", "scripts/offline.py", "scripts/deploy.py",
             "scripts/db.sh", "scripts/migrate.sh", "migrations/0001.sql", "inventory/application.cdx.json"]
    images = {}
    for index, role in enumerate(sorted(offline.ROLES)):
        name = "images/" + role + ".tar"
        names.append(name)
        images[role] = {"source": release["image"] if role == "app" else "example.test/" + role + "@sha256:" + "c" * 64,
                        "id": "sha256:" + str(index + 1) * 64, "archive": name}
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
        if name.startswith("bin/"):
            path.chmod(0o755)
    (root / "release.json").write_text(json.dumps(release))
    data = {"schema": 1, "arch": "amd64", "release": release, "images": images,
            "files": {p.relative_to(root).as_posix(): {"sha256": offline.digest(p), "size": p.stat().st_size}
                      for p in root.rglob("*") if p.is_file()}}
    return data, write_lock(root, data)


def write_lock(root, data):
    lock = root / "bundle.lock.json"
    lock.write_text(json.dumps(data))
    return offline.digest(lock)


class VerificationTests(unittest.TestCase):
    def test_archive_evidence_must_cover_exact_bundle_platform_and_all_checks(self):
        data = {"arch": "amd64", "release": {"revision": "b" * 40}}
        report = {**data, "result": "passed", "bundle_sha256": "a" * 64,
                  "external_interfaces": [], "checks": offline.ACCEPTANCE_CHECKS}
        offline.verify_evidence(data, "a" * 64, report)
        for change in ({"result": "failed"}, {"arch": "arm64"}, {"release": {}}, {"bundle_sha256": "c" * 64},
                       {"external_interfaces": ["eth0"]}, {"checks": offline.ACCEPTANCE_CHECKS[:-1]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                offline.verify_evidence(data, "a" * 64, {**report, **change})

    def test_baseline_then_corruption_missing_file_and_added_secret_fail(self):
        for defect in ("corrupt", "missing", "extra", "lock", "wrong-arch"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                data, expected = fixture(root)
                self.assertEqual(offline.verify(root, expected, "amd64"), data)
                if defect == "corrupt": (root / "images/app.tar").write_text("tamper!")
                elif defect == "missing": (root / "migrations/0001.sql").unlink()
                elif defect == "extra": (root / ".env").write_text("do not ship credentials")
                elif defect == "lock": (root / "bundle.lock.json").write_text("{}")
                with self.assertRaises(ValueError):
                    offline.verify(root, expected, "arm64" if defect == "wrong-arch" else "amd64")

    def test_hostile_inventory_and_release_mismatch_fail_even_with_matching_lock_hash(self):
        for defect in ("../escape", "/absolute", "dir/../escape", "dir\\escape", "C:escape", "missing-role", "other-release", "missing-tool"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                data, _ = fixture(root)
                if defect == "missing-role": del data["images"]["postgres"]
                elif defect == "other-release": data["release"]["revision"] = "d" * 40
                elif defect == "missing-tool": del data["files"]["bin/goose"]
                else: data["files"][defect] = {"sha256": "f" * 64, "size": 0}
                with self.assertRaises(ValueError): offline.verify(root, write_lock(root, data), "amd64")

    @unittest.skipIf(os.name == "nt", "symlink fixture requires Linux privileges")
    def test_symlink_substitution_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, expected = fixture(root)
            (root / "bin/goose").unlink()
            (root / "bin/goose").symlink_to(root / "bin/sierxctl")
            with self.assertRaises(ValueError): offline.verify(root, expected, "amd64")

    def test_import_checks_platform_and_revision_without_pull_or_service_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, _ = fixture(root)
            commands = []
            by_id = {info["id"]: role for role, info in data["images"].items()}
            def command(*args):
                commands.append(args)
                if args[:3] == ("podman", "image", "inspect"):
                    return json.dumps([{"Id": args[-1], "Architecture": "amd64", "Os": "linux",
                                        "Labels": {"org.opencontainers.image.revision": data["release"]["revision"]} if by_id[args[-1]] == "app" else {}}])
                return ""
            with mock.patch.object(offline, "command", side_effect=command), contextlib.redirect_stdout(io.StringIO()):
                offline.run_operation(root, data, "import")
            self.assertEqual(sum(args[:2] == ("podman", "load") for args in commands), 3)
            self.assertTrue(all(args[:2] in (("podman", "load"), ("podman", "image")) for args in commands))
            for change in ({"Architecture": "arm64"}, {"Labels": {}}, {"Id": "0" * 64}):
                metadata = {"Id": data["images"]["app"]["id"], "Architecture": "amd64", "Os": "linux", "Labels": {"org.opencontainers.image.revision": data["release"]["revision"]}, **change}
                with mock.patch.object(offline, "command", return_value=json.dumps([metadata])), self.assertRaises(ValueError):
                    offline.inspect_image(data["images"]["app"], "amd64", data["release"]["revision"])

    def test_operations_override_online_inputs_without_reset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, _ = fixture(root)
            with mock.patch.dict(os.environ, {"SIERX_DEPLOY_MANIFEST_URL": "https://example.test/release.json", "GOOSE": "/wrong"}), mock.patch.object(offline.os, "access", return_value=True), mock.patch.object(offline.subprocess, "run") as run:
                offline.run_operation(root, data, "migrate-up")
                args, kwargs = run.call_args
                self.assertEqual(args[0], ["bash", "scripts/migrate.sh", "up"])
                self.assertEqual(kwargs["env"]["SIERX_NETWORK_MODE"], "offline")
                self.assertNotIn("SIERX_DEPLOY_MANIFEST_URL", kwargs["env"])
                self.assertEqual(kwargs["env"]["GOOSE"], str(root / "bin/goose"))
                with self.assertRaises(ValueError): offline.run_operation(root, data, "db-reset")


class AssemblyTests(unittest.TestCase):
    def test_native_assembly_preserves_release_and_exports_ids_then_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            release = {"image": "example.test/sierx@sha256:" + "a" * 64, "revision": "b" * 40}
            source = {name: b"tracked fixture" for name in ("LICENSE", "NOTICE", "scripts/offline.py", "scripts/deploy.py", "scripts/db.sh", "scripts/migrate.sh", "migrations/0001.sql")}
            source["deploy/quadlet/sierx-postgres.container"] = ("Image=example.test/postgres@sha256:" + "c" * 64 + "\n").encode()
            blobs = {str(index): content for index, content in enumerate(source.values())}
            (parent / "release.json").write_text(json.dumps(release))
            (parent / "sbom.json").write_text(json.dumps({"bomFormat": "CycloneDX", "metadata": {"component": {"properties": [{"name": "vcs:commit", "value": release["revision"]}]}}}))
            calls = []
            def command(*args, **kwargs):
                calls.append(args)
                if args[:2] == ("git", "rev-parse"): return release["revision"]
                if args[:2] == ("git", "status"): return ""
                if args[:2] == ("git", "ls-files"):
                    return "\n".join("100644 " + str(index) + " 0\t" + name for index, name in enumerate(source))
                if args[:3] == ("podman", "image", "inspect"):
                    return json.dumps([{"Id": "d" * 64, "Os": "linux", "Architecture": "amd64", "Labels": {"org.opencontainers.image.revision": release["revision"]}}])
                if args[:2] == ("podman", "save"): Path(args[5]).write_bytes(b"archive")
                if args[:2] == ("podman", "create"): return "fixture"
                if args[:2] == ("podman", "cp"): Path(args[-1]).write_bytes(b"cli")
                return ""
            goose = b"verified migration tool"
            with mock.patch.object(offline, "native_arch", return_value="amd64"), mock.patch.object(offline, "command", side_effect=command), mock.patch.object(offline.subprocess, "check_output", side_effect=lambda args, **kw: blobs[args[-1]]), mock.patch.object(urllib.request, "urlopen", side_effect=[io.BytesIO(goose), io.BytesIO(b"MIT fixture")]), mock.patch.dict(offline.GOOSE, {"amd64": ("x86_64", hashlib.sha256(goose).hexdigest())}), contextlib.redirect_stdout(io.StringIO()):
                offline.prepare(parent / "release.json", "example.test/caddy@sha256:" + "e" * 64, parent / "bundle", parent / "sbom.json")
            root = parent / "bundle"
            expected = offline.digest(root / "bundle.lock.json")
            data = offline.verify(root, expected, "amd64")
            self.assertEqual(data["release"], release)
            self.assertEqual((root / "migrations/0001.sql").read_bytes(), source["migrations/0001.sql"])
            saves = [args for args in calls if args[:2] == ("podman", "save")]
            self.assertEqual(len(saves), 3)
            self.assertTrue(all(args[-1] == "sha256:" + "d" * 64 for args in saves))
            (root / "bin/goose").write_bytes(b"modified")
            with self.assertRaises(ValueError): offline.verify(root, expected, "amd64")


class OfflineGatewayTests(unittest.TestCase):
    def test_apply_uses_verified_local_ids_and_never_pulls(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            bundle, home = parent / "bundle", parent / "home"
            bundle.mkdir()
            data, _ = fixture(bundle)
            shutil.copytree(ROOT / "deploy", bundle / "deploy")
            config = home / ".config/sierx"
            (config / "tls").mkdir(parents=True)
            (config / "app.env").write_text("SIERX_LISTEN_ADDR=127.0.0.1:8080\nSIERX_BASE_URL=https://example.test:8443\nSIERX_AUTH_MODE=local\n")
            for name in ("server.crt", "server.key"):
                (config / "tls" / name).write_text("fixture")
            real_stat = Path.stat
            def private_stat(path, *args, **kwargs):
                result = real_stat(path, *args, **kwargs)
                if path in (config / "app.env", config / "tls/server.key"):
                    fields = list(result); fields[0] = 0o100600
                    return os.stat_result(fields)
                return result
            calls = []
            def run(*args):
                calls.append(args)
                if args[:3] == ("podman", "image", "inspect"):
                    return json.dumps([{"Labels": {"org.opencontainers.image.revision": data["release"]["revision"]}}])
                if args[:2] == ("podman", "create"): return "fixture"
                if args[:2] == ("podman", "cp"): (Path(args[-1]) / "hash.js").write_text("fixture")
                return ""
            environment = {"SIERX_NETWORK_MODE": "offline", "SIERX_TLS_MODE": "provided", "SIERX_DEPLOY_MANIFEST_FILE": str(bundle / "release.json"),
                           "SIERX_BASE_URL": "https://example.test:8443", "SIERX_APP_PORT": "8080", "SIERX_IMAGE_REPOSITORY": "example.test/sierx",
                           "SIERX_CADDY_IMAGE": data["images"]["caddy"]["source"]}
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.status = 200
            with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(deploy, "ROOT", bundle), mock.patch.object(Path, "home", return_value=home), mock.patch.object(Path, "stat", private_stat), mock.patch.object(importlib.util, "spec_from_file_location", return_value=mock.MagicMock()), mock.patch.object(importlib.util, "module_from_spec", return_value=offline), mock.patch.object(offline, "from_environment", return_value=(bundle, data)), mock.patch.object(offline, "inspect_image") as inspect, mock.patch.object(deploy, "run", side_effect=run), mock.patch.object(deploy.urllib.request, "urlopen", return_value=response) as network, contextlib.redirect_stdout(io.StringIO()):
                deploy.main("apply")
                self.assertEqual(inspect.call_count, 2)
                self.assertEqual(network.call_count, 1, "only the application's HTTPS health probe may use urllib")
                self.assertEqual(network.call_args.args[0], "https://example.test:8443/api/v1/healthz")
            self.assertFalse(any(args[:2] == ("podman", "pull") for args in calls))
            self.assertIn(("podman", "create", "--pull=never", data["images"]["app"]["id"]), calls)
            for role, name in (("app", "sierx"), ("caddy", "sierx-caddy")):
                unit = (home / ".config/containers/systemd" / (name + ".container")).read_text()
                self.assertIn("Image=" + data["images"][role]["id"], unit)
                self.assertIn("Pull=never", unit)

    def test_offline_refuses_online_manifest_and_public_certificate_issuance(self):
        with mock.patch.dict(os.environ, {"SIERX_NETWORK_MODE": "offline", "SIERX_DEPLOY_MANIFEST_URL": "https://example.test/release.json"}, clear=True), mock.patch.object(deploy.urllib.request, "urlopen") as network:
            with self.assertRaises(ValueError): deploy.read_release()
            with self.assertRaises(ValueError): deploy.gateway_config("example.test:8443", "8080", {})
            network.assert_not_called()

    def test_provided_certificate_retains_https_without_acme(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            tls = home / ".config/sierx/tls"
            tls.mkdir(parents=True)
            for name in ("server.crt", "server.key"):
                (tls / name).write_text("fixture")
                (tls / name).chmod(0o600)
            real_stat = Path.stat
            def private_stat(path, *args, **kwargs):
                result = real_stat(path, *args, **kwargs)
                if path == tls / "server.key":
                    fields = list(result); fields[0] = 0o100600
                    return os.stat_result(fields)
                return result
            with mock.patch.dict(os.environ, {"SIERX_NETWORK_MODE": "offline", "SIERX_TLS_MODE": "provided"}, clear=True), mock.patch.object(Path, "home", return_value=home), mock.patch.object(Path, "stat", private_stat):
                text = deploy.gateway_config("example.test:8443", "8080", {})
                self.assertIn("auto_https off", text)
                self.assertIn("ocsp_stapling off", text)
                self.assertIn("tls /etc/sierx/tls/server.crt /etc/sierx/tls/server.key", text)
                (tls / "server.key").unlink()
                with self.assertRaises(ValueError): deploy.gateway_config("example.test:8443", "8080", {})


if __name__ == "__main__":
    unittest.main()
