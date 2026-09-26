"""Native acceptance in a fresh network namespace and disposable image store.

Run as root through `unshare --net`; never uses the operator's container store,
user services, database, or credentials. Host reboot remains a separate test.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
import offline


def run(*args, **kwargs):
    try:
        return subprocess.check_output(args, stderr=subprocess.PIPE, text=True, **kwargs).strip()
    except subprocess.CalledProcessError as error:
        # Keep potentially sensitive subprocess output out of CI logs.
        diagnostic = Path(os.environ["SIERX_OFFLINE_REPORT"] + ".private.log")
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(diagnostic, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
            stream.write(error.stderr or "")
        print("offline acceptance: subprocess failed (" + Path(args[0]).name + "); private diagnostic saved", file=sys.stderr)
        raise


def main():
    report = Path(os.environ["SIERX_OFFLINE_REPORT"]).absolute()
    report.unlink(missing_ok=True)
    if os.geteuid() != 0:
        raise ValueError("Run in a disposable root network namespace using sudo unshare --net")
    interfaces = json.loads(run("ip", "-j", "link", "show"))
    if {entry["ifname"] for entry in interfaces} != {"lo"}:
        raise ValueError("Refusing acceptance outside a network namespace containing only loopback")
    run("ip", "link", "set", "lo", "up")
    root, data = offline.from_environment()
    with tempfile.TemporaryDirectory(prefix="sierx-offline-acceptance-") as temporary:
        scratch = Path(temporary)
        podman = ["podman", "--root", str(scratch / "store"), "--runroot", str(scratch / "run"),
                  "--storage-driver=vfs", "--cgroup-manager=cgroupfs", "--events-backend=file"]
        def container(*args):
            return run(*podman, *args)
        originals = offline.command
        def isolated(*args, **kwargs):
            if args[0] != "podman":
                raise ValueError("Unexpected bundle import command")
            return container(*args[1:])
        password = secrets.token_hex(24)
        email = "offline@example.test"
        base = "https://localhost:18443"
        database = "postgres://sierx:" + password + "@127.0.0.1:15432/sierx?sslmode=disable"
        environment = {**os.environ, "DATABASE_URL": database, "SIERX_ENV": "staging",
                       "SIERX_BASE_URL": base, "SIERX_LISTEN_ADDR": "127.0.0.1:18081",
                       "SIERX_AUTH_MODE": "local", "SIERX_SESSION_KEY": __import__("base64").b64encode(secrets.token_bytes(32)).decode(),
                       "SIERX_NETWORK_MODE": "offline", "SIERX_TLS_MODE": "provided",
                       "SIERX_BOOTSTRAP_ADMIN_EMAIL": email, "SIERX_BOOTSTRAP_ADMIN_PASSWORD": password,
                       "SIERX_BOOTSTRAP_ADMIN_NAME": "Offline acceptance",
                       "SIERX_BOOTSTRAP_WORKSPACE_SLUG": "offline", "SIERX_BOOTSTRAP_WORKSPACE_NAME": "Offline acceptance",
                       "SIERX_BOOTSTRAP_PROJECT_PREFIX": "OFF", "SIERX_BOOTSTRAP_PROJECT_NAME": "Offline acceptance"}
        try:
            offline.command = isolated
            offline.run_operation(root, data, "import")
            offline.command = originals
            common = ["--pull=never", "--network=host", "--cgroups=disabled", "--security-opt=label=disable"]
            container("run", "-d", "--name", "db", *common,
                      "-e", "POSTGRES_USER=sierx", "-e", "POSTGRES_PASSWORD=" + password, "-e", "POSTGRES_DB=sierx",
                      "-e", "POSTGRES_INITDB_ARGS=--locale=C --encoding=UTF8",
                      "-v", "offline-data:/var/lib/postgresql", data["images"]["postgres"]["id"], "postgres", "-p", "15432",
                      "-c", "shared_preload_libraries=pg_stat_statements")
            for attempt in range(60):
                try:
                    container("exec", "db", "pg_isready", "-q", "-p", "15432", "-U", "sierx", "-d", "sierx")
                    break
                except subprocess.CalledProcessError:
                    if attempt == 59: raise
                    time.sleep(1)
            run("bash", "scripts/migrate.sh", "up", cwd=root, env=environment)
            run(str(root / "bin/sierxctl"), "bootstrap", cwd=root, env=environment)
            # Generate an ephemeral site certificate; no public CA or DNS needed.
            tls = scratch / "tls"
            tls.mkdir()
            run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-keyout", str(tls / "server.key"), "-out", str(tls / "server.crt"), "-subj", "/CN=localhost",
                "-addext", "subjectAltName=DNS:localhost", "-addext", "basicConstraints=critical,CA:TRUE")
            (tls / "server.key").chmod(0o600)
            environment["SSL_CERT_FILE"] = str(tls / "server.crt")
            envfile = scratch / "app.env"
            envfile.write_text("\n".join(key + "=" + environment[key] for key in
                                         ("DATABASE_URL", "SIERX_ENV", "SIERX_BASE_URL", "SIERX_LISTEN_ADDR", "SIERX_AUTH_MODE", "SIERX_SESSION_KEY")) + "\n")
            envfile.chmod(0o600)
            app = data["images"]["app"]["id"]
            container("create", "--name", "assets", "--pull=never", app)
            assets = scratch / "assets"
            assets.mkdir()
            container("cp", "assets:/srv/sierx/assets/.", str(assets))
            container("rm", "assets")
            # Exercise the actual gateway renderer with an isolated home.
            import deploy
            home = scratch / "home"
            (home / ".config/sierx").mkdir(parents=True)
            shutil.copytree(tls, home / ".config/sierx/tls")
            saved = dict(os.environ)
            os.environ.update(environment)
            os.environ["HOME"] = str(home)
            try:
                caddyfile = scratch / "Caddyfile"
                caddyfile.write_text(deploy.gateway_config("localhost:18443", "18081", {"SIERX_AUTH_MODE": "local"}))
            finally:
                os.environ.clear(); os.environ.update(saved)
            container("run", "-d", "--name", "app", *common, "--read-only", "--env-file", str(envfile), app)
            container("run", "-d", "--name", "gateway", *common,
                      "-v", str(caddyfile) + ":/etc/caddy/Caddyfile:ro", "-v", str(tls) + ":/etc/sierx/tls:ro",
                      "-v", str(assets) + ":/srv/sierx/assets:ro", data["images"]["caddy"]["id"])
            import ssl
            import urllib.request
            import http.cookiejar
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),
                       urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(tls / "server.crt"))))
            def request(path, payload=None):
                data_bytes = json.dumps(payload).encode() if payload is not None else None
                req = urllib.request.Request(base + path, data=data_bytes, headers={"Content-Type": "application/json", "Origin": base})
                with opener.open(req, timeout=5) as response:
                    return json.loads(response.read() or b"{}")
            for attempt in range(60):
                try:
                    request("/api/v1/healthz")
                    break
                except OSError:
                    if attempt == 59: raise
                    time.sleep(1)
            request("/api/v1/auth/login", {"email": email, "password": password})
            # Use the same real API workflow as the canonical artifact test.
            request("/api/v1/items", {"project": "OFF", "title": "Offline acceptance", "type": "story"})
            smoke_env = {**environment, "SIERX_SMOKE_URL": base, "SIERX_SMOKE_ITEM": "OFF-1", "SIERX_SMOKE_EMAIL": email, "SIERX_SMOKE_PASSWORD": password}
            before = run("python3", "-B", "scripts/release-smoke.py", cwd=root, env=smoke_env)
            container("restart", "db", "app", "gateway")
            for attempt in range(60):
                try:
                    after = run("python3", "-B", "scripts/release-smoke.py", cwd=root, env=smoke_env)
                    break
                except subprocess.CalledProcessError:
                    if attempt == 59: raise
                    time.sleep(1)
            if before != after or "item fingerprint" not in before:
                raise ValueError("Item fingerprint changed after database/app/gateway restart")
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"arch": data["arch"], "release": data["release"],
                                         "bundle_sha256": os.environ["SIERX_OFFLINE_SHA256"],
                                         "external_interfaces": [], "result": "passed",
                                         "checks": ["empty-store-import", "migrations", "bootstrap", "provided-tls", "https-smoke", "database-app-gateway-restart-persistence"]}, indent=2) + "\n")
            print("offline acceptance: verified import, HTTPS workflow and full service restart passed without external networking")
            Path(os.environ["SIERX_OFFLINE_REPORT"] + ".private.log").unlink(missing_ok=True)
        finally:
            offline.command = originals
            subprocess.run([*podman, "rm", "-af"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([*podman, "unmount", "--all", "--force"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit("offline acceptance: " + (str(error) if isinstance(error, ValueError) else "failed; no passing evidence written"))
