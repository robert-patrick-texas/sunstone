#!/bin/bash
# Assemble /opt/sunstone and package it with nfpm inside the clean builder
# container, following vakr's packaging/container/build.sh.
# packaging/build-deb.sh runs it; do not run it on a host, because it
# installs into /opt/sunstone.
#
# Inputs: /in/source.tar (the staged tree), /in/release-signers, and:
#   SUNSTONE_VERSION      VERSION string, e.g. 0.2.0-rc.1
#   SUNSTONE_DEB_VERSION  its Debian form, e.g. 0.2.0~rc.1
#   SUNSTONE_TEST_BUILD   1 when VERSION_OVERRIDE set the version
#   SOURCE_DATE_EPOCH     commit time; every packaged file gets this mtime
#   HOST_UID, HOST_GID    owner for the files written to /out
# Output: /out/sunstone_<deb version>_amd64.deb
set -euo pipefail

: "${SUNSTONE_VERSION:?}" "${SUNSTONE_DEB_VERSION:?}" "${SOURCE_DATE_EPOCH:?}"
export SOURCE_DATE_EPOCH
# Fixed hash seed for reproducible bytecode; no stray __pycache__ while
# Sunstone itself runs below (bytecode is compiled once, at the end).
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1
export UV_PYTHON_INSTALL_DIR=/build/python UV_NO_PROGRESS=1 UV_LINK_MODE=copy

OPT=/opt/sunstone
PY=$OPT/python/bin/python3
PYVER=""  # from backend/.python-version, so the bundled interpreter follows it
SRC=/build/src
DEB=/build/out/sunstone_${SUNSTONE_DEB_VERSION}_amd64.deb

log() { printf '==> %s\n' "$*"; }
die() { printf 'build.sh: %s\n' "$*" >&2; exit 1; }

unpack_source() {
    mkdir -p "$SRC" /build/out "$OPT"
    tar -xf /in/source.tar -C "$SRC"
    cd "$SRC"
    if [ "${SUNSTONE_TEST_BUILD:-0}" = 1 ]; then
        log "TEST BUILD: VERSION_OVERRIDE sets version $SUNSTONE_VERSION (never release this)"
        printf '%s\n' "$SUNSTONE_VERSION" >VERSION
    fi
    [ "$(cat VERSION)" = "$SUNSTONE_VERSION" ] || die "VERSION is not $SUNSTONE_VERSION"
    PYVER=$(tr -d '[:space:]' <backend/.python-version)
    [[ $PYVER =~ ^3\.[0-9]+$ ]] || die "backend/.python-version must be MAJOR.MINOR, not '$PYVER'"
}

install_python() {
    # uv pins the python-build-standalone release and verifies its checksum.
    log "installing Python $PYVER from python-build-standalone"
    uv python install --no-bin "$PYVER"
    local found
    found=$(uv python find --managed-python "$PYVER")
    mv "$(dirname "$(dirname "$(readlink -f "$found")")")" "$OPT/python"
    local lib=$OPT/python/lib stdlib=$OPT/python/lib/python$PYVER
    # Tk/IDLE need X11 and are useless on a server. Headers, the config dir,
    # *-config, pydoc, and libpython matter only for building or embedding,
    # never here: wheels are binary-only. The base interpreter's pip goes
    # too, so packages only enter through the venv.
    rm -rf "$stdlib"/{idlelib,tkinter,turtledemo,turtle.py} "$stdlib"/lib-dynload/_tkinter.* \
        "$lib"/{tcl,tk,itcl,thread}* "$lib"/lib{tcl,tk}* "$lib/pkgconfig" "$lib"/libpython3* \
        "$stdlib"/config-"$PYVER"-* "$OPT/python/include" "$stdlib"/site-packages/pip* \
        "$OPT/python/bin"/{idle,pip,pydoc}* "$OPT/python/bin"/python*-config
    "$PY" --version
}

install_venv() {
    log "creating $OPT/venv with locked dependencies and the sunstone wheel"
    "$PY" -m venv --without-pip "$OPT/venv"
    # A relative interpreter link keeps the venv valid wherever /opt/sunstone
    # is inspected (lintian, an unpacked image); the .gitignore is noise here.
    ln -sfn ../../python/bin/python3 "$OPT/venv/bin/python3"
    rm -f "$OPT/venv/.gitignore"
    (
        cd backend
        uv export --frozen --no-dev --no-emit-project --quiet \
            --format requirements.txt -o /build/requirements.txt
        # PyYAML publishes no wheel for Python 3.15 yet, so it is built here
        # from its hash-checked source with hash-pinned build tools, without
        # its optional C extension: pure Python, as `uv sync` builds it for
        # development. Everything else comes as a hash-checked wheel only.
        awk '/^pyyaml==/{f=1} !f{print} f&&!/\\$/{f=0}' /build/requirements.txt \
            >/build/requirements-wheels.txt
        awk '/^pyyaml==/{f=1} f{print} f&&!/\\$/{f=0}' /build/requirements.txt \
            >/build/requirements-source.txt
        uv pip install --python "$OPT/venv/bin/python3" --require-hashes --only-binary :all: \
            --no-deps -r /build/requirements-wheels.txt
        PYYAML_FORCE_LIBYAML=0 uv pip install --python "$OPT/venv/bin/python3" --require-hashes \
            --no-deps --build-constraint ../packaging/build-constraints.txt \
            -r /build/requirements-source.txt
        uv build --wheel --python "$PY" --out-dir /build/wheel \
            --build-constraint ../packaging/build-constraints.txt --require-hashes .
    )
    # --no-cache: a cached wheel of the same name must never stand in for
    # this build's code.
    uv pip install --python "$OPT/venv/bin/python3" --no-deps --no-cache /build/wheel/sunstone-*.whl
    # uv's install-time timestamp (uv_cache.json, listed in RECORD) is only
    # uv bookkeeping and would make two builds of one commit differ.
    local info
    info=$(echo "$OPT"/venv/lib/python"$PYVER"/site-packages/sunstone-*.dist-info)
    rm -f "$info/uv_cache.json" "$OPT/venv/.lock"
    sed -i '/\/uv_cache\.json,/d' "$info/RECORD"
}

install_share() {
    local share=$OPT/share
    install -D -m 0644 /in/release-signers "$share/release-signers"
    install -D -m 0644 packaging/templates/config.toml "$share/templates/config.toml"
    install -D -m 0644 -t "$share/samples" data/sample/small.yaml data/sample/small.oncall.yaml \
        data/sample/large.yaml data/sample/large.oncall.yaml
    install -D -m 0644 -t "$share/doc" LICENSE NOTICE README.md CHANGELOG.md
    write_debian_changelog
}

install_web() {
    # npm ci from the lockfile without running any package's install
    # scripts, then the production build. Only the built files and the
    # bundled packages' licence texts are packaged; Node never is.
    log "building the web UI (npm ci --ignore-scripts, npm run build)"
    (
        cd frontend
        npm ci --ignore-scripts --no-audit --no-fund
        npm run build
        node scripts/collect-licenses.js "$OPT/share/doc/web-licenses" ../packaging/copyright
    )
    mkdir -p "$OPT/share/web"
    cp -R frontend/build/. "$OPT/share/web/"
}

smoke_test() {
    # Every remaining extension module and wheel must still load after pruning.
    log "smoke test: import every lib-dynload module and the runtime packages"
    "$OPT/venv/bin/python3" - <<'PY'
import importlib, pathlib, sys
version = f"python{sys.version_info.major}.{sys.version_info.minor}"
dynload = pathlib.Path(sys.base_exec_prefix, "lib", version, "lib-dynload")
names = sorted(p.name.split(".")[0] for p in dynload.glob("*.so"))
assert names, f"no extension modules found in {dynload}"
# Most extensions are built into the interpreter; these cover its static libraries.
builtin = ["ssl", "sqlite3", "ctypes", "zlib", "bz2", "lzma", "decimal", "zoneinfo"]
wheels = ["pydantic_core._pydantic_core", "yaml", "uvicorn", "sunstone.cli"]
for name in [*names, *builtin, *wheels]:
    importlib.import_module(name)
print(f"imported {len(names) + len(builtin) + len(wheels)} modules on Python {sys.version}")
PY
    # The wheel's version, in Python's spelling (0.2.0rc1), is VERSION's.
    "$OPT/venv/bin/sunstone" --version
    "$OPT/venv/bin/python3" -c 'import sys
from importlib.metadata import version
from sunstone.update.versions import Version
sys.exit(Version.parse(version("sunstone")) != Version.parse(sys.argv[1]))' \
        "$SUNSTONE_VERSION" || die "the installed sunstone is not $SUNSTONE_VERSION"
}

write_debian_changelog() {
    # Debian policy wants a Debian-format changelog in /usr/share/doc/sunstone
    # (nfpm.yaml). It points at CHANGELOG.md, which stays the one real record.
    local maintainer
    maintainer=$(sed -n 's/^maintainer: //p' packaging/nfpm.yaml)
    mkdir -p /build/doc
    printf '%s\n' "sunstone ($SUNSTONE_DEB_VERSION) unstable; urgency=medium" "" \
        "  * Release $SUNSTONE_VERSION. Release notes: /opt/sunstone/share/doc/CHANGELOG.md" "" \
        " -- $maintainer  $(date -u -R -d "@$SOURCE_DATE_EPOCH")" |
        gzip -9 --no-name >/build/doc/changelog.gz
    touch --date="@$SOURCE_DATE_EPOCH" /build/doc/changelog.gz
}

normalize_tree() {
    log "compiling bytecode and normalising modes and mtimes"
    find "$OPT" -name __pycache__ -type d -prune -exec rm -rf {} +
    # Hash-based .pyc files stay valid whatever the source mtime is, so the
    # mtime clamp below cannot make Python rewrite them as root at runtime.
    # One process in sorted order: spreading files over workers is not reproducible.
    "$PY" -m compileall -q -j 1 --invalidation-mode checked-hash \
        "$OPT/python/lib/python$PYVER" "$OPT/venv/lib/python$PYVER/site-packages"
    chmod -R u+rwX,go+rX,go-w "$OPT"
    # Shared libraries are mapped, never executed; dpkg and lintian expect 0644.
    find "$OPT" -type f \( -name '*.so' -o -name '*.so.*' \) -exec chmod a-x {} +
    find "$OPT" -exec touch --no-dereference --date="@$SOURCE_DATE_EPOCH" {} +
}

check_glibc_floor() {
    # The package declares libc6 (>= floor); nothing packaged may need newer.
    local floor newest
    floor=$(sed -n 's/.*- libc6 (>= \([0-9.]*\)).*/\1/p' packaging/nfpm.yaml)
    # readelf exits non-zero for the many non-ELF files; only its output matters.
    newest=$({ find "$OPT" -type f -exec readelf -V --wide {} + 2>/dev/null || true; } |
        grep -oE 'Name: GLIBC_[0-9.]+' | sed 's/Name: GLIBC_//' | sort -uV | tail -n 1)
    [ -n "$newest" ] || die "found no ELF files needing glibc; is readelf installed?"
    log "newest glibc symbol version needed: $newest (declared floor $floor)"
    dpkg --compare-versions "$newest" le "$floor" || die "raise libc6 floor in nfpm.yaml"
}

verify_units() {
    log "systemd-analyze verify"
    local out
    out=$(systemd-analyze verify --man=no --recursive-errors=no \
        "$SRC"/packaging/systemd/sunstone.service 2>&1) ||
        die "systemd-analyze verify failed: $out"
    [ -z "$out" ] || die "systemd-analyze verify reported: $out"
}

package_and_lint() {
    log "nfpm package -> $(basename "$DEB")"
    SUNSTONE_DEB_VERSION=$SUNSTONE_DEB_VERSION nfpm package --config packaging/nfpm.yaml \
        --packager deb --target "$DEB"
    log "lintian"
    # lintian warns when run as root; it only needs to read the package.
    runuser -u nobody -- env HOME=/tmp lintian --fail-on error --tag-display-limit 0 "$DEB"
    cp "$DEB" /out/
    chown "${HOST_UID:-0}:${HOST_GID:-0}" /out/"$(basename "$DEB")"
    log "built $(basename "$DEB") ($(du -h "$DEB" | cut -f1))"
}

unpack_source
install_python
install_venv
install_share
install_web
smoke_test
normalize_tree
check_glibc_floor
verify_units
package_and_lint
