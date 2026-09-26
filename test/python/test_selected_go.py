import importlib.util
from pathlib import Path
import unittest
import io
import json
import os
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "selected_go", Path(__file__).parents[2] / "scripts/run-selected-go.py")
selected_go = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selected_go)


class SelectedTestTests(unittest.TestCase):
    def event(self, action, test="TestRequired", package="example.test/api"):
        return {"Action": action, "Test": test, "Package": package}

    def test_actual_execution_required(self):
        expected = "example.test/api:TestRequired"
        selected_go.check([self.event("run"), self.event("pass")], expected)
        for events in ([], [self.event("pass")], [self.event("run")],
                       [self.event("run"), self.event("skip")],
                       [self.event("run"), self.event("fail")],
                       [self.event("run", package="another/api"),
                        self.event("pass", package="another/api")],
                       [self.event("run"), self.event("skip", "TestRequired/child"),
                        self.event("pass")]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                selected_go.check(events, expected)

    def test_runner_rejects_successful_empty_or_skipped_process(self):
        for events in ([], [self.event("run"), self.event("skip")]):
            process = mock.MagicMock()
            process.__enter__.return_value = process
            process.stdout = io.StringIO("".join(json.dumps(e) + "\n" for e in events))
            process.wait.return_value = 0
            with mock.patch.dict(os.environ, {"SIERX_EXPECT_GO_TEST": "example.test/api:TestRequired"}), \
                    mock.patch.object(selected_go.subprocess, "Popen", return_value=process), \
                    mock.patch.object(selected_go.sys, "argv", ["runner", "./api"]):
                with self.assertRaises(ValueError):
                    selected_go.main()

    def test_runner_preserves_process_failure(self):
        process = mock.MagicMock()
        process.__enter__.return_value = process
        process.stdout = io.StringIO("")
        process.wait.return_value = 23
        with mock.patch.dict(os.environ, {"SIERX_EXPECT_GO_TEST": "example.test/api:TestRequired"}), \
                mock.patch.object(selected_go.subprocess, "Popen", return_value=process):
            self.assertEqual(selected_go.main(), 23)


if __name__ == "__main__":
    unittest.main()
