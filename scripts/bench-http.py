"""Measure authenticated, read-only HTTP latency on an explicit Sierx target."""
import argparse
import http.cookiejar
import ipaddress
import json
import math
import os
import platform
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

LIMITS_MS = {
    "board_page_100": 150,
    "item_detail_and_history": 100,
    "sxq_indexed_project": 200,
    "item_rollup": 50,
    "changes_50": 80,
    "sxq_full_text": 300,
}
LIMITS_BYTES = {"changes_50": 20 * 1024}


def percentile(values, fraction):
    if not values or not 0 < fraction <= 1:
        raise ValueError("percentile requires samples and a fraction in (0, 1]")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def origin(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("SIERX_BENCH_URL must be an HTTP(S) origin without credentials or a path")
    try:
        address = socket.gethostbyname(parsed.hostname)
    except OSError as error:
        raise ValueError("benchmark target hostname did not resolve") from error
    if parsed.scheme != "https" and not ipaddress.ip_address(address).is_loopback:
        raise ValueError("HTTP is allowed only for a loopback target; use HTTPS otherwise")
    return value.rstrip("/")


class Client:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def get(self, path):
        request = urllib.request.Request(self.base + path, headers={"Accept": "application/json"})
        start = time.perf_counter_ns()
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            raise ValueError("benchmark request failed with HTTP " + str(error.code)) from None
        except urllib.error.URLError:
            raise ValueError("benchmark request failed; check target availability and certificate trust") from None
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        if status != 200:
            raise ValueError("benchmark request returned HTTP " + str(status))
        return elapsed, len(body), body

    def post(self, path, body):
        data = json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json", "Origin": self.base})
        try:
            with self.opener.open(request, timeout=30) as response:
                response.read()
                return response.status
        except (urllib.error.HTTPError, urllib.error.URLError):
            return None


def run(args):
    base = origin(os.environ["SIERX_BENCH_URL"])
    key = os.environ["SIERX_BENCH_ITEM"]
    if not re.fullmatch(r"[A-Z][A-Z0-9]*-[1-9][0-9]*", key):
        raise ValueError("SIERX_BENCH_ITEM must name an existing item")
    client = Client(base)
    status = client.post("/api/v1/auth/login", {
        "email": os.environ["SIERX_BENCH_EMAIL"],
        "password": os.environ["SIERX_BENCH_PASSWORD"],
        "code": os.environ.get("SIERX_BENCH_CODE", "")})
    if status != 200:
        raise ValueError("benchmark login failed; check private credentials and target")
    try:
        _, _, raw = client.get("/api/v1/items/" + key)
        item = json.loads(raw)
        prefix = item["project"]["key_prefix"]
        count = 0
        cursor = None
        for _ in range(101):
            query = {"project": prefix, "limit": "100", "fields": "key"}
            if cursor:
                query["cursor"] = cursor
            _, _, page_raw = client.get("/api/v1/items?" + urllib.parse.urlencode(query))
            page = json.loads(page_raw)
            count += len(page["data"])
            cursor = page.get("next_cursor")
            if not cursor:
                break
        if count != 10000:
            raise ValueError(f"selected project has {count} active items; performance fixture must contain exactly 10,000")
        q_project = urllib.parse.quote("project = " + prefix, safe="")
        q_text = urllib.parse.quote('text ~ "rollup cursor"', safe="")
        scenarios = {
            "board_page_100": ["/api/v1/items?project=" + prefix + "&limit=100&fields=key,title,status,type,assignee,points,due_date"],
            "item_detail_and_history": ["/api/v1/items/" + key,
                                        "/api/v1/items/" + key + "/history?limit=50"],
            "sxq_indexed_project": ["/api/v1/items?q=" + q_project + "&limit=100&fields=key,title,status,type,assignee,points,due_date"],
            "item_rollup": ["/api/v1/items/" + key + "/rollup"],
            "changes_50": ["/api/v1/changes?since_seq=0&limit=50"],
            "sxq_full_text": ["/api/v1/items?q=" + q_text + "&limit=100&fields=key,title,status,type,assignee,points,due_date"],
        }
        if getattr(args,"workload_warmup",None):
            args.workload_warmup(client,scenarios)
        results = {}
        for name, paths in scenarios.items():
            samples, response_bytes = [], []
            for iteration in range(args.warmups + args.samples):
                elapsed, size = 0.0, 0
                for path in paths:
                    duration, body_size, _ = client.get(path)
                    elapsed += duration
                    size += body_size
                if iteration >= args.warmups:
                    samples.append(elapsed)
                    response_bytes.append(size)
                    if getattr(args,"sample_observer",None):
                        args.sample_observer()
            p95 = percentile(samples, .95)
            results[name] = {
                "samples": len(samples), "p50_ms": round(percentile(samples, .50), 3),
                "p95_ms": round(p95, 3), "max_ms": round(max(samples), 3),
                "response_bytes_last_sample": response_bytes[-1],
                "limit_ms": LIMITS_MS[name], "within_limit": p95 <= LIMITS_MS[name],
            }
            if name in LIMITS_BYTES:
                results[name]["limit_bytes"] = LIMITS_BYTES[name]
                results[name]["within_byte_limit"] = response_bytes[-1] < LIMITS_BYTES[name]
        report = {
            "measurement": "client round-trip including HTTP/TLS and network",
            "target_label": os.environ.get("SIERX_BENCH_TARGET_LABEL", "unlabeled"),
            "hardware": hardware(), "warmups_per_scenario": args.warmups,
            "measured_samples_per_scenario": args.samples,
            "active_fixture_items": count, "results": results,
            "note": "Use a direct local origin to compare with SPEC server budgets; public tunnel timings include network/TLS overhead.",
        }
        return report
    finally:
        client.post("/api/v1/auth/logout", {})


def hardware():
    model = platform.processor() or "unspecified"
    memory = None
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as stream:
            for line in stream:
                if line.lower().startswith(("model name", "hardware")):
                    model = line.split(":", 1)[-1].strip()
                    break
        with open("/proc/meminfo", encoding="ascii") as stream:
            first = stream.readline()
        match = re.search(r"\d+", first)
        memory = int(match.group()) * 1024 if match else None
    except OSError:
        pass
    return {"os": platform.platform(), "architecture": platform.machine(),
            "cpu_model": model, "memory_bytes": memory}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=500)
    parser.add_argument("--warmups", type=int, default=20)
    args = parser.parse_args()
    if args.samples < 500 or args.warmups < 1:
        raise ValueError("Use at least 500 measured samples and one warmup per scenario")
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, TypeError, json.JSONDecodeError) as error:
        sys.exit("bench-http: " + str(error))
