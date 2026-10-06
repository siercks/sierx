#!/usr/bin/env bash
# Scheduled driver-neutral backup. Failure remains visible in the systemd unit.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
export SIERX_BACKUP_KIND=incr
[[ $(date -u +%u) != 7 ]] || export SIERX_BACKUP_KIND=full
for driver in $(bash scripts/backup/driver.sh --list); do
  bash scripts/backup/driver.sh "$driver" backup >/dev/null
  bash scripts/backup/driver.sh "$driver" verify
  bash scripts/backup/driver.sh "$driver" retention
done
echo 'scheduled backup: all configured drivers passed backup, verify and retention'
