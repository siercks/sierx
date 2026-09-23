"""Native Podman artifact acceptance; only newly created disposable containers.

HTTP is confined to loopback fixtures. This is not the separate HTTPS/Caddy or
physical recovery acceptance, and never consumes operator database credentials.
"""
import hashlib
import http.cookies
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, **kwargs).strip()


def await_ready(check):
    deadline = time.monotonic() + 60
    while True:
        try:
            return check()
        except (OSError, subprocess.CalledProcessError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.5)


def main():
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if arch != os.environ.get("ARCH") or platform.system() != "Linux":
        raise ValueError("Image acceptance requires the matching native Linux architecture")
    revision = os.environ["SIERX_TEST_REVISION"]
    image = os.environ["SIERX_TEST_IMAGE"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision) or not re.fullmatch(r"[^\s@]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("Use an exact revision and immutable image digest")
    evidence = ROOT / f"dist/acceptance-{arch}.json"
    evidence.unlink(missing_ok=True)  # A failed rerun must not leave old acceptance.
    run("podman", "pull", image)
    metadata = json.loads(run("podman", "image", "inspect", image))[0]
    if (metadata["Architecture"] != arch or metadata["Os"] != "linux"
            or metadata["Config"]["User"] != "65532:65532"
            or metadata.get("Labels", {}).get("org.opencontainers.image.revision") != revision):
        raise ValueError("Candidate architecture, runtime user or revision differs")
    pg_image = next(line.split("=", 1)[1] for line in
                    (ROOT / "deploy/quadlet/sierx-postgres.container").read_text().splitlines()
                    if line.startswith("Image="))
    run("podman", "pull", pg_image)
    pod = "sierx-artifact-" + uuid.uuid4().hex[:12]
    app, db = pod + "-app", pod + "-db"
    with tempfile.TemporaryDirectory(prefix="sierx-artifact-") as temporary:
        scratch = Path(temporary)
        created = False
        try:
            run("podman", "pod", "create", "--name", pod, "-p", "127.0.0.1::8080", "-p", "127.0.0.1::5432")
            created = True
            run("podman", "run", "-d", "--pod", pod, "--name", db,
                "--tmpfs", "/var/lib/postgresql", "-e", "POSTGRES_PASSWORD=artifact-only-password",
                "-e", "POSTGRES_DB=sierx", "-e", "POSTGRES_INITDB_ARGS=--locale=C --encoding=UTF8", pg_image)
            await_ready(lambda: run("podman", "exec", db, "pg_isready", "-U", "postgres", "-d", "sierx"))
            infra = json.loads(run("podman", "pod", "inspect", pod))["InfraContainerID"]
            ports = json.loads(run("podman", "inspect", infra))[0]["NetworkSettings"]["Ports"]
            app_port = ports["8080/tcp"][0]["HostPort"]
            pg_port = ports["5432/tcp"][0]["HostPort"]
            origin = "http://127.0.0.1:" + app_port
            goose = os.environ["GOOSE"]
            run(goose, "-dir", str(ROOT / "migrations"), "postgres",
                "postgres://postgres:artifact-only-password@127.0.0.1:" + pg_port + "/sierx?sslmode=disable", "up")
            env = scratch / "app.env"
            env.write_text("\n".join([
                "DATABASE_URL=postgres://postgres:artifact-only-password@127.0.0.1:5432/sierx?sslmode=disable",
                "SIERX_AUTH_MODE=local", "SIERX_BASE_URL=" + origin,
                "SIERX_LISTEN_ADDR=0.0.0.0:8080", "SIERX_SESSION_KEY=artifact-only-session-key-0000000000000000",
                "SIERX_BOOTSTRAP_WORKSPACE_SLUG=artifact", "SIERX_BOOTSTRAP_WORKSPACE_NAME=Artifact",
                "SIERX_BOOTSTRAP_ADMIN_EMAIL=artifact@example.test", "SIERX_BOOTSTRAP_ADMIN_NAME=Artifact",
                "SIERX_BOOTSTRAP_ADMIN_PASSWORD=artifact-only-password",
                "SIERX_BOOTSTRAP_PROJECT_PREFIX=SRX", "SIERX_BOOTSTRAP_PROJECT_NAME=Artifact"]) + "\n")
            env.chmod(0o600)
            options = ["--pod", pod, "--read-only", "--security-opt", "no-new-privileges", "--env-file", str(env)]
            run("podman", "run", "--rm", *options, "--entrypoint", "/usr/local/bin/sierxctl", image, "bootstrap")
            run("podman", "run", "-d", "--name", app, *options, image)
            run("podman", "exec", app, "/usr/local/bin/sierxctl", "partitions", "ensure", "--months-ahead", "1")
            # A shell-free runtime must not acquire operator tooling accidentally.
            for shell in ("/bin/sh", "/bin/bash"):
                result = subprocess.run(["podman", "exec", app, shell, "-c", "true"], capture_output=True)
                if result.returncode == 0:
                    raise ValueError("Unexpected shell in application image")
            cookie = ""
            def request(path, body=None, version=None):
                nonlocal cookie
                headers = {"Content-Type": "application/json", "Origin": origin}
                if cookie:
                    headers["Cookie"] = cookie
                if version is not None:
                    headers["If-Match"] = '"' + str(version) + '"'
                req = urllib.request.Request(origin + path, headers=headers,
                      data=None if body is None else json.dumps(body).encode(),
                      method="PATCH" if version is not None else None)
                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.headers.get("Set-Cookie"):
                        parsed = http.cookies.SimpleCookie(response.headers["Set-Cookie"])
                        session = parsed.get("__Host-sierx_session")
                        if not session or not session["secure"] or not session["httponly"]:
                            raise ValueError("Session cookie flags missing")
                        # Explicit test-only loopback cookie handling; real deployments use HTTPS.
                        cookie = session.key + "=" + session.value
                    return response.read()
            await_ready(lambda: request("/api/v1/healthz"))
            def login():
                request("/api/v1/auth/login", {"email": "artifact@example.test", "password": "artifact-only-password"})
            login()
            item = json.loads(request("/api/v1/items", {"project": "SRX", "type": "story", "title": "Artifact persistence"}))
            item = json.loads(request("/api/v1/items/" + item["key"], {"body": "Written by the shipped image"}, item["version"]))
            def fingerprint():
                current = json.loads(request("/api/v1/items/" + item["key"]))
                return hashlib.sha256(json.dumps({key: current[key] for key in
                    ("id", "key", "title", "body", "version", "change_seq")}, sort_keys=True).encode()).hexdigest()
            before = fingerprint()
            for path in ("/", "/" + item["key"]):
                if b'id="sierx-state"' not in request(path):
                    raise ValueError("Shipped frontend initial state missing")
            run("podman", "stop", "--time", "20", app)
            stopped = json.loads(run("podman", "inspect", app))[0]["State"]
            if stopped["ExitCode"] != 0 or stopped.get("OOMKilled"):
                raise ValueError("Application did not stop gracefully")
            run("podman", "start", app)
            await_ready(lambda: request("/api/v1/healthz"))
            login()
            if fingerprint() != before:
                raise ValueError("Restart changed the persistent item")
            evidence.parent.mkdir(exist_ok=True)
            evidence.write_text(json.dumps({"image": image, "revision": revision,
                "platform": "linux/" + arch, "status": "passed", "checks": ["image-policy", "bootstrap",
                "partitions", "http-write", "deep-link", "graceful-stop", "restart-persistence"]}, indent=2) + "\n")
            print("release-image acceptance: " + arch + " exact digest passed")
        finally:
            if created:
                subprocess.run(["podman", "pod", "rm", "-f", pod], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError):
        sys.exit("release-image acceptance failed; no acceptance evidence issued (fixture logs remain private)")
