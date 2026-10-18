import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("bench_http", ROOT / "scripts" / "bench-http.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class HttpBenchmarkTests(unittest.TestCase):
    def test_nearest_rank_percentiles(self):
        values = list(range(1, 101))
        self.assertEqual(bench.percentile(values, .50), 50)
        self.assertEqual(bench.percentile(values, .95), 95)
        self.assertEqual(bench.percentile(values, 1), 100)

    def test_empty_and_invalid_percentiles_fail(self):
        for values, fraction in (([], .95), ([1], 0), ([1], 1.1)):
            with self.subTest(values=values, fraction=fraction), self.assertRaises(ValueError):
                bench.percentile(values, fraction)

    def test_target_requires_origin_and_https_off_loopback(self):
        self.assertEqual(bench.origin("http://127.0.0.1:8080"), "http://127.0.0.1:8080")
        for value in ("http://example.test", "https://user:pass@example.test", "https://example.test/app"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bench.origin(value)

    def test_read_only_report_runs_all_scenarios_on_10k_fixture(self):
        class FakeClient:
            def __init__(self, base):
                self.logged_out = False

            def post(self, path, body):
                if path.endswith("/logout"):
                    self.logged_out = True
                return 200

            def get(self, path):
                if path == "/api/v1/items/SRX-42":
                    body = json.dumps({"project": {"key_prefix": "SRX"}}).encode()
                elif path.startswith("/api/v1/items?"):
                    query = parse_qs(urlsplit(path).query)
                    fields=set(query.get('fields',[''])[0].split(','))
                    assert fields and fields <= {'key','title','status','type','assignee','points','due_date'}
                    if "project" in query and "q" not in query:
                        cursor = int(query.get("cursor", ["0"])[0])
                        next_cursor = str(cursor + 1) if cursor < 99 else None
                        body = json.dumps({"data": [None] * 100,
                                           "next_cursor": next_cursor}).encode()
                    else:
                        body = b'{"data":[],"next_cursor":null}'
                else:
                    body = b'{}'
                return 1.25, len(body), body

        environment = {
            "SIERX_BENCH_URL": "http://127.0.0.1:9000",
            "SIERX_BENCH_ITEM": "SRX-42",
            "SIERX_BENCH_EMAIL": "operator@example.invalid",
            "SIERX_BENCH_PASSWORD": "private-test-password",
        }
        with mock.patch.dict("os.environ", environment), mock.patch.object(bench, "Client", FakeClient):
            conditioned=[]
            report = bench.run(SimpleNamespace(warmups=1, samples=2,workload_warmup=lambda client,scenarios:conditioned.append(set(scenarios))))
        self.assertEqual(conditioned,[set(bench.LIMITS_MS)])
        self.assertEqual(report["active_fixture_items"], 10000)
        self.assertEqual(set(report["results"]), set(bench.LIMITS_MS))
        self.assertTrue(all(item["samples"] == 2 for item in report["results"].values()))
        self.assertNotIn("private-test-password", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
