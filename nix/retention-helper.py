from __future__ import annotations

import argparse
import datetime
import errno
import os
import secrets
import stat
import sys
from pathlib import PurePosixPath
from typing import Callable


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_PATH_FLAGS = getattr(os, "O_PATH", os.O_RDONLY) | os.O_CLOEXEC | os.O_NOFOLLOW


class RetentionError(RuntimeError):
    pass


def _relative_parts(value: str) -> tuple[str, ...]:
    path = PurePosixPath(value)
    if not value or value == "." or path.is_absolute():
        raise RetentionError("target must be a non-empty relative path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise RetentionError("parent traversal and empty path components are not allowed")
    if path.parts[0] == ".quarantine":
        raise RetentionError("target is already in quarantine")
    return path.parts


def _open_directory(path: str) -> int:
    try:
        return os.open(path, _DIRECTORY_FLAGS)
    except OSError as error:
        raise RetentionError(f"cannot safely open directory {path!r}: {error.strerror}") from error


def _open_child_directory(parent_fd: int, name: str) -> int:
    try:
        return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        raise RetentionError(
            f"cannot safely open directory component {name!r}: {error.strerror}"
        ) from error


def _open_parent(root_fd: int, parts: tuple[str, ...]) -> tuple[int, str]:
    current_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = _open_child_directory(current_fd, part)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd, parts[-1]
    except BaseException:
        os.close(current_fd)
        raise


def _ensure_quarantine(media_fd: int) -> int:
    try:
        os.mkdir(".quarantine", mode=0o750, dir_fd=media_fd)
    except FileExistsError:
        pass
    return _open_child_directory(media_fd, ".quarantine")


def _new_bucket(quarantine_fd: int) -> tuple[int, str]:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for _ in range(128):
        name = f"{stamp}-{secrets.token_hex(6)}"
        try:
            os.mkdir(name, mode=0o750, dir_fd=quarantine_fd)
        except FileExistsError:
            continue
        return _open_child_directory(quarantine_fd, name), name
    raise RetentionError("could not allocate a unique quarantine directory")


def _open_audit(data_fd: int) -> int:
    flags = os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        audit_fd = os.open("deletion-audit.log", flags, dir_fd=data_fd)
    except OSError as error:
        raise RetentionError(
            f"cannot safely open deletion-audit.log: {error.strerror}"
        ) from error
    audit_stat = os.fstat(audit_fd)
    if not stat.S_ISREG(audit_stat.st_mode):
        os.close(audit_fd)
        raise RetentionError("deletion-audit.log is not a regular file")
    return audit_fd


def _audit(audit_fd: int, event: str, details: str) -> None:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    user = os.environ.get("SUDO_USER") or os.environ.get("USER") or "unknown"
    line = f"{stamp} {event} user={user!r} {details}\n".encode()
    os.write(audit_fd, line)
    os.fsync(audit_fd)


def quarantine(
    data_root: str,
    relative_target: str,
    hook: Callable[[str], None] | None = None,
) -> str:
    parts = _relative_parts(relative_target)
    data_fd = _open_directory(data_root)
    media_fd = parent_fd = target_fd = quarantine_fd = bucket_fd = audit_fd = -1
    try:
        media_fd = _open_child_directory(data_fd, "media")
        parent_fd, target_name = _open_parent(media_fd, parts)
        try:
            target_fd = os.open(target_name, _PATH_FLAGS, dir_fd=parent_fd)
        except OSError as error:
            raise RetentionError(
                f"cannot safely open target {relative_target!r}: {error.strerror}"
            ) from error
        before = os.fstat(target_fd)
        if stat.S_ISLNK(before.st_mode):
            raise RetentionError("symbolic-link targets are not accepted")

        quarantine_fd = _ensure_quarantine(media_fd)
        bucket_fd, bucket_name = _new_bucket(quarantine_fd)
        audit_fd = _open_audit(data_fd)
        if hook is not None:
            hook("before_rename")

        os.rename(
            target_name,
            target_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=bucket_fd,
        )
        after = os.stat(target_name, dir_fd=bucket_fd, follow_symlinks=False)
        if (before.st_dev, before.st_ino, stat.S_IFMT(before.st_mode)) != (
            after.st_dev,
            after.st_ino,
            stat.S_IFMT(after.st_mode),
        ):
            _audit(
                audit_fd,
                "DELETE_RACE_QUARANTINED",
                f"src={relative_target!r} quarantined_at={bucket_name + '/' + target_name!r}",
            )
            raise RetentionError(
                "target changed during quarantine; the raced entry remains quarantined"
            )

        destination = f".quarantine/{bucket_name}/{target_name}"
        _audit(
            audit_fd,
            "DELETE_REQUESTED",
            f"src={relative_target!r} quarantined_at={destination!r}",
        )
        return destination
    finally:
        for descriptor in (
            audit_fd,
            bucket_fd,
            quarantine_fd,
            target_fd,
            parent_fd,
            media_fd,
            data_fd,
        ):
            if descriptor >= 0:
                os.close(descriptor)


def _remove_tree(parent_fd: int, name: str) -> None:
    entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(entry.st_mode):
        os.unlink(name, dir_fd=parent_fd)
        return

    child_fd = _open_child_directory(parent_fd, name)
    try:
        for child in os.listdir(child_fd):
            if child in {".", ".."}:
                continue
            _remove_tree(child_fd, child)
    finally:
        os.close(child_fd)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except OSError as error:
        if error.errno in {errno.ENOTDIR, errno.ELOOP}:
            raise RetentionError(
                f"quarantine entry {name!r} changed during purge; refusing"
            ) from error
        raise


def list_quarantine(data_root: str) -> list[str]:
    data_fd = _open_directory(data_root)
    media_fd = quarantine_fd = -1
    try:
        media_fd = _open_child_directory(data_fd, "media")
        quarantine_fd = _ensure_quarantine(media_fd)
        return sorted(os.listdir(quarantine_fd))
    finally:
        for descriptor in (quarantine_fd, media_fd, data_fd):
            if descriptor >= 0:
                os.close(descriptor)


def purge(data_root: str) -> list[str]:
    data_fd = _open_directory(data_root)
    media_fd = quarantine_fd = audit_fd = -1
    try:
        media_fd = _open_child_directory(data_fd, "media")
        quarantine_fd = _ensure_quarantine(media_fd)
        entries = sorted(os.listdir(quarantine_fd))
        if not entries:
            return []
        audit_fd = _open_audit(data_fd)
        _audit(audit_fd, "DELETE_PURGE_STARTED", f"items={entries!r}")
        for entry in entries:
            _remove_tree(quarantine_fd, entry)
        for entry in entries:
            _audit(audit_fd, "DELETE_PURGED", f"item={entry!r}")
        return entries
    finally:
        for descriptor in (audit_fd, quarantine_fd, media_fd, data_fd):
            if descriptor >= 0:
                os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    quarantine_parser = subparsers.add_parser("quarantine")
    quarantine_parser.add_argument("target")
    subparsers.add_parser("list")
    subparsers.add_parser("purge")
    arguments = parser.parse_args()
    try:
        if arguments.command == "quarantine":
            destination = quarantine(arguments.data_root, arguments.target)
            print(destination)
        elif arguments.command == "list":
            for entry in list_quarantine(arguments.data_root):
                print(entry)
        else:
            for entry in purge(arguments.data_root):
                print(entry)
    except (OSError, RetentionError) as error:
        print(f"ai-coaching retention: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
