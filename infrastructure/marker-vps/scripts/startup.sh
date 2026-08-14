#!/usr/bin/env bash
# Called on GPU VPS boot (e.g. via cloud-init / systemd) to join the mesh
# network, refresh the image and start the worker. See STRUCTURE.md.
set -euo pipefail

cd /opt/marker-vps

docker login --username "${REGISTRY_USER:?}" --password-stdin <<< "${REGISTRY_TOKEN:?}" \
  "https://${MARKER_WORKER_IMAGE%%/*}"

systemctl start tailscaled
tailscale up --authkey "${TAILSCALE_AUTH_KEY:?}"

docker compose down || true
docker compose pull
docker compose up -d