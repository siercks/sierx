"""Deployment boundaries for a local tunnel origin and reviewed artifacts."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import URLError

spec = importlib.util.spec_from_file_location("deploy", Path(__file__).parents[2] / "scripts/deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class ManifestTests(unittest.TestCase):
    def test_local_artifact_uses_same_validation_without_network(self):
        release = {"image": "example.test/sierx@sha256:" + "a" * 64, "revision": "b" * 40}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release.json"
            path.write_text(json.dumps(release))
            environment = {"SIERX_DEPLOY_MANIFEST_FILE": str(path), "SIERX_IMAGE_REPOSITORY": "example.test/sierx"}
            with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(deploy.urllib.request, "urlopen") as network:
                self.assertEqual(deploy.read_release(), release)
                network.assert_not_called()
                for content in ('{}', json.dumps({**release, "image": "example.test/sierx:latest"}), ' ' * 8193):
                    path.write_text(content)
                    with self.assertRaises(ValueError):
                        deploy.read_release()

    def test_ambiguous_missing_and_unsafe_sources_fail(self):
        for environment in ({}, {"SIERX_DEPLOY_MANIFEST_URL": "https://example.test/release.json", "SIERX_DEPLOY_MANIFEST_FILE": "/tmp/release.json"}, {"SIERX_DEPLOY_MANIFEST_FILE": "relative.json"}, {"SIERX_DEPLOY_MANIFEST_URL": "http://example.test/release.json"}):
            with self.subTest(environment=environment), mock.patch.dict(os.environ, environment, clear=True), self.assertRaises(ValueError):
                deploy.read_release()


class GatewayTests(unittest.TestCase):
    def test_loopback_tunnel_requires_local_auth_and_distinct_port(self):
        environment = {"SIERX_GATEWAY_MODE": "tunnel", "SIERX_GATEWAY_PORT": "18080"}
        with mock.patch.dict(os.environ, environment, clear=True):
            text = deploy.gateway_config("example.test", "8080", {"SIERX_AUTH_MODE": "local"})
            self.assertIn("http://example.test:18080", text)
            self.assertIn("bind 127.0.0.1", text)
            self.assertIn("auto_https off", text)
            for port in ("8080", "08080", "443", "65536", "18080\n}"):
                with mock.patch.dict(os.environ, {"SIERX_GATEWAY_PORT": port}), self.assertRaises(ValueError):
                    deploy.gateway_config("example.test", "8080", {"SIERX_AUTH_MODE": "local"})
            for mode in ("proxy", "", None):
                with self.assertRaises(ValueError):
                    deploy.gateway_config("example.test", "8080", {"SIERX_AUTH_MODE": mode})
            with self.assertRaises(ValueError):
                deploy.gateway_config("example.test:8443", "8080", {"SIERX_AUTH_MODE": "local"})
        with mock.patch.dict(os.environ, {"SIERX_GATEWAY_MODE": "typo"}, clear=True), self.assertRaises(ValueError):
            deploy.gateway_config("example.test", "8080", {})
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIn("h1 h2 h3", deploy.gateway_config("example.test", "8080", {}))

    def test_same_revision_gateway_change_applies_and_failed_health_rolls_back(self):
        for healthy in (False, True):
            with self.subTest(healthy=healthy), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                config = home / ".config/sierx"
                units = home / ".config/containers/systemd"
                state = home / ".local/share/sierx"
                for directory in (config, units, state):
                    directory.mkdir(parents=True, exist_ok=True)
                app = config / "app.env"
                app.write_text("SIERX_LISTEN_ADDR=127.0.0.1:8080\nSIERX_BASE_URL=https://example.test\nSIERX_AUTH_MODE=local\n")
                release = {"image": "example.test/sierx@sha256:" + "a" * 64, "revision": "b" * 40}
                (state / "current.json").write_text(json.dumps(release))
                values = {"SIERX_IMAGE": release["image"], "SIERX_CADDY_IMAGE": "example.test/caddy@sha256:" + "c" * 64}
                for name in ("sierx", "sierx-caddy"):
                    (units / (name + ".container")).write_text(deploy.render("deploy/quadlet/" + name + ".container.tmpl", values))
                old_gateway = deploy.render("deploy/Caddyfile.tmpl", {"SIERX_HOST": "example.test", "SIERX_APP_PORT": "8080"})
                (config / "Caddyfile").write_text(old_gateway)
                real_stat = Path.stat
                def private_stat(path, *args, **kwargs):
                    result = real_stat(path, *args, **kwargs)
                    if path == app:
                        fields = list(result); fields[0] = 0o100600
                        return os.stat_result(fields)
                    return result
                commands = []
                def run(*args):
                    commands.append(args)
                    if args[:3] == ("podman", "image", "inspect"):
                        return json.dumps([{"Labels": {"org.opencontainers.image.revision": release["revision"]}}])
                    if args[:2] == ("podman", "create"):
                        return "fixture"
                    if args[:2] == ("podman", "cp"):
                        (Path(args[-1]) / "fixture.js").write_text("fixture")
                    return ""
                response = mock.MagicMock()
                response.__enter__.return_value = response
                response.status = 200
                environment = {"SIERX_BASE_URL": "https://example.test", "SIERX_APP_PORT": "8080", "SIERX_CADDY_IMAGE": values["SIERX_CADDY_IMAGE"], "SIERX_GATEWAY_MODE": "tunnel", "SIERX_GATEWAY_PORT": "18080"}
                with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(Path, "home", return_value=home), mock.patch.object(Path, "stat", private_stat), mock.patch.object(deploy, "read_release", return_value=release), mock.patch.object(deploy, "run", side_effect=run), mock.patch.object(deploy.time, "sleep"), mock.patch.object(deploy.urllib.request, "urlopen", side_effect=None if healthy else URLError("offline"), return_value=response), contextlib.redirect_stdout(io.StringIO()):
                    if healthy:
                        deploy.main("apply")
                        self.assertIn("bind 127.0.0.1", (config / "Caddyfile").read_text())
                        count = len(commands)
                        deploy.main("apply")
                        self.assertEqual(len(commands), count, "identical installed configuration should be a no-op")
                    else:
                        with self.assertRaises(URLError):
                            deploy.main("apply")
                        self.assertEqual((config / "Caddyfile").read_text(), old_gateway)
                self.assertIn(("systemctl", "--user", "restart", "sierx.service", "sierx-caddy.service"), commands)
                self.assertEqual(json.loads((state / "current.json").read_text()), release)


if __name__ == "__main__":
    unittest.main()
