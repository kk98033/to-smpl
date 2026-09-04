#!/usr/bin/env bash
# Prepare smpl-0901-bridge container for GB10 / ARM64.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
models_dir="${SMPL_MODELS_DIR:-${script_dir}/models}"

for path in "${models_dir}/J_regressor_body25.npy" "${models_dir}/smpl/SMPL_NEUTRAL.pkl"; do
    if [[ ! -f "${path}" ]]; then
        echo "required model asset missing: ${path}" >&2
        echo "place SMPL models in ${models_dir} before running" >&2
        exit 2
    fi
done

echo "[to-smpl] Building smpl-0901-bridge:gx10 image..."
if [[ "${EUID}" -ne 0 ]] && ! docker info >/dev/null 2>&1; then
    sudo docker compose -f "${script_dir}/compose.yaml" build
else
    docker compose -f "${script_dir}/compose.yaml" build
fi

echo "[to-smpl] Image build and model validation complete."
echo "To start the bridge:"
echo "  sudo UNITY_HOST=127.0.0.1 docker compose up -d"
