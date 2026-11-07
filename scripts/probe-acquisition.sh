#!/usr/bin/env bash
# Targeted diagnostic only. It neither starts app services nor promotes an image.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
revision=$(git rev-parse HEAD)
case $(uname -m) in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; *) exit 1 ;; esac
[[ $(id -u) != 0 ]] || { echo 'Run as the original rootless Podman user' >&2; exit 1; }
archive=$(realpath "dist/candidate-$arch.tar")
report="$PWD/dist/acquisition-diagnostic-$arch.json"
# A separate network namespace has only loopback. Drop back to the original
# user before Python/Podman, preserving root solely for strace observation.
sudo -n unshare --net -- /bin/bash -eu -c '
  ip link set lo up
  exec env HOME="$6" USER="$1" LOGNAME="$1" strace -qq -f --seccomp-bpf -e trace=network,clone,clone3,execve,exit_group \
    -o /dev/null -u "$1" /usr/bin/python3 "$2/scripts/probe-acquisition.py" \
    --archive "$3" --revision "$4" --report "$5"
' bash "$(id -un)" "$PWD" "$archive" "$revision" "$report" "$HOME"
