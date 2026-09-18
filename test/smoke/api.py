"""Exercise real binaries and HTTP with curl against the caller's scratch DB."""
import json
import os
import pathlib
import socket
import subprocess
import tempfile
import time

with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
env = dict(os.environ, SIERX_AUTH_MODE="local", SIERX_BASE_URL=f"http://localhost:{port}",
           SIERX_LISTEN_ADDR=f"127.0.0.1:{port}", SIERX_SESSION_KEY="smoke-only-public-fixture-key-000000000000",
           SIERX_BOOTSTRAP_WORKSPACE_SLUG="smoke", SIERX_BOOTSTRAP_WORKSPACE_NAME="Smoke",
           SIERX_BOOTSTRAP_ADMIN_EMAIL="smoke@example.test", SIERX_BOOTSTRAP_ADMIN_NAME="Smoke",
           SIERX_BOOTSTRAP_ADMIN_PASSWORD="smoke-password-12345",
           SIERX_BOOTSTRAP_PROJECT_PREFIX="SMK", SIERX_BOOTSTRAP_PROJECT_NAME="Smoke")
subprocess.run(["bin/sierxctl", "bootstrap"], env=env, check=True, capture_output=True)
with tempfile.TemporaryDirectory(prefix="sierx-http-") as temporary:
    directory = pathlib.Path(temporary)
    with (directory / "server.log").open("w+") as log:
        process = subprocess.Popen(["bin/sierx"], env=env, stdout=log, stderr=log)
        def request(method, path, body=None, version=None):
            command = ["curl", "--silent", "--show-error", "--fail-with-body", "--max-time", "10",
                       "--cookie-jar", str(directory / "cookies"), "--cookie", str(directory / "cookies"),
                       "--request", method, env["SIERX_BASE_URL"] + "/api/v1" + path]
            if body is not None:
                command += ["--header", "Content-Type: application/json", "--data-binary", json.dumps(body)]
            if version is not None:
                command += ["--header", f'If-Match: "{version}"']
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(f"{method} {path}: {result.stderr} {result.stdout}")
            return json.loads(result.stdout) if result.stdout else None
        try:
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise AssertionError("API exited before readiness")
                try:
                    assert request("GET", "/healthz")["database"] == "reachable"
                    break
                except AssertionError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(.05)
            assert request("POST", "/auth/login", {"email": "smoke@example.test", "password": "smoke-password-12345"})["authenticated"]
            me = request("GET", "/me")
            assert request("PATCH", "/me", {"theme": "dark", "reduced_motion": True})["theme"] == "dark"
            assert request("GET", "/projects")["data"][0]["key_prefix"] == "SMK"
            assert request("GET", "/projects/SMK/config")["version"] == 1
            first = request("POST", "/items", {"project": "SMK", "type": "story", "title": "Curl item"})
            parent = request("POST", "/items", {"project": "SMK", "type": "epic", "title": "Curl parent"})
            key = first["key"]
            assert request("POST", f"/items/{key}/transition", {"to_status": "doing", "fields": {"assignee": me["id"]}}, 1)["version"] == 2
            assert request("POST", f"/items/{key}/move", {"parent": parent["key"]}, 2)["version"] == 3
            link = request("POST", f"/items/{key}/links", {"to": parent["key"], "kind": "relates"}, 3)
            assert request("GET", f"/items/{key}/links")["data"][0]["id"] == link["id"]
            comment = request("POST", "/comments", {"item": key, "body": "**Raw Markdown**"}, 4)
            assert request("GET", "/comments?item=" + key)["data"][0]["body"] == "**Raw Markdown**"
            assert request("PATCH", f"/items/{key}", {"title": "Curl edited"}, 5)["version"] == 6
            assert request("GET", f'/items/{parent["key"]}/children?fields=key')["data"][0]["key"] == key
            assert request("GET", f'/items/{parent["key"]}/descendants?fields=key&depth=2')["data"][0]["key"] == key
            assert request("GET", f'/items/{parent["key"]}/rollup')["descendant_count"] == 1
            assert request("GET", "/items?fields=key&q=project%3DSMK")["data"]
            assert request("GET", "/sxq/complete?partial=sta")["suggestions"]
            view = request("POST", "/views", {"name": "Smoke", "query": "project=SMK", "layout": "list"})
            assert request("GET", "/views")["data"][0]["id"] == view["id"]
            assert request("GET", f"/items/{key}/history")["data"][0]["kind"] == "field_changed"
            assert request("GET", "/changes?since_seq=0")["next_seq"] >= 8
            request("DELETE", f'/comments/{comment["id"]}', version=6)
            request("DELETE", f'/links/{link["id"]}', version=7)
            request("DELETE", f"/items/{key}", version=8)
            assert request("GET", f"/items/{key}")["deleted_at"]
            request("POST", "/auth/logout")
            print("smoke-api: real CLI bootstrap and curl workflow PASS")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
