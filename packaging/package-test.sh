#!/bin/bash
# Package tests, following vakr's: build three test releases signed with a
# throwaway key, a broken one, and two that must be refused, then install,
# run, update, roll back, update daily from a stand-in for GitHub behind a CA
# the host does not trust, and remove them inside a container booted with
# systemd (container/systemd-test.sh). `make package-test` runs this; it
# needs docker, git, uv, ssh-keygen, and openssl.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
work=dist/package-test
rm -rf "$work"
mkdir -p "$work/keys"
ssh-keygen -q -t ed25519 -N "" -C package-test -f "$work/keys/release"
ssh-keygen -q -t ed25519 -N "" -C untrusted -f "$work/keys/untrusted"
printf 'sunstone-release namespaces="sunstone-release" %s\n' \
    "$(cat "$work/keys/release.pub")" >"$work/keys/signers"

sign() {
    # SHA256SUMS for the package in directory $1, signed with key $2.
    (cd "$1" && sha256sum sunstone_*_amd64.deb >SHA256SUMS)
    ssh-keygen -q -Y sign -f "$2" -n sunstone-release "$1/SHA256SUMS"
}

for version in 0.1.1 0.1.2 0.1.4; do
    VERSION_OVERRIDE=$version RELEASE_SIGNERS=$work/keys/signers \
        packaging/build-deb.sh "$work/$version"
    sign "$work/$version" "$work/keys/release"
done

# 0.1.3: 0.1.2 with code that fails at start, so the update must roll back.
mkdir -p "$work/broken"
docker run --rm --volume "$PWD/$work:/w" ubuntu:26.04 bash -c '
    set -e
    dpkg-deb -R /w/0.1.2/sunstone_0.1.2_amd64.deb /tmp/x
    echo "raise SystemExit(\"broken on purpose by package-test\")" \
        >>"$(echo /tmp/x/opt/sunstone/venv/lib/python3.*/site-packages/sunstone/cli.py)"
    sed -i "s/^Version: .*/Version: 0.1.3/" /tmp/x/DEBIAN/control
    dpkg-deb --root-owner-group -b /tmp/x /w/broken/sunstone_0.1.3_amd64.deb >/dev/null
    chown -R '"$(id -u):$(id -g)"' /w/broken'
sign "$work/broken" "$work/keys/release"

# 0.1.2 altered after signing, and 0.1.2 signed by a key the packages do not trust.
mkdir -p "$work/tampered" "$work/untrusted"
cp "$work"/0.1.2/* "$work/tampered/"
printf x >>"$work/tampered/sunstone_0.1.2_amd64.deb"
cp "$work/0.1.2/sunstone_0.1.2_amd64.deb" "$work/untrusted/"
sign "$work/untrusted" "$work/keys/untrusted"

# A CA the host does not trust, as an inspecting proxy's would be, and the
# certificate it issues for the stand-in for GitHub (container/fake-github.py).
mkdir -p "$work/pki"
ec=(-newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes)
printf '%s\n' '[req]' 'distinguished_name = dn' 'prompt = no' '[dn]' 'CN = Test Inspection CA' \
    '[ext]' 'basicConstraints = critical,CA:TRUE' 'subjectKeyIdentifier = hash' \
    'keyUsage = critical,keyCertSign,cRLSign' >"$work/pki/ca.cnf"
openssl req -x509 -config "$work/pki/ca.cnf" -extensions ext "${ec[@]}" -days 2 \
    -keyout "$work/pki/ca.key" -out "$work/pki/ca.pem" 2>/dev/null
openssl req -new "${ec[@]}" -subj /CN=localhost \
    -keyout "$work/pki/server.key" -out "$work/pki/server.csr" 2>/dev/null
printf '%s\n' 'subjectAltName = DNS:localhost' 'basicConstraints = CA:FALSE' \
    'keyUsage = critical,digitalSignature' 'extendedKeyUsage = serverAuth' \
    'authorityKeyIdentifier = keyid' 'subjectKeyIdentifier = hash' >"$work/pki/server.ext"
openssl x509 -req -in "$work/pki/server.csr" -CA "$work/pki/ca.pem" -CAkey "$work/pki/ca.key" \
    -set_serial 2 -days 2 -extfile "$work/pki/server.ext" -out "$work/pki/server.pem" 2>/dev/null

image=sunstone-systemd-test
docker build --quiet --tag "$image" - <packaging/container/Dockerfile.systemd >/dev/null
container=sunstone-package-test-$$
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT
# systemd as PID 1 needs a privileged container with its own cgroup tree.
docker run --detach --name "$container" --privileged --cgroupns=private \
    --tmpfs /run --tmpfs /run/lock \
    --volume "$PWD/packaging/container:/test:ro" --volume "$PWD/$work:/releases:ro" \
    "$image" >/dev/null
for _ in $(seq 60); do
    state=$(docker exec "$container" systemctl is-system-running 2>/dev/null || true)
    case $state in running | degraded) break ;; esac
    sleep 1
done
docker exec "$container" bash /test/systemd-test.sh
