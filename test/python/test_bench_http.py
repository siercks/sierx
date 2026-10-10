import importlib.util
from pathlib import Path
import unittest

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


if __name__ == "__main__":
    unittest.main()
