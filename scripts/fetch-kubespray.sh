#!/usr/bin/env bash
# Fetch code only. This script never invokes Ansible or changes a guest.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: scripts/fetch-kubespray.sh <private-checkout-directory>' >&2
  exit 2
fi
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
release_commit="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kubespray"]["commit"])' "$repo_root/versions.lock.json")"
upstream_url="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kubespray"]["repository"])' "$repo_root/versions.lock.json")"
checkout="$1"
python3 - "$checkout" "$repo_root" <<'PY'
from pathlib import Path
import sys
out=Path(sys.argv[1]).resolve();root=Path(sys.argv[2]).resolve()
if out.is_relative_to(root):
    raise SystemExit('Use a private checkout directory outside this public repository.')
if out.exists():
    raise SystemExit('Destination already exists; inspect/reuse it explicitly instead of overwriting.')
PY
mkdir -p "$checkout"
git -C "$checkout" init --quiet
git -C "$checkout" remote add origin "$upstream_url"
git -C "$checkout" fetch --depth=1 origin "$release_commit"
git -C "$checkout" checkout --detach FETCH_HEAD
actual_commit="$(git -C "$checkout" rev-parse HEAD)"
[[ "$actual_commit" == "$release_commit" ]] || { echo 'Commit mismatch' >&2; exit 1; }
echo "Verified Kubespray source commit: $actual_commit"
