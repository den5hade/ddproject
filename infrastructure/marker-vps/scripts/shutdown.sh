#!/usr/bin/env bash
# Called by marker-orchestrator / scheduled task when work is drained, to stop
# the GPU node and save money.
set -euo pipefail

cd /opt/marker-vps
docker compose down