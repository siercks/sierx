"""Operator-run, pull-based deployment. No source builds or incoming webhook."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Every shipped unit has a concrete installer. Keep this inventory exhaustive.
UNIT_INSTALLERS = {
    "sierx-postgres.container": "db.sh up",
    "sierx.container.tmpl": "apply",
    "sierx-caddy.container.tmpl": "apply",
    "sierx-pull.service.tmpl": "install-timer",
    "sierx-pull.timer": "install-timer",
    "sierx-backup.service.tmpl": "install-backup-timer",
    "sierx-backup.timer": "install-backup-timer",
    "sierx-maintenance.service": "install-maintenance-timer",
    "sierx-maintenance.timer": "install-maintenance-timer",
    "sierx-restoretest.service.tmpl": "install-restore-timer",
    "sierx-restoretest.timer": "install-restore-timer",
}
TIMERS = {
    "install-timer": "sierx-pull",
    "install-backup-timer": "sierx-backup",
    "install-maintenance-timer": "sierx-maintenance",
    "install-restore-timer": "sierx-restoretest",
}


def unit_inventory():
    actual = {p.name for p in (ROOT / "deploy/quadlet").iterdir() if p.is_file()}
    if actual != set(UNIT_INSTALLERS):
        raise ValueError("Unit installer inventory differs from shipped units")
    return UNIT_INSTALLERS


def timer_files(mode, values):
    unit = TIMERS[mode]
    service = unit + ".service"
    source = service + ".tmpl" if (ROOT / "deploy/quadlet" / (service + ".tmpl")).exists() else service
    return {service: render("deploy/quadlet/" + source, values),
            unit + ".timer": render("deploy/quadlet/" + unit + ".timer", values)}


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE).strip()


def required(name):
    value = os.environ.get(name, "")
    if not value or any(c in value for c in '\n\r\0'):
        raise ValueError(f"Set {name} in the private host environment")
    return value


def validate_manifest(data, repository):
    if not isinstance(data, dict) or set(data) != {"image", "revision"}:
        raise ValueError("Release manifest must contain image and revision only")
    if not all(isinstance(v, str) for v in data.values()):
        raise ValueError("Release manifest values must be strings")
    if not re.fullmatch(r"[a-f0-9]{40}", data["revision"]):
        raise ValueError("Release revision must be a full Git SHA")
    if not re.fullmatch(re.escape(repository) + r"@sha256:[a-f0-9]{64}", data["image"]):
        raise ValueError("Release image must be a digest in the operator-approved repository")
    return data


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def render(template, values):
    text = (ROOT / template).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("@" + key + "@", value)
    if re.search(r"@[A-Z_]+@", text):
        raise ValueError("Unresolved deployment template value")
    return text


def read_release():
    # A reviewed Actions artifact can be staged locally without publishing a URL.
    source = os.environ.get("SIERX_DEPLOY_MANIFEST_URL", "")
    local = os.environ.get("SIERX_DEPLOY_MANIFEST_FILE", "")
    if os.environ.get("SIERX_NETWORK_MODE") == "offline" and source:
        raise ValueError("Offline deployment requires a local release manifest")
    if bool(source) == bool(local):
        raise ValueError("Set exactly one of SIERX_DEPLOY_MANIFEST_URL or SIERX_DEPLOY_MANIFEST_FILE")
    if local:
        path = pathlib.Path(required("SIERX_DEPLOY_MANIFEST_FILE"))
        if not path.is_absolute() or not path.is_file():
            raise ValueError("The reviewed release manifest must be an absolute file path")
        with path.open("rb") as stream:
            raw = stream.read(8193)
    else:
        source = required("SIERX_DEPLOY_MANIFEST_URL")
        if urllib.parse.urlsplit(source).scheme != "https":
            raise ValueError("The release manifest requires HTTPS")
        with urllib.request.urlopen(source, timeout=30) as response:
            raw = response.read(8193)
    if len(raw) > 8192:
        raise ValueError("Release manifest is too large")
    return validate_manifest(json.loads(raw), required("SIERX_IMAGE_REPOSITORY"))


def gateway_config(host, app_port, app_env):
    mode = os.environ.get("SIERX_GATEWAY_MODE", "direct")
    values = {"SIERX_HOST": host, "SIERX_APP_PORT": app_port}
    tls = os.environ.get("SIERX_TLS_MODE", "public")
    if tls not in {"public", "provided"}:
        raise ValueError("SIERX_TLS_MODE must be public or provided")
    if os.environ.get("SIERX_NETWORK_MODE") == "offline" and (mode != "direct" or tls != "provided"):
        raise ValueError("Offline deployment requires direct HTTPS with a provided certificate")
    if mode == "direct":
        text = render("deploy/Caddyfile.tmpl", values)
        if tls == "provided":
            directory = pathlib.Path.home() / ".config/sierx/tls"
            certificate, key = directory / "server.crt", directory / "server.key"
            if not certificate.is_file() or not key.is_file() or key.stat().st_mode & 0o077:
                raise ValueError("Install tls/server.crt and private 0600 tls/server.key before deployment")
            # Explicit TLS remains HTTPS. Disable automatic port-80 redirects
            # so an unprivileged :8443 site does not unexpectedly need port 80.
            options = "  auto_https off\n  admin off\n"
            if os.environ.get("SIERX_NETWORK_MODE") == "offline":
                options += "  ocsp_stapling off\n"
            text = text.replace("{\n  servers", "{\n" + options + "  servers", 1)
            text = text.replace(host + " {", host + " {\n  tls /etc/sierx/tls/server.crt /etc/sierx/tls/server.key", 1)
        return text
    if tls != "public":
        raise ValueError("Provided TLS belongs to the direct gateway profile")
    if mode != "tunnel":
        raise ValueError("SIERX_GATEWAY_MODE must be direct or tunnel")
    port = required("SIERX_GATEWAY_PORT")
    if not re.fullmatch(r"[0-9]{4,5}", port) or not 1024 <= int(port) <= 65535 or int(port) == int(app_port):
        raise ValueError("Tunnel gateway port must be an unprivileged port distinct from the application")
    if ":" in host:
        raise ValueError("Tunnel mode requires a standard HTTPS hostname without a port")
    if app_env.get("SIERX_AUTH_MODE") != "local":
        raise ValueError("Tunnel mode currently requires Sierx local authentication")
    values["SIERX_GATEWAY_PORT"] = port
    return render("deploy/Caddyfile.tunnel.tmpl", values)


def main(mode):
    if mode not in {"plan", "apply", *TIMERS}:
        raise ValueError("Usage: deploy.py plan|apply|" + "|".join(TIMERS))
    network = os.environ.get("SIERX_NETWORK_MODE", "connected")
    if network not in {"connected", "offline"}:
        raise ValueError("SIERX_NETWORK_MODE must be connected or offline")
    if network == "offline" and mode in TIMERS:
        raise ValueError("Offline timers require a separately reviewed host schedule; use verified manual operations")
    unit_inventory()
    config = pathlib.Path.home() / ".config/sierx"
    units = pathlib.Path.home() / ".config/containers/systemd"
    state = pathlib.Path.home() / ".local/share/sierx"
    config.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    if mode in TIMERS:
        unit = TIMERS[mode]
        user_units = pathlib.Path.home() / ".config/systemd/user"
        checkout = str(ROOT)
        if any(c in checkout for c in '"\n\r%\\'):
            raise ValueError("Unsupported character in operator checkout path")
        values = {"SIERX_CHECKOUT": checkout}
        if mode == "install-restore-timer":
            binary = pathlib.Path(required("SIERX_OPERATOR_BIN"))
            if (not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK)
                    or any(c in str(binary) for c in '"\n\r%\\')):
                raise ValueError("SIERX_OPERATOR_BIN must be an executable absolute path to the accepted native release CLI")
            for tool in ("bash", "psql", "flock"):
                if shutil.which(tool) is None:
                    raise ValueError("Restore host prerequisite missing: " + tool)
            restore_env = config / "restore.env"
            if not restore_env.is_file() or restore_env.stat().st_mode & 0o077:
                raise ValueError("Create the private 0600 restore.env before installing its timer")
            values["SIERX_OPERATOR_BIN"] = str(binary)
        for filename, content in timer_files(mode, values).items():
            atomic(user_units / filename, content)
        run("systemctl", "--user", "daemon-reload")
        run("systemctl", "--user", "enable", "--now", unit+".timer")
        return
    offline_images = None
    if network == "offline":
        # Loaded by path for callers which import deploy.py in tests or tools.
        import importlib.util
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("sierx_offline", ROOT / "scripts/offline.py")
        offline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(offline)
        bundle, locked = offline.from_environment()
        if bundle.resolve() != ROOT:
            raise ValueError("Run the deployment scripts from the verified bundle")
        offline_images = locked["images"]
    release = read_release()
    if offline_images and release != locked["release"]:
        raise ValueError("Deployment release differs from verified bundle")
    current = state / "current.json"
    origin = urllib.parse.urlsplit(required("SIERX_BASE_URL"))
    if origin.scheme != "https" or origin.username or origin.path not in {"", "/"} or origin.query or origin.fragment or not origin.hostname:
        raise ValueError("SIERX_BASE_URL must be a plain HTTPS origin")
    host = origin.netloc
    if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", host):
        raise ValueError("Invalid HTTPS host")
    port = required("SIERX_APP_PORT")
    if not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise ValueError("SIERX_APP_PORT must be an unprivileged port")
    gateway = required("SIERX_CADDY_IMAGE")
    if not re.fullmatch(r"[A-Za-z0-9._:/-]+@sha256:[a-f0-9]{64}", gateway):
        raise ValueError("Caddy must use a pinned image digest")
    app_image, gateway_image = release["image"], gateway
    if offline_images:
        if gateway != offline_images["caddy"]["source"]:
            raise ValueError("Caddy differs from verified bundle")
        for role in ("app", "caddy"):
            offline.inspect_image(offline_images[role], locked["arch"], release["revision"] if role == "app" else None)
        app_image, gateway_image = offline_images["app"]["id"], offline_images["caddy"]["id"]
    app_env = config / "app.env"
    if not app_env.is_file() or app_env.stat().st_mode & 0o077:
        raise ValueError("Create the private 0600 app.env before deployment")
    env = dict(line.split("=", 1) for line in app_env.read_text().splitlines() if line and not line.startswith("#") and "=" in line)
    if env.get("SIERX_LISTEN_ADDR") != "127.0.0.1:" + port:
        raise ValueError("app.env must bind the application to the selected loopback port")
    if env.get("SIERX_BASE_URL", "").rstrip("/") != required("SIERX_BASE_URL").rstrip("/"):
        raise ValueError("Application and gateway origins differ")
    values = {"SIERX_IMAGE": app_image, "SIERX_CADDY_IMAGE": gateway_image, "SIERX_HOST": host, "SIERX_APP_PORT": port}
    planned = {units / "sierx.container": render("deploy/quadlet/sierx.container.tmpl", values),
               units / "sierx-caddy.container": render("deploy/quadlet/sierx-caddy.container.tmpl", values),
               config / "Caddyfile": gateway_config(host, port, env)}
    if os.environ.get("SIERX_TLS_MODE") == "provided":
        path = units / "sierx-caddy.container"
        planned[path] = planned[path].replace("NoNewPrivileges=true", "Volume=%h/.config/sierx/tls:/etc/sierx/tls:ro,Z\nNoNewPrivileges=true")
    print("deploy: candidate " + release["revision"] + "; digest-pinned app and HTTPS gateway; no database reset")
    if mode == "plan":
        return
    # The same image can require a gateway-mode/configuration change.
    if (current.exists() and json.loads(current.read_text()) == release
            and all(path.is_file() and path.read_text() == text for path, text in planned.items())):
        print("deploy: accepted revision and rendered configuration are already installed")
        return
    if network == "connected":
        run("podman", "pull", app_image)
        run("podman", "pull", gateway_image)
    metadata = json.loads(run("podman", "image", "inspect", app_image))[0]
    if metadata.get("Labels", {}).get("org.opencontainers.image.revision") != release["revision"]:
        raise ValueError("Image revision does not match the release manifest")
    container = run("podman", "create", "--pull=never", app_image)
    try:
        with tempfile.TemporaryDirectory(prefix="sierx-release-") as temporary:
            run("podman", "cp", container + ":/srv/sierx/assets/.", temporary)
            assets = state / "assets"
            assets.mkdir(exist_ok=True)
            # Keep old hashes available for already-open browser sessions.
            for file in pathlib.Path(temporary).iterdir():
                if not file.is_file() or file.is_symlink():
                    raise ValueError("Unexpected release asset")
                destination = assets / file.name
                if destination.exists() and destination.read_bytes() != file.read_bytes():
                    raise ValueError("Content-hashed asset collision")
                shutil.copyfile(file, destination)
    finally:
        run("podman", "rm", container)
    previous = {path: path.read_text() if path.exists() else None for path in planned}
    try:
        for path, text in planned.items():
            atomic(path, text)
        run("systemctl", "--user", "daemon-reload")
        run("systemctl", "--user", "restart", "sierx.service", "sierx-caddy.service")
        for attempt in range(20):
            try:
                with urllib.request.urlopen(required("SIERX_BASE_URL").rstrip("/") + "/api/v1/healthz", timeout=5) as response:
                    if response.status == 200:
                        break
            except OSError:
                if attempt == 19:
                    raise
                time.sleep(3)
        atomic(current, json.dumps(release, indent=2) + "\n")
        print("deploy: HTTPS health passed; candidate is current")
    except Exception:
        for path, text in previous.items():
            if text is not None:
                atomic(path, text)
            else:
                path.unlink(missing_ok=True)
        run("systemctl", "--user", "daemon-reload")
        if previous[units / "sierx.container"] is not None:
            run("systemctl", "--user", "restart", "sierx.service", "sierx-caddy.service")
        else:
            run("systemctl", "--user", "stop", "sierx.service", "sierx-caddy.service")
        raise


if __name__ == "__main__":
    try:
        # Host-side Linux tool: serialize manual and timer runs before changes.
        import fcntl
        lock_path = pathlib.Path.home() / ".local/share/sierx/deploy.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            main(sys.argv[1] if len(sys.argv) > 1 else "plan")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # Never print command arguments, URLs, response bodies or host config.
        print("deploy: " + (str(error) if isinstance(error, ValueError) else "operation failed; inspect private host logs"), file=sys.stderr)
        sys.exit(1)
