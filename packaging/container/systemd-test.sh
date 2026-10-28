#!/bin/bash
# Install, run, update, roll back, and remove test builds of the package,
# inside a container booted with systemd as PID 1; packaging/package-test.sh
# runs it with `docker exec`. /releases holds one directory per release,
# each with a package, SHA256SUMS, and its signature by a throwaway key the
# test packages trust: 0.1.1, 0.1.2, and 0.1.4; broken (0.1.3, which fails at
# start); tampered (0.1.2, altered after signing); untrusted (0.1.2, signed by
# another key). /releases/pki holds a test CA, which the host does not trust,
# and the certificate it issued to container/fake-github.py, a stand-in for
# GitHub that the daily update reaches.
set -uo pipefail
# shellcheck source=packaging/container/testlib.sh
. /test/testlib.sh

API=http://127.0.0.1:8000/api

served() { curl -fsS "$API/version" 2>/dev/null | sed -n 's/.*"version":"\([^"]*\)".*/\1/p'; }
serves() {
    # The service answers as this version within a minute.
    for _ in $(seq 60); do
        [ "$(served)" = "$1" ] && return 0
        sleep 1
    done
    return 1
}
update_from() {
    # self-update --file from one release directory; its output goes to /tmp/update.log.
    local dir=/releases/$1
    sunstone self-update --yes --file "$(echo "$dir"/sunstone_*_amd64.deb)" \
        --sums "$dir/SHA256SUMS" --sig "$dir/SHA256SUMS.sig" >/tmp/update.log 2>&1
}
said() { contains "$(cat /tmp/update.log)" "$1"; }
mode() { stat -c '%a %U:%G' "$1"; }
record() { sed -n "s/.*\"$1\": \"\([^\"]*\)\".*/\1/p" /var/lib/sunstone/update/last-update.json; }

section "install 0.1.1"
apt_get update
apt_get install --no-install-recommends curl
# apt's sandbox user must be able to read local packages.
mkdir -p /tmp/debs && cp /releases/0.1.1/*.deb /tmp/debs/ && chmod 0644 /tmp/debs/*.deb
check "the package installs with apt" apt_get install /tmp/debs/sunstone_0.1.1_amd64.deb
check "sunstone --version says 0.1.1" equals "$(sunstone --version)" "sunstone 0.1.1"
check "/etc/sunstone/config.toml is created, readable by the service" \
    equals "$(mode /etc/sunstone/config.toml)" "640 root:sunstone"
check "the sample topology and on-call directory are put in /etc/sunstone" \
    test -s /etc/sunstone/topology.yaml -a -s /etc/sunstone/oncall.yaml
check "/var/lib/sunstone is root's" equals "$(mode /var/lib/sunstone)" "755 root:root"
check "/var/lib/sunstone/state is the service's" \
    equals "$(mode /var/lib/sunstone/state)" "750 sunstone:sunstone"
check "/var/lib/sunstone/update is root's alone" \
    equals "$(mode /var/lib/sunstone/update)" "700 root:root"
check "the release signers are installed" test -s /opt/sunstone/share/release-signers
check "the web UI's licences are installed" \
    test -s /opt/sunstone/share/doc/web-licenses/maplibre-gl/LICENSE.txt
check "sunstone check passes" sunstone check
check "nothing is enabled on install" equals "$(systemctl is-enabled sunstone.service)" disabled
check "nothing is started on install" test "$(systemctl is-active sunstone.service)" != active

section "the service"
systemctl enable --now sunstone.service
check "it answers as 0.1.1" serves 0.1.1
check "it serves the web UI at /" contains "$(curl -fsS http://127.0.0.1:8000/)" "<html"
pid=$(systemctl show -p MainPID --value sunstone.service)
check "it runs as sunstone" equals "$(ps -o user= -p "$pid")" sunstone
curl -fsS -X POST -H 'Content-Type: application/json' \
    -d '{"text": "written before the update", "by": "Pat"}' "$API/shift-notes" >/dev/null
check "a note is saved in the state directory" \
    grep -q "written before the update" /var/lib/sunstone/state/operations.json
config_before=$(sha256sum /etc/sunstone/config.toml)

section "releases that do not verify are refused"
update_from tampered
status=$?
check "a package altered after signing is refused" said "does not match SHA256SUMS"
check "with exit status 1" equals "$status" 1
update_from untrusted
status=$?
check "a release signed by another key is refused" said "signature verification failed"
check "with exit status 1" equals "$status" 1
check "and 0.1.1 still answers" serves 0.1.1
check "nothing was backed up for them" test -z "$(ls -A /var/lib/sunstone/update/backups)"

section "update to 0.1.2, from files copied by hand"
check "self-update installs 0.1.2" update_from 0.1.2
check "it says so" said "updated 0.1.1 -> 0.1.2"
check "it warns that a rollback could restore only configuration and state" \
    said "would restore only configuration and state"
check "the service answers as 0.1.2" serves 0.1.2
check "the note is still there" contains "$(curl -fsS "$API/handover")" "written before the update"
check "the configuration is untouched" equals "$(sha256sum /etc/sunstone/config.toml)" "$config_before"
backup=$(ls /var/lib/sunstone/update/backups/pre-update-*.tar.gz)
check "a backup was written, readable only by root" equals "$(mode "$backup")" "600 root:root"
check "the update is recorded" equals "$(record result)" updated

section "a release that fails to start rolls back"
update_from broken
status=$?
check "self-update exits 1" equals "$status" 1
check "it rolls back to 0.1.2" said "rolling back to 0.1.2"
check "0.1.2 is installed again" equals "$(dpkg-query -W -f='${Version}' sunstone)" 0.1.2
check "and answers" serves 0.1.2
check "the failure is recorded" equals "$(record result) $(record to)" "failed 0.1.3"

section "a downgrade from files, then --rollback"
check "self-update installs 0.1.1 over 0.1.2" update_from 0.1.1
check "0.1.1 answers" serves 0.1.1
echo "# edited after the downgrade" >>/etc/sunstone/config.toml
check "--rollback goes back to 0.1.2" sunstone self-update --rollback --yes
check "0.1.2 answers again" serves 0.1.2
check "the configuration is as it was before the downgrade" \
    equals "$(sha256sum /etc/sunstone/config.toml)" "$config_before"
check "today's configuration was saved first" \
    test -n "$(ls /var/lib/sunstone/update/backups/pre-rollback-*.tar.gz)"
check "the rollback is recorded" equals "$(record result) $(record to)" "rolled-back 0.1.2"

section "daily updates from a stand-in for GitHub, behind a CA the host does not trust"
journal() { journalctl -u sunstone-update.service --no-pager -o cat; }
check "the update timer is installed, and not enabled" \
    equals "$(systemctl is-enabled sunstone-update.timer)" disabled
check "/etc/sunstone/ca.d is root's" equals "$(mode /etc/sunstone/ca.d)" "755 root:root"
printf '%s\n' 0.1.1 0.1.2 broken >/tmp/listed
systemd-run --quiet --unit=fake-github /opt/sunstone/python/bin/python3 /test/fake-github.py
for _ in $(seq 30); do
    (exec 3<>/dev/tcp/127.0.0.1/8443) 2>/dev/null && break
    sleep 1
done
echo 'api = "https://localhost:8443"' >>/etc/sunstone/config.toml
sunstone self-update --check >/tmp/update.log 2>&1
status=$?
check "a certificate from a CA the host does not trust is refused" said "certificate not trusted"
check "saying where an inspecting proxy's CA goes" \
    said "put its CA certificate in /etc/sunstone/ca.d"
check "with exit status 1" equals "$status" 1
cp /releases/pki/ca.pem /etc/sunstone/ca.d/test-inspection.pem
sunstone self-update --check >/tmp/update.log 2>&1
check "with its CA in /etc/sunstone/ca.d, 0.1.3 is found" said "0.1.3 is available (installed 0.1.2)"

check "the timer enables" systemctl enable --now sunstone-update.timer
check "and is scheduled" contains "$(systemctl list-timers sunstone-update.timer)" sunstone-update.timer
systemctl start sunstone-update.service
check "an unattended update to the broken 0.1.3 fails" \
    equals "$(systemctl is-failed sunstone-update.service)" failed
check "it rolls back, and the journal says so" contains "$(journal)" "rolling back to 0.1.2"
check "0.1.2 answers again" serves 0.1.2
check "the failure is recorded" equals "$(record result) $(record to)" "failed 0.1.3"
check "the next run does not try 0.1.3 again" systemctl start sunstone-update.service
check "and says why" contains "$(journal)" "0.1.3 failed to install last time"
check "0.1.2 is still installed" equals "$(dpkg-query -W -f='${Version}' sunstone)" 0.1.2

echo 0.1.4 >>/tmp/listed
echo 'hold_version = "0.1.2"' >>/etc/sunstone/config.toml
check "held at 0.1.2, a run installs nothing" systemctl start sunstone-update.service
check "and says what is held back" \
    contains "$(journal)" "0.1.4 is out, but updates are held at 0.1.2"
sed -i '/^hold_version/d' /etc/sunstone/config.toml
check "released, a run installs 0.1.4" systemctl start sunstone-update.service
check "0.1.4 answers" serves 0.1.4
check "the update is recorded" equals "$(record result) $(record to)" "updated 0.1.4"
systemctl stop fake-github

section "remove and purge"
check "the package removes" apt_get remove sunstone
check "the service is stopped" test "$(systemctl is-active sunstone.service)" != active
check "the update timer is stopped" \
    test "$(systemctl is-active sunstone-update.timer)" != active
check "/opt/sunstone is gone" test ! -e /opt/sunstone
check "/usr/bin/sunstone is gone" test ! -e /usr/bin/sunstone
check "the configuration is kept" test -s /etc/sunstone/config.toml
check "the saved state is kept" test -s /var/lib/sunstone/state/operations.json
apt-get -o Dpkg::Use-Pty=0 -y purge sunstone >/tmp/purge.log 2>&1
status=$?
check "the package purges" equals "$status" 0
check "purge removes /etc/sunstone" test ! -e /etc/sunstone
check "purge removes self-update's directory" test ! -e /var/lib/sunstone/update
check "purge removes the timer's enablement link" \
    test ! -e /etc/systemd/system/timers.target.wants/sunstone-update.timer
check "purge keeps saved state, and says so" \
    test -s /var/lib/sunstone/state/operations.json -a -n "$(grep 'kept the saved state' /tmp/purge.log)"

finish "systemd-test"
