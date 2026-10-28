"""The update: find, download, verify, back up, install, check, and roll back.

Nothing changes before a release verifies. Then the configuration and
saved state are backed up, the package is installed with apt (whose
``postinst`` restarts the service if it was running), and the new version
must pass ``sunstone check`` and, if the service was running, answer as the
new version. If any of that fails, the previous package (cached and
verified beforehand) goes back in, with the backup.

Everything lives in the update directory, ``/var/lib/sunstone/update``,
which only root may write, so the service account cannot plant a backup or
package for root to restore: ``cache/<version>/`` (the installed version,
the one it came from, and the newest other are kept), ``backups/`` (five of
each kind), the record of the last update, and the lock.
"""

import fcntl
import json
import os
import re
import shutil
import stat
import time
import urllib.request
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sunstone.update.backup import (
    BackupError,
    create_backup,
    list_backups,
    restore_backup,
)
from sunstone.update.process import Runner, run_command
from sunstone.update.releases import (
    Getter,
    Release,
    ReleaseError,
    asset_url,
    https_get,
    list_releases,
    package_name,
)
from sunstone.update.verify import Artifacts, VerificationError, verify
from sunstone.update.versions import Version

SERVICE = "sunstone.service"
# How long the restarted service has to answer as the new version.
SETTLE_S = 90.0
# Cached releases kept besides the installed one and the one it came from.
KEEP_OTHERS = 1
SUMS, SIG = "SHA256SUMS", "SHA256SUMS.sig"
_PACKAGE = re.compile(r"^sunstone_(.+)_amd64\.deb$")


class UpdateError(Exception):
    """The update cannot start: another is running, or its directory is unsafe."""


class _Failed(Exception):
    """A step after the install began failed, so the update rolls back."""


@dataclass(frozen=True)
class Paths:
    """Where an installed Sunstone keeps what an update touches."""

    signers: Path
    binary: Path
    """The installed ``sunstone``, run after an install to check it."""
    config_file: Path
    config_dir: Path
    state_dir: Path
    update_dir: Path

    @property
    def cache(self) -> Path:
        """Downloaded and verified packages, by version."""
        return self.update_dir / "cache"

    @property
    def backups(self) -> Path:
        """Pre-update and pre-rollback archives."""
        return self.update_dir / "backups"


INSTALLED = Paths(
    signers=Path("/opt/sunstone/share/release-signers"),
    binary=Path("/opt/sunstone/venv/bin/sunstone"),
    config_file=Path("/etc/sunstone/config.toml"),
    config_dir=Path("/etc/sunstone"),
    state_dir=Path("/var/lib/sunstone/state"),
    update_dir=Path("/var/lib/sunstone/update"),
)


def local_get(url: str) -> bytes:
    """Ask the local service something, briefly.

    Args:
        url: An ``http://`` URL on this host.

    Returns:
        The body.

    Raises:
        OSError: If it does not answer.
    """
    with urllib.request.urlopen(url, timeout=5) as answer:
        return answer.read(65536)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Updater:
    """Updates and rolls back one installation; its collaborators can be replaced."""

    paths: Paths
    repository: str
    installed: Version
    health_url: str
    """The service's ``/api/version``."""
    run: Runner = run_command
    get: Getter = https_get
    probe: Getter = local_get
    say: Callable[[str], None] = print
    now: Callable[[], datetime] = _now
    sleep: Callable[[float], None] = time.sleep
    settle: float = SETTLE_S

    def check(self) -> int:
        """Say whether a newer release exists, changing nothing.

        Returns:
            0 once the check completed, whatever it found; 1 if releases
            could not be listed.

        Raises:
            None
        """
        try:
            releases = list_releases(self.get, self.repository)
        except ReleaseError as e:
            self.say(f"sunstone self-update: cannot list releases: {e}")
            return 1
        if not releases:
            self.say(f"sunstone self-update: {self.repository} has no releases yet")
        elif releases[0].version > self.installed:
            newest = releases[0].version
            self.say(
                f"sunstone self-update: {newest} is available "
                f"(installed {self.installed})"
            )
        else:
            self.say(f"sunstone self-update: up to date: {self.installed}")
        return 0

    def update(self, target: Version | None, confirm: Callable[[str], bool]) -> int:
        """Install the newest release if it is newer, or a given one.

        Args:
            target: A release to install even if older or the same, or None
                for the newest, only if newer.
            confirm: Asks whether to go ahead.

        Returns:
            0 when updated or already up to date; 1 when declined, refused,
            failed and rolled back, or releases could not be fetched.

        Raises:
            UpdateError: If another update is running, or the update
                directory is not safe.
        """
        try:
            releases = list_releases(self.get, self.repository)
        except ReleaseError as e:
            self.say(f"sunstone self-update: cannot list releases: {e}")
            return 1
        if target is None:
            if not releases or releases[0].version <= self.installed:
                self.say(f"sunstone self-update: up to date: {self.installed}")
                return 0
            release = releases[0]
        else:
            found = [r for r in releases if r.version == target]
            if not found:
                self.say(f"sunstone self-update: no release {target} found")
                return 1
            release = found[0]
        if not confirm(
            f"Install Sunstone {release.version} (installed {self.installed})?"
        ):
            self.say("sunstone self-update: nothing installed")
            return 1
        with self._locked():
            try:
                artifacts = self._download(release)
            except ReleaseError as e:
                self.say(f"sunstone self-update: download failed: {e}")
                return 1
            return self._apply(release.version, artifacts, release.notes, releases)

    def install_files(
        self, package: Path, sums: Path, sig: Path, confirm: Callable[[str], bool]
    ) -> int:
        """Install a release copied to this host by hand.

        Args:
            package: ``sunstone_<version>_amd64.deb``.
            sums: Its ``SHA256SUMS``.
            sig: ``SHA256SUMS.sig``.
            confirm: Asks whether to go ahead.

        Returns:
            0 when updated; 1 when declined, refused, or failed and rolled
            back; 2 when the package's name is not a release's.

        Raises:
            UpdateError: If another update is running, or the update
                directory is not safe.
        """
        named = _PACKAGE.match(package.name)
        try:
            version = Version.parse(named[1] if named else "")
        except ValueError:
            self.say(f"sunstone self-update: {package.name} is not a release package")
            return 2
        if not confirm(f"Install Sunstone {version} (installed {self.installed})?"):
            self.say("sunstone self-update: nothing installed")
            return 1
        with self._locked():
            # Verified and installed from root's own copy, which no one else can swap.
            dest = self._fresh(version)
            for source, name in (
                (package, package_name(version)),
                (sums, SUMS),
                (sig, SIG),
            ):
                shutil.copyfile(source, dest / name)
            return self._apply(version, _artifacts(dest, version), "", None)

    def rollback(self, confirm: Callable[[str], bool]) -> int:
        """Go back to the version the last update came from, with its backup.

        Returns:
            0 when rolled back; 1 when there is nothing to go back to, or it
            was declined, refused, or failed.

        Raises:
            UpdateError: If another update is running, or the update
                directory is not safe.
        """
        target = self._rollback_target()
        if target is None:
            self.say("sunstone self-update: no older verified package is cached")
            return 1
        backups = list_backups(self.paths.backups)
        question = f"Roll back Sunstone {self.installed} to {target}?"
        if backups:
            question += (
                f" Configuration and state go back to {backups[0].name}; "
                "today's are saved first."
            )
        if not confirm(question):
            self.say("sunstone self-update: nothing changed")
            return 1
        with self._locked():
            artifacts = _artifacts(self.paths.cache / str(target), target)
            # Rolled back because this version fails, the service may be failed.
            wanted = self._wanted()
            try:
                verify(artifacts, self.paths.signers, self.run)
                create_backup(
                    self._sources(), self.paths.backups, self.now(), "pre-rollback"
                )
                self._install(artifacts.package)
                if backups:
                    restore_backup(backups[0], self._sources())
                if wanted:
                    self._restart()
                self._check(target, wanted)
            except (VerificationError, BackupError, _Failed) as e:
                self._record("failed", target, str(e))
                self.say(f"sunstone self-update: rollback failed: {e}")
                return 1
            self._record("rolled-back", target, "")
            self.say(f"sunstone self-update: rolled back {self.installed} -> {target}")
            return 0

    def _apply(
        self,
        version: Version,
        artifacts: Artifacts,
        notes: str,
        releases: Sequence[Release] | None,
    ) -> int:
        """Verify, back up, install, and check one release, or roll back."""
        try:
            verify(artifacts, self.paths.signers, self.run)
        except VerificationError as e:
            shutil.rmtree(artifacts.package.parent, ignore_errors=True)
            self._record("refused", version, str(e))
            self.say(f"sunstone self-update: {e}; nothing changed")
            return 1
        previous = self._previous(releases)
        try:
            backup = create_backup(self._sources(), self.paths.backups, self.now())
        except BackupError as e:
            self._record("failed", version, str(e))
            self.say(f"sunstone self-update: {e}; nothing changed")
            return 1
        was_running = self._running()
        if was_running:
            # So that the restart is not refused for earlier failed starts.
            self.run(["systemctl", "reset-failed", SERVICE], None, None)
        try:
            self._install(artifacts.package)
            self._check(version, was_running)
        except _Failed as e:
            self.say(f"sunstone self-update: {version} failed: {e}")
            self._roll_back(previous, backup, was_running)
            self._record("failed", version, str(e))
            return 1
        self._record("updated", version, "")
        self._prune(version)
        self.say(f"sunstone self-update: updated {self.installed} -> {version}")
        excerpt = [line for line in notes.splitlines() if line.strip()][:12]
        if excerpt:
            self.say(f"release notes ({version}):")
            for line in excerpt:
                self.say(f"  {line}")
        return 0

    def _previous(self, releases: Sequence[Release] | None) -> Artifacts | None:
        """A verified package of the installed version, to roll back to."""
        dest = self.paths.cache / str(self.installed)
        artifacts = _artifacts(dest, self.installed)
        complete = all(
            p.is_file() for p in (artifacts.package, artifacts.sums, artifacts.sig)
        )
        if not complete and releases is not None:
            found = [r for r in releases if r.version == self.installed]
            try:
                artifacts = self._download(found[0]) if found else artifacts
            except ReleaseError:
                pass
        try:
            verify(artifacts, self.paths.signers, self.run)
            return artifacts
        except VerificationError, OSError:
            self.say(
                f"sunstone self-update: no verified package of {self.installed} "
                "is at hand; a rollback would restore only configuration and state"
            )
            return None

    def _download(self, release: Release) -> Artifacts:
        dest = self._fresh(release.version)
        for name in (package_name(release.version), SUMS, SIG):
            (dest / name).write_bytes(self.get(asset_url(release, name)))
        return _artifacts(dest, release.version)

    def _fresh(self, version: Version) -> Path:
        dest = self.paths.cache / str(version)
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(mode=0o700)
        return dest

    def _install(self, package: Path) -> None:
        done = self.run(
            ["apt-get", "install", "-y", "--allow-downgrades", str(package)],
            None,
            {"DEBIAN_FRONTEND": "noninteractive"},
        )
        if done.code != 0:
            raise _Failed(f"apt-get install failed: {_tail(done.output)}")

    def _running(self) -> bool:
        return self._systemctl("is-active", "--quiet") == 0

    def _wanted(self) -> bool:
        """Whether the service is meant to run: running, or failed trying to."""
        return self._running() or self._systemctl("is-failed", "--quiet") == 0

    def _restart(self) -> None:
        # Failed starts use up systemd's start limit, which would refuse this one.
        self._systemctl("reset-failed")
        self._systemctl("restart")

    def _systemctl(self, *args: str) -> int:
        return self.run(["systemctl", *args, SERVICE], None, None).code

    def _check(self, version: Version, was_running: bool) -> None:
        """The new version must load everything, and answer if it was running."""
        checked = self.run(
            [str(self.paths.binary), "check", "--config", str(self.paths.config_file)],
            None,
            None,
        )
        if checked.code != 0:
            raise _Failed(f"sunstone check failed: {_tail(checked.output)}")
        if not was_running:
            self.say(f"sunstone self-update: {SERVICE} was not running; left stopped")
            return
        last = "no answer"
        for _ in range(int(self.settle // 2) + 1):
            try:
                answered = json.loads(self.probe(self.health_url))["version"]
                if Version.parse(answered) == version:
                    return
                last = f"it answers as {answered}"
            except (OSError, ValueError, KeyError, TypeError) as e:
                last = str(e)
            self.sleep(2)
        raise _Failed(
            f"{SERVICE} did not answer as {version} within {self.settle:g} s ({last})"
        )

    def _roll_back(
        self, previous: Artifacts | None, backup: Path, was_running: bool
    ) -> None:
        self.say(f"sunstone self-update: rolling back to {self.installed}")
        if previous is not None:
            try:
                self._install(previous.package)
            except _Failed as e:
                self.say(f"sunstone self-update: reinstalling {self.installed}: {e}")
        try:
            restore_backup(backup, self._sources())
        except BackupError as e:
            self.say(f"sunstone self-update: {e}")
        if not was_running:
            return
        self._restart()
        try:
            self._check(self.installed, True)
            self.say(f"sunstone self-update: {self.installed} answers again")
        except _Failed as e:
            self.say(f"sunstone self-update: after the rollback, {e}")

    def _rollback_target(self) -> Version | None:
        """Where the last update came from, or the newest older cached version."""
        try:
            record = json.loads(
                (self.paths.update_dir / "last-update.json").read_text()
            )
            came_from = Version.parse(record["from"])
            updated = record.get("result") == "updated"
            if updated and record.get("to") == str(self.installed):
                if came_from in self._cached():
                    return came_from
        except OSError, ValueError, KeyError, TypeError:
            pass
        older = [v for v in self._cached() if v < self.installed]
        return max(older, default=None)

    def _cached(self) -> list[Version]:
        """Versions whose three files are all in the cache."""
        found = []
        for path in self.paths.cache.glob("*"):
            try:
                version = Version.parse(path.name)
            except ValueError:
                continue
            files = _artifacts(path, version)
            if all(p.is_file() for p in (files.package, files.sums, files.sig)):
                found.append(version)
        return found

    def _prune(self, current: Version) -> None:
        """Keep the new version, the one it replaced, and the newest other."""
        keep = {current, self.installed}
        others = sorted((v for v in self._cached() if v not in keep), reverse=True)
        for v in others[KEEP_OTHERS:]:
            shutil.rmtree(self.paths.cache / str(v), ignore_errors=True)

    def _sources(self) -> dict[str, Path]:
        return {"config": self.paths.config_dir, "state": self.paths.state_dir}

    def _record(self, result: str, version: Version, message: str) -> None:
        record = {
            "result": result,
            "from": str(self.installed),
            "to": str(version),
            "at": self.now().isoformat(),
            "message": message,
        }
        path = self.paths.update_dir / "last-update.json"
        part = path.with_name(path.name + ".part")
        part.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        os.replace(part, path)

    @contextmanager
    def _locked(self) -> Generator[None]:
        """Check the update directory is root's alone, and hold the lock."""
        home = self.paths.update_dir
        try:
            info = home.lstat()
        except FileNotFoundError as e:
            raise UpdateError(f"{home} is missing; reinstall the package") from e
        if not stat.S_ISDIR(info.st_mode):
            raise UpdateError(f"{home} is not a directory")
        if os.geteuid() == 0 and (info.st_uid != 0 or info.st_mode & 0o022):
            raise UpdateError(f"{home} must be owned, and writable, only by root")
        for sub in (self.paths.cache, self.paths.backups):
            sub.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(
            home / "self-update.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise UpdateError("another update is already running") from e
            yield
        finally:
            os.close(fd)


def _artifacts(dest: Path, version: Version) -> Artifacts:
    return Artifacts(dest / package_name(version), dest / SUMS, dest / SIG)


def _tail(output: str) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return " / ".join(lines[-3:]) or "no output"
