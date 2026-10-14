import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "artifact_acceptance", Path(__file__).parents[2] / "scripts/test-release-image.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class ArtifactFixtureTests(unittest.TestCase):
    def test_psql_required_before_any_container_work(self):
        with mock.patch.object(fixture.shutil, "which", return_value=None), mock.patch.object(fixture, "run") as run:
            with self.assertRaisesRegex(ValueError, "Install PostgreSQL 18"):
                fixture.require_psql()
            run.assert_not_called()

    def test_psql_version_is_explicit(self):
        with mock.patch.object(fixture.shutil, "which", return_value="/fixture/psql"), mock.patch.object(fixture, "run") as run:
            for version in ("psql (PostgreSQL) 16.15", "psql (PostgreSQL) 19.0", "unknown"):
                run.return_value = version
                with self.subTest(version=version), self.assertRaisesRegex(ValueError, "Select PostgreSQL 18"):
                    fixture.require_psql()
            run.return_value = "psql (PostgreSQL) 18.6 (Ubuntu)"
            fixture.require_psql()

    def test_final_tcp_and_mapped_sql_both_must_be_ready(self):
        database = "postgres://fixture-only@127.0.0.1:12345/sierx"
        tcp_probe = ("podman", "exec", "fixture-db", "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "sierx")
        sql_probe = ("psql", database, "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", "SELECT 1")
        with mock.patch.object(fixture, "run", side_effect=[subprocess.CalledProcessError(1, tcp_probe), "", subprocess.CalledProcessError(2, sql_probe), "1"]) as run, mock.patch.object(fixture.time, "sleep"):
            fixture.await_database("fixture-db", database)
            self.assertEqual(run.call_args_list, [mock.call(*tcp_probe), mock.call(*tcp_probe), mock.call(*sql_probe), mock.call(*sql_probe)])

    def test_readiness_timeout_does_not_reach_sql(self):
        with mock.patch.object(fixture, "run", side_effect=subprocess.CalledProcessError(1, ["podman", "exec"])) as run, mock.patch.object(fixture.time, "monotonic", side_effect=[0, 61]):
            with self.assertRaises(subprocess.CalledProcessError):
                fixture.await_database("fixture-db", "fixture-only")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], "podman")

    def test_command_diagnostics_omit_arguments_and_stderr(self):
        error = subprocess.CalledProcessError(2, ["/usr/bin/psql", "postgres://private:secret@host/db"], stderr="secret diagnostic")
        self.assertEqual(fixture.failure_detail(error), "psql failed with exit status 2")
        error.cmd = ["/private/path/custom-tool", "secret"]
        self.assertEqual(fixture.failure_detail(error), "operator-tool failed with exit status 2")

    def test_missing_client_removes_stale_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "dist/acceptance-amd64.json"
            evidence.parent.mkdir()
            evidence.write_text('{"status":"passed"}')
            environment = {"ARCH": "amd64", "SIERX_TEST_REVISION": "a" * 40, "SIERX_TEST_IMAGE": "example.test/sierx@sha256:" + "b" * 64}
            with mock.patch.object(fixture, "ROOT", root), mock.patch.dict(os.environ, environment), mock.patch.object(fixture.platform, "machine", return_value="x86_64"), mock.patch.object(fixture.platform, "system", return_value="Linux"), mock.patch.object(fixture, "require_psql", side_effect=ValueError("missing client")), mock.patch.object(fixture, "ensure_image") as images:
                with self.assertRaisesRegex(ValueError, "missing client"):
                    fixture.main()
                self.assertFalse(evidence.exists())
                images.assert_not_called()


if __name__ == "__main__":
    unittest.main()