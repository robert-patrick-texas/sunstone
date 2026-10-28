import fcntl
import hashlib
import http.server
import json
import os
import re
import socket
import socketserver
import ssl
import subprocess
import threading
from collections.abc import Generator, Mapping, Sequence
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sunstone.update.backup import create_backup, list_backups, restore_backup
from sunstone.update.process import RunResult, run_command
from sunstone.update.releases import (
    ReleaseError,
    asset_url,
    https_getter,
    list_releases,
    package_name,
)
from sunstone.update.updater import Paths, UpdateError, Updater
from sunstone.update.verify import SIGNER, Artifacts, VerificationError, verify
from sunstone.update.versions import Version

V = Version.parse


def test_versions_read_every_spelling_and_put_candidates_first() -> None:
    assert V("v1.4.0-rc.1") == V("1.4.0~rc.1") == V("1.4.0.rc.1") == V("1.4.0rc1")
    assert V("1.4.0-rc.2") < V("1.4.0") < V("1.4.1") < V("1.10.0")
    rc = V("1.4.0rc1")
    assert (str(rc), rc.deb, rc.tag) == ("1.4.0-rc.1", "1.4.0~rc.1", "v1.4.0-rc.1")
    with pytest.raises(ValueError):
        V("1.4")


def make_key(directory: Path) -> tuple[Path, Path]:
    """A throwaway release key, and a signers file that trusts it."""
    directory.mkdir(parents=True)
    key = directory / "release"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
    )
    signers = directory / "signers"
    public = key.with_name("release.pub").read_text()
    signers.write_text(f'{SIGNER} namespaces="{SIGNER}" {public}')
    return key, signers


def publish(dest: Path, version: Version, key: Path) -> Artifacts:
    """A release's three files, signed."""
    dest.mkdir(parents=True, exist_ok=True)
    package = dest / package_name(version)
    package.write_bytes(f"sunstone {version}".encode())
    sums = dest / "SHA256SUMS"
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    sums.write_text(f"{digest}  {package.name}\n")
    subprocess.run(
        ["ssh-keygen", "-q", "-Y", "sign", "-f", str(key), "-n", SIGNER, str(sums)],
        check=True,
    )
    return Artifacts(package, sums, dest / "SHA256SUMS.sig")


def test_a_release_verifies_only_with_a_trusted_signature_and_its_checksum(
    tmp_path: Path,
) -> None:
    key, signers = make_key(tmp_path / "key")
    other, _ = make_key(tmp_path / "other")
    good = publish(tmp_path / "good", V("0.2.0"), key)
    verify(good, signers, run_command)

    forged = publish(tmp_path / "forged", V("0.2.0"), other)
    with pytest.raises(VerificationError, match="signature verification failed"):
        verify(forged, signers, run_command)
    good.package.write_bytes(b"tampered")
    with pytest.raises(VerificationError, match="does not match SHA256SUMS"):
        verify(good, signers, run_command)
    signers.write_text("# a placeholder, no key yet\n")
    with pytest.raises(VerificationError, match="lists no key"):
        verify(good, signers, run_command)


def test_releases_are_listed_newest_first_without_drafts_or_other_tags() -> None:
    def asset(name: str) -> dict:
        return {"name": name, "browser_download_url": f"https://dl/{name}"}

    listed = [
        {"tag_name": "v0.2.0-rc.1", "assets": [asset("sunstone_0.2.0.rc.1_amd64.deb")]},
        {"tag_name": "v0.3.0", "draft": True},
        {"tag_name": "nightly"},
        {"tag_name": "v0.2.0", "body": "## Changes", "assets": []},
    ]
    asked = []

    def get(url: str) -> bytes:
        asked.append(url)
        return json.dumps(listed).encode()

    releases = list_releases(get, "o/sunstone", "https://ghe.example/api/v3")
    assert asked == ["https://ghe.example/api/v3/repos/o/sunstone/releases?per_page=30"]
    assert [str(r.version) for r in releases] == ["0.2.0", "0.2.0-rc.1"]
    # GitHub writes a "~" in a file name as ".".
    rc = releases[1]
    assert asset_url(rc, package_name(rc.version)).endswith("0.2.0.rc.1_amd64.deb")


def test_a_backup_puts_configuration_and_state_back_as_they_were(
    tmp_path: Path,
) -> None:
    config, state, backups = tmp_path / "etc", tmp_path / "state", tmp_path / "b"
    for d in (config, state, backups):
        d.mkdir()
    (config / "config.toml").write_text("port = 8000\n")
    (state / "operations.json").write_text("{}")
    sources = {"config": config, "state": state}
    archive = create_backup(sources, backups, datetime_at(0))
    assert archive.stat().st_mode & 0o777 == 0o600

    (config / "config.toml").write_text("port = 9000\n")
    (config / "added.yaml").write_text("x")
    restore_backup(archive, sources)
    assert sorted(p.name for p in config.iterdir()) == ["config.toml"]
    assert (config / "config.toml").read_text() == "port = 8000\n"
    assert (state / "operations.json").read_text() == "{}"

    for minute in range(1, 8):
        create_backup(sources, backups, datetime_at(minute))
    assert len(list_backups(backups)) == 5


def datetime_at(minute: int) -> datetime:
    return datetime(2026, 10, 27, 15, minute, tzinfo=UTC)


class Host:
    """A pretend installed host: GitHub, apt, systemctl, and the service."""

    def __init__(self, tmp: Path, key: Path, signers: Path) -> None:
        self.tmp, self.key = tmp, key
        self.paths = Paths(
            signers=signers,
            binary=tmp / "opt/sunstone",
            config_file=tmp / "etc/config.toml",
            config_dir=tmp / "etc",
            state_dir=tmp / "state",
            update_dir=tmp / "update",
        )
        for d in (self.paths.config_dir, self.paths.state_dir, self.paths.update_dir):
            d.mkdir(parents=True)
        self.paths.config_file.write_text("as the admin left it\n")
        self.current = "0.1.0"
        self.running = True
        self.failed = False
        self.dead: set[str] = set()
        self.calls: list[list[str]] = []
        self.published: dict[Version, Artifacts] = {}
        self.said: list[str] = []
        self.online = True

    def publish(self, version: str, key: Path | None = None) -> None:
        v = V(version)
        self.published[v] = publish(self.tmp / "github" / version, v, key or self.key)

    def get(self, url: str) -> bytes:
        if not self.online:
            raise OSError("no network")
        if url.endswith("/releases?per_page=30"):
            return json.dumps(
                [
                    {
                        "tag_name": v.tag,
                        "body": f"## {v}\n- better",
                        "assets": [
                            {"name": p.name, "browser_download_url": str(p)}
                            for p in (a.package, a.sums, a.sig)
                        ],
                    }
                    for v, a in self.published.items()
                ]
            ).encode()
        return Path(url).read_bytes()

    def run(
        self, args: Sequence[str], stdin: bytes | None, env: Mapping[str, str] | None
    ) -> RunResult:
        args = list(args)
        self.calls.append(args)
        if args[0] == "ssh-keygen":
            return run_command(args, stdin, env)
        if args[:2] == ["apt-get", "install"]:
            found = re.search(r"sunstone_(.+)_amd64\.deb$", args[-1])
            assert found
            self.current = str(V(found[1]))
            # As a package's postinst might.
            self.paths.config_file.write_text(f"rewritten by {self.current}\n")
            return RunResult(0, "")
        if args[:2] == ["systemctl", "is-active"]:
            return RunResult(0 if self.running else 3, "")
        if args[:2] == ["systemctl", "is-failed"]:
            return RunResult(0 if self.failed else 1, "")
        if args[:2] == ["systemctl", "restart"]:
            self.running, self.failed = True, False
        return RunResult(0, "")

    def probe(self, url: str) -> bytes:
        if self.current in self.dead:
            raise OSError("connection refused")
        return json.dumps({"version": self.current}).encode()

    def updater(self, installed: str) -> Updater:
        return Updater(
            paths=self.paths,
            repository="o/sunstone",
            installed=V(installed),
            health_url="http://127.0.0.1:8000/api/version",
            run=self.run,
            get=self.get,
            probe=self.probe,
            say=self.said.append,
            sleep=lambda s: None,
            settle=4,
        )

    def installs(self) -> list[str]:
        return [Path(c[-1]).name for c in self.calls if c[:2] == ["apt-get", "install"]]

    def record(self) -> dict:
        return json.loads((self.paths.update_dir / "last-update.json").read_text())


@pytest.fixture
def host(tmp_path: Path) -> Host:
    key, signers = make_key(tmp_path / "key")
    found = Host(tmp_path, key, signers)
    found.publish("0.1.0")
    return found


def yes(question: str) -> bool:
    return True


def test_check_says_whether_a_newer_release_exists(host: Host) -> None:
    assert host.updater("0.1.0").check() == 0
    host.publish("0.2.0")
    assert host.updater("0.1.0").check() == 0
    assert host.said == [
        "sunstone self-update: up to date: 0.1.0",
        "sunstone self-update: 0.2.0 is available (installed 0.1.0)",
    ]


def test_an_update_verifies_backs_up_installs_and_waits_for_the_new_version(
    host: Host,
) -> None:
    host.publish("0.2.0")
    assert host.updater("0.1.0").update(None, yes) == 0
    assert host.installs() == ["sunstone_0.2.0_amd64.deb"]
    check = [str(host.paths.binary), "check", "--config", str(host.paths.config_file)]
    assert check in host.calls
    assert host.record() | {"at": "", "message": ""} == {
        "result": "updated",
        "from": "0.1.0",
        "to": "0.2.0",
        "at": "",
        "message": "",
    }
    assert len(list_backups(host.paths.update_dir / "backups")) == 1
    # The installed version is kept to roll back to.
    cache = host.paths.update_dir / "cache"
    assert sorted(p.name for p in cache.iterdir()) == ["0.1.0", "0.2.0"]
    assert "sunstone self-update: updated 0.1.0 -> 0.2.0" in host.said
    assert "  - better" in host.said

    # Nothing newer: nothing to do.
    host.calls.clear()
    assert host.updater("0.2.0").update(None, yes) == 0
    assert host.installs() == []


def test_a_release_that_does_not_verify_changes_nothing(
    host: Host, tmp_path: Path
) -> None:
    other, _ = make_key(tmp_path / "other")
    host.publish("0.2.0", key=other)
    assert host.updater("0.1.0").update(None, yes) == 1
    assert host.installs() == []
    assert host.record()["result"] == "refused"
    assert not (host.paths.update_dir / "cache" / "0.2.0").exists()
    assert list_backups(host.paths.update_dir / "backups") == []
    assert host.paths.config_file.read_text() == "as the admin left it\n"


def test_a_failed_update_puts_the_previous_version_and_the_backup_back(
    host: Host,
) -> None:
    host.publish("0.2.0")
    host.dead.add("0.2.0")
    assert host.updater("0.1.0").update(None, yes) == 1
    assert host.installs() == ["sunstone_0.2.0_amd64.deb", "sunstone_0.1.0_amd64.deb"]
    assert host.current == "0.1.0"
    assert host.paths.config_file.read_text() == "as the admin left it\n"
    record = host.record()
    assert (record["result"], record["to"]) == ("failed", "0.2.0")
    assert "did not answer as 0.2.0" in record["message"]
    # Its failed starts must not stop the previous version starting again.
    restart = host.calls[-4:]
    assert ["systemctl", "reset-failed", "sunstone.service"] in restart
    assert ["systemctl", "restart", "sunstone.service"] in restart
    assert "sunstone self-update: 0.1.0 answers again" in host.said


def test_the_timer_installs_newer_releases_but_not_one_that_failed_last_time(
    host: Host,
) -> None:
    host.publish("0.2.0")
    host.dead.add("0.2.0")
    assert host.updater("0.1.0").update(None, yes, unattended=True) == 1
    assert host.current == "0.1.0"

    # Not installed and rolled back again every day.
    host.calls.clear()
    assert host.updater("0.1.0").update(None, yes, unattended=True) == 0
    assert host.installs() == []
    assert host.said[-1] == (
        "sunstone self-update: 0.2.0 failed to install last time, so it is not "
        "tried again until a newer release comes; "
        "sudo sunstone self-update --version 0.2.0 tries it now"
    )
    host.publish("0.2.1")
    assert host.updater("0.1.0").update(None, yes, unattended=True) == 0
    assert host.installs() == ["sunstone_0.2.1_amd64.deb"]


def test_updates_that_pick_the_release_go_no_further_than_the_hold(
    host: Host,
) -> None:
    for version in ("0.2.0", "0.3.0"):
        host.publish(version)
    held = replace(host.updater("0.1.0"), hold=V("0.2.0"))
    assert held.check() == 0
    assert host.said[-1] == (
        "sunstone self-update: 0.2.0 is available (installed 0.1.0); "
        "0.3.0 is out, but updates are held at 0.2.0"
    )
    assert held.update(None, yes, unattended=True) == 0
    assert host.installs() == ["sunstone_0.2.0_amd64.deb"]
    held = replace(host.updater("0.2.0"), hold=V("0.2.0"))
    assert held.update(None, yes, unattended=True) == 0
    assert host.said[-1] == (
        "sunstone self-update: up to date: 0.2.0; "
        "0.3.0 is out, but updates are held at 0.2.0"
    )
    # Named at the console, a newer release still installs.
    assert held.update(V("0.3.0"), yes) == 0
    assert host.current == "0.3.0"


def test_a_service_left_stopped_needs_only_to_pass_its_check(host: Host) -> None:
    host.publish("0.2.0")
    host.running = False
    host.dead.add("0.2.0")
    assert host.updater("0.1.0").update(None, yes) == 0
    assert host.current == "0.2.0"


def test_a_release_copied_by_hand_installs_without_the_network(
    host: Host, tmp_path: Path
) -> None:
    copied = publish(tmp_path / "usb", V("0.2.0"), host.key)
    host.online = False
    updater = host.updater("0.1.0")
    assert updater.install_files(copied.package, copied.sums, copied.sig, yes) == 0
    # Root's own copy is installed, not the one it was given.
    [install] = [c for c in host.calls if c[0] == "apt-get"]
    assert Path(install[-1]).parent == host.paths.update_dir / "cache" / "0.2.0"
    assert any("would restore only configuration and state" in s for s in host.said)


def test_rollback_returns_to_the_version_the_update_came_from(host: Host) -> None:
    host.publish("0.2.0")
    assert host.updater("0.1.0").update(None, yes) == 0
    host.paths.config_file.write_text("edited after the update\n")
    assert host.updater("0.2.0").rollback(yes) == 0
    assert host.installs()[-1] == "sunstone_0.1.0_amd64.deb"
    assert host.current == "0.1.0"
    # As it was before the update; what it was is saved first.
    assert host.paths.config_file.read_text() == "as the admin left it\n"
    backups = host.paths.update_dir / "backups"
    assert len(list_backups(backups, "pre-rollback")) == 1
    assert host.record()["result"] == "rolled-back"


def test_rollback_after_a_downgrade_returns_to_the_newer_version(host: Host) -> None:
    host.publish("0.2.0")
    assert host.updater("0.1.0").update(None, yes) == 0
    assert host.updater("0.2.0").update(V("0.1.0"), yes) == 0
    assert host.updater("0.1.0").rollback(yes) == 0
    assert host.current == "0.2.0"


def test_rollback_starts_a_service_the_broken_version_left_failed(
    host: Host,
) -> None:
    host.publish("0.2.0")
    assert host.updater("0.1.0").update(None, yes) == 0
    host.running, host.failed = False, True
    assert host.updater("0.2.0").rollback(yes) == 0
    assert ["systemctl", "restart", "sunstone.service"] in host.calls
    assert host.running and host.current == "0.1.0"


def test_nothing_happens_when_declined_or_while_another_update_runs(
    host: Host,
) -> None:
    host.publish("0.2.0")
    assert host.updater("0.1.0").update(None, lambda q: False) == 1
    assert host.installs() == []
    lock = host.paths.update_dir / "self-update.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with pytest.raises(UpdateError, match="already running"):
            host.updater("0.1.0").update(None, yes)
    finally:
        os.close(fd)
    assert host.installs() == []


def openssl(*args: str | Path) -> None:
    subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True)


def make_ca(directory: Path, name: str, strict: bool = True) -> Path:
    """A test CA, issuing a certificate for 127.0.0.1 kept beside it.

    With ``strict`` False the CA lacks ``keyUsage``, as many inspection
    CAs issued before clients enforced the strict X.509 profile do.
    """
    directory.mkdir(parents=True, exist_ok=True)
    usage = "keyUsage = critical,keyCertSign,cRLSign\n" if strict else ""
    (directory / f"{name}.cnf").write_text(
        "[req]\ndistinguished_name = dn\nprompt = no\n"
        f"[dn]\nCN = {name}\n"
        "[ext]\nbasicConstraints = critical,CA:TRUE\n"
        f"subjectKeyIdentifier = hash\n{usage}"
    )
    (directory / "server.ext").write_text(
        "subjectAltName = IP:127.0.0.1\nbasicConstraints = CA:FALSE\n"
        "keyUsage = critical,digitalSignature\nextendedKeyUsage = serverAuth\n"
        "authorityKeyIdentifier = keyid\nsubjectKeyIdentifier = hash\n"
    )
    ca, key = directory / f"{name}.pem", directory / f"{name}.key"
    ec = ("-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes")
    openssl(
        "req",
        "-x509",
        "-config",
        directory / f"{name}.cnf",
        "-extensions",
        "ext",
        *ec,
        "-keyout",
        key,
        "-out",
        ca,
        "-days",
        "2",
    )
    csr = directory / f"{name}-server.csr"
    openssl(
        "req",
        "-new",
        *ec,
        "-keyout",
        directory / f"{name}-server.key",
        "-out",
        csr,
        "-subj",
        "/CN=127.0.0.1",
    )
    openssl(
        "x509",
        "-req",
        "-in",
        csr,
        "-CA",
        ca,
        "-CAkey",
        key,
        "-set_serial",
        "2",
        "-days",
        "2",
        "-out",
        directory / f"{name}-server.pem",
        "-extfile",
        directory / "server.ext",
    )
    return ca


@pytest.fixture
def served(tmp_path: Path) -> Generator[tuple[Path, str]]:
    """An HTTPS server whose certificate only the CA ``strict-ca`` vouches for."""
    ca = make_ca(tmp_path / "pki", "strict-ca")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        ca.with_name("strict-ca-server.pem"), ca.with_name("strict-ca-server.key")
    )

    class Releases(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Releases)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield ca, f"https://127.0.0.1:{server.server_port}/releases"
    server.shutdown()


def test_releases_come_over_https_trusting_the_ca_directory_too(
    served: tuple[Path, str], tmp_path: Path
) -> None:
    ca, url = served
    trusted = tmp_path / "ca.d"
    trusted.mkdir()
    with pytest.raises(ReleaseError) as refused:
        https_getter(trusted)(url)
    assert str(refused.value) == (
        f"{url}: certificate not trusted: unable to get local issuer certificate; "
        f"behind a proxy that inspects TLS, put its CA certificate in {trusted}"
    )
    (trusted / "corp-inspection.pem").write_bytes(ca.read_bytes())
    assert https_getter(trusted)(url) == b"[]"

    (trusted / "README").write_text("only .pem and .crt files are read\n")
    (trusted / "broken.crt").write_text("not a certificate\n")
    with pytest.raises(ReleaseError, match=f"^{trusted / 'broken.crt'}: not a PEM"):
        https_getter(trusted)


def test_an_older_inspection_ca_needs_the_strict_profile_relaxed(
    tmp_path: Path,
) -> None:
    ca = make_ca(tmp_path / "pki", "legacy-ca", strict=False)
    trusted = tmp_path / "ca.d"
    trusted.mkdir()
    (trusted / "legacy.pem").write_bytes(ca.read_bytes())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        ca.with_name("legacy-ca-server.pem"), ca.with_name("legacy-ca-server.key")
    )
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler
    )
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"https://127.0.0.1:{server.server_port}/missing"
    try:
        with pytest.raises(ReleaseError) as refused:
            https_getter(trusted)(url)
        assert str(refused.value) == (
            f"{url}: certificate not trusted: CA cert does not include key usage "
            "extension; if legacy.pem is the inspecting proxy's CA, it may not meet "
            "the strict X.509 profile: tls_strict_x509 = false in [update] accepts it"
        )
        # Relaxed, the certificate is trusted, and the server answers.
        with pytest.raises(ReleaseError, match="HTTP 404"):
            https_getter(trusted, strict=False)(url)
    finally:
        server.shutdown()


def test_releases_come_through_the_configured_proxy(
    served: tuple[Path, str], tmp_path: Path
) -> None:
    ca, url = served
    trusted = tmp_path / "ca.d"
    trusted.mkdir()
    (trusted / "ca.pem").write_bytes(ca.read_bytes())
    asked: list[bytes] = []

    def pump(source: socket.socket, sink: socket.socket) -> None:
        with suppress(OSError):
            while data := source.recv(65536):
                sink.sendall(data)
        with suppress(OSError):
            sink.shutdown(socket.SHUT_WR)

    class Tunnel(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            request = self.rfile.readline()
            asked.append(request)
            while self.rfile.readline() not in (b"\r\n", b""):
                pass
            host, port = request.split()[1].decode().rsplit(":", 1)
            with socket.create_connection((host, int(port))) as upstream:
                self.connection.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                back = threading.Thread(target=pump, args=(upstream, self.connection))
                back.start()
                pump(self.connection, upstream)
                back.join()

    proxy = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Tunnel)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        get = https_getter(trusted, proxy=f"http://127.0.0.1:{proxy.server_address[1]}")
        assert get(url) == b"[]"
        port = url.split(":")[2].split("/")[0]
        assert asked == [f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n".encode()]
    finally:
        proxy.shutdown()
