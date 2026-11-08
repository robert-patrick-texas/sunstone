#!/bin/bash
# The dev instance inside its container (compose.yaml). The working tree is at
# /src, read-only. The API runs from it, restarting when its code changes. The
# web UI is built from a copy in /work and rebuilt whenever its source changes;
# a build that fails leaves the last good one served.
set -euo pipefail

topology=/src/${SUNSTONE_DEV_TOPOLOGY}

# Copy the web UI's source, leaving out what builds and tests make; print what
# changed. Folder times are left alone: a build touches the copy's folder (Vite
# writes and deletes a file beside its config), which would start another.
sync_source() {
    rsync -a --delete --omit-dir-times --itemize-changes \
        --exclude node_modules --exclude .svelte-kit --exclude build \
        --exclude test-results --exclude e2e --exclude bench \
        /src/frontend/ /work/frontend/
}

# Build the web UI and put it where the API serves it from: new hashed assets
# first, then index.html, then the old assets go.
build_web() {
    cd /work/frontend
    if ! cmp -s package-lock.json /work/installed.lock; then
        npm ci --no-audit --no-fund && cp package-lock.json /work/installed.lock
    fi
    if npm run build >/work/build.log 2>&1; then
        rsync -a --delete-after build/ /work/web/
        echo "sunstone-dev: web UI built"
    else
        cat /work/build.log
        echo "sunstone-dev: the web UI did not build; serving the last one" >&2
    fi
}

# Reinstalling Sunstone itself picks up a new VERSION; the editable install
# otherwise keeps the one it was installed with. The dev dependencies bring
# watchfiles, without which --reload restarts on code changes only, not on
# topology edits.
(cd /src/backend && uv sync --locked --reinstall-package sunstone)
mkdir -p /work/frontend /work/web
sync_source >/dev/null
build_web

/venv/bin/sunstone serve --topology "$topology" --state-dir /state \
    --web-dir /work/web --host 0.0.0.0 --port 8000 --reload &
api=$!
trap 'kill "$api" 2>/dev/null; wait "$api"; exit 0' TERM INT

# A run of edits builds once: after a change, wait until the source has been
# still for a few seconds.
while kill -0 "$api" 2>/dev/null; do
    sleep 2
    [ -z "$(sync_source)" ] && continue
    while sleep 3 && [ -n "$(sync_source)" ]; do :; done
    build_web
done
wait "$api"
