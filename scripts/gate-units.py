"""Validate the actual rendered deployment units using native Linux tools."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import deploy


def verify(root, planted=False):
    source, generated = root / "src", root / "generated"
    source.mkdir(); generated.mkdir()
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
    values = {"SIERX_IMAGE": "example.test/sierx@sha256:" + "a" * 64,
              "SIERX_CADDY_IMAGE": "example.test/caddy@sha256:" + "c" * 64,
              "SIERX_HOST": "tracker.example.test", "SIERX_APP_PORT": "8080",
              "SIERX_CHECKOUT": str(deploy.ROOT), "SIERX_OPERATOR_BIN": "/usr/bin/true"}
    for filename in deploy.unit_inventory():
        destination = source / filename.removesuffix(".tmpl")
        destination.write_text(deploy.render("deploy/quadlet/" + filename, values))
    if planted:
        (source / "sierx-planted.service").write_text(
            "[Service]\nType=oneshot\nWorkingDirectory=relative\nExecStart=/usr/bin/true\n")
    quadlet = os.environ.get("QUADLET", "/usr/libexec/podman/quadlet")
    subprocess.run([quadlet, "-user", str(generated)], check=True,
                   env={**os.environ, "QUADLET_UNIT_DIRS": str(source)})
    for path in source.iterdir():
        if path.suffix in {".service", ".timer"}:
            shutil.copyfile(path, generated / path.name)
    expected = {name.removesuffix(".tmpl").removesuffix(".container") + ".service"
                for name in deploy.UNIT_INSTALLERS if name.removesuffix(".tmpl").endswith(".container")}
    if not all((generated / name).is_file() for name in expected):
        raise ValueError("Quadlet did not generate every required container service")
    result = subprocess.run(["systemd-analyze", "--user", "verify", "--man=no",
                             *map(str, sorted(generated.glob("*.service"))),
                             *map(str, sorted(generated.glob("*.timer")))],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env={**os.environ, "LC_ALL": "C", "XDG_RUNTIME_DIR": str(runtime)})
    if planted:
        if result.returncode == 0 or "not absolute" not in result.stdout or "sierx-planted" not in result.stdout:
            raise ValueError("Planted relative WorkingDirectory did not fail for the expected reason\n" + result.stdout)
    elif result.returncode or any(term in result.stdout.lower() for term in ("unknown key", "unknown lvalue", "bad unit", "failed to parse")):
        raise ValueError("Rendered units failed verification\n" + result.stdout)


def main():
    if sys.argv[1:] not in ([], ["--prove"]):
        raise ValueError("Usage: gate-units.py [--prove]")
    for tool in ("podman", "systemd-analyze", "python3", "flock", "true"):
        if shutil.which(tool) is None:
            raise ValueError("Missing unit verification prerequisite: " + tool)
    for tool in ("podman", "systemd-analyze"):
        version = subprocess.check_output([tool, "--version"], text=True).splitlines()[0]
        print("gate-units profile: " + version, flush=True)
    with tempfile.TemporaryDirectory(prefix="sierx-units-") as scratch:
        baseline = Path(scratch) / "baseline"; baseline.mkdir()
        verify(baseline)
        if "--prove" in sys.argv:
            planted = Path(scratch) / "planted"; planted.mkdir()
            verify(planted, planted=True)
    print("gate-units: rendered units accepted" + ("; planted invalid unit rejected" if "--prove" in sys.argv else ""))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit("gate-units: " + str(error))
