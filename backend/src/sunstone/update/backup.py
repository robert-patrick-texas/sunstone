"""Backups of the configuration and saved state, taken before an update.

Each backup is one ``.tar.gz`` holding ``/etc/sunstone`` and the state
directory, written at mode 0600 and kept five at a time. Saved files are
each replaced whole when they change, so each is copied as it was before or
after a change, never half written. A restore puts each directory back by
renaming it into place, with the owners and modes recorded.
"""

import os
import shutil
import tarfile
from datetime import datetime
from pathlib import Path

KEPT = 5


class BackupError(Exception):
    """A backup cannot be written, or is not safe to restore."""


def create_backup(
    sources: dict[str, Path], backups: Path, now: datetime, prefix: str = "pre-update"
) -> Path:
    """Archive some directories.

    Args:
        sources: Name in the archive to directory; missing ones are left out.
        backups: Where backups go.
        now: When, for the file name.
        prefix: ``pre-update`` or ``pre-rollback``.

    Returns:
        The archive, such as ``pre-update-20261027T150000Z.tar.gz``.

    Raises:
        BackupError: If it cannot be written.
    """
    final = backups / f"{prefix}-{now:%Y%m%dT%H%M%SZ}.tar.gz"
    part = final.with_name(final.name + ".part")
    try:
        part.unlink(missing_ok=True)
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w:gz") as tar:
            for name, path in sources.items():
                if path.exists():
                    tar.add(path, arcname=name)
        os.replace(part, final)
    except OSError as e:
        raise BackupError(f"cannot write {final}: {e}") from e
    for old in list_backups(backups, prefix)[KEPT:]:
        old.unlink(missing_ok=True)
    return final


def list_backups(backups: Path, prefix: str = "pre-update") -> list[Path]:
    """Backups of one kind, newest first.

    Args:
        backups: Where backups are.
        prefix: ``pre-update`` or ``pre-rollback``.

    Returns:
        The archives.

    Raises:
        None
    """
    return sorted(backups.glob(f"{prefix}-*.tar.gz"), reverse=True)


def restore_backup(archive: Path, targets: dict[str, Path]) -> None:
    """Put archived directories back in place of the current ones.

    Args:
        archive: A backup.
        targets: Name in the archive to the directory it replaces; a name the
            archive lacks leaves its directory as it is.

    Raises:
        BackupError: If the archive is a link, or is writable by others (or,
            for root, owned by anyone else), or cannot be read or extracted.
    """
    info = archive.lstat()
    if not archive.is_file() or archive.is_symlink() or info.st_mode & 0o022:
        raise BackupError(f"{archive} is not a backup this updater wrote")
    if os.geteuid() == 0 and info.st_uid != 0:
        raise BackupError(f"{archive} is not owned by root")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for name, target in targets.items():
                mine = [
                    m
                    for m in members
                    if m.name == name or m.name.startswith(name + "/")
                ]
                if mine:
                    _swap_in(tar, mine, name, target)
    except (OSError, tarfile.TarError) as e:
        raise BackupError(f"cannot restore {archive}: {e}") from e


def _swap_in(
    tar: tarfile.TarFile, members: list[tarfile.TarInfo], name: str, target: Path
) -> None:
    """Extract one archived directory beside its target, then rename it in."""
    incoming = target.with_name(f".{target.name}.incoming")
    old = target.with_name(f".{target.name}.old")
    shutil.rmtree(incoming, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)

    def renamed(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
        moved = member.replace(name=incoming.name + member.name[len(name) :])
        return tarfile.tar_filter(moved, path)

    tar.extractall(target.parent, members=members, numeric_owner=True, filter=renamed)
    if target.exists():
        target.rename(old)
    incoming.rename(target)
    shutil.rmtree(old, ignore_errors=True)
