import os
import stat
import sys


_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _pkexec_owner():
    if not sys.platform.startswith("linux") or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None

    raw_uid = os.environ.get("PKEXEC_UID", "")
    if not raw_uid.isdecimal():
        return None
    uid = int(raw_uid)
    if uid <= 0:
        return None

    try:
        import pwd

        account = pwd.getpwuid(uid)
    except (ImportError, KeyError):
        return None
    return uid, account.pw_gid


def _fchown_if_needed(descriptor, owner):
    uid, gid = owner
    try:
        os.fchown(descriptor, uid, gid)
    except OSError:
        # Some mounted filesystems expose synthetic ownership and reject chown.
        stat = os.fstat(descriptor)
        if stat.st_uid != uid or stat.st_gid != gid:
            raise


def set_pkexec_user_ownership_fd(descriptor):
    """Assign ownership through an already-open descriptor, never a path."""
    owner = _pkexec_owner()
    if owner is None:
        return False
    _fchown_if_needed(descriptor, owner)
    return True


def _absolute_parts(path):
    absolute = os.path.abspath(os.fspath(path))
    return absolute, tuple(part for part in absolute.split(os.sep) if part)


def _open_directory(path, *, create, owner):
    """Walk an absolute path with dir-fds and O_NOFOLLOW for every component."""
    absolute, parts = _absolute_parts(path)
    descriptor = os.open(os.sep, _DIRECTORY_FLAGS)
    try:
        for part in parts:
            created = False
            try:
                child = os.open(part, _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o777, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    # A competing creator is safe only if the next no-follow open
                    # confirms this component is a directory, not a symlink.
                    pass
                child = os.open(part, _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=descriptor)
            try:
                if created and owner is not None:
                    _fchown_if_needed(child, owner)
            except BaseException:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def ensure_pkexec_user_owned_directory(path):
    """Create missing directories without following symlinks and own them safely."""
    owner = _pkexec_owner()
    if not sys.platform.startswith("linux") or os.open not in os.supports_dir_fd:
        os.makedirs(path, exist_ok=True)
        return False

    descriptor = _open_directory(path, create=True, owner=owner)
    os.close(descriptor)
    return owner is not None


def open_pkexec_safe_directory(path):
    """Open a directory without following any symlink in its absolute path."""
    return _open_directory(path, create=False, owner=None)


def set_pkexec_user_ownership(path):
    """Safely own a path by opening every component without following symlinks."""
    owner = _pkexec_owner()
    if owner is None:
        return False

    absolute, parts = _absolute_parts(path)
    if not parts:
        raise ValueError("Refusing to change ownership of the filesystem root")
    parent = os.path.dirname(absolute) or os.sep
    parent_fd = _open_directory(parent, create=False, owner=None)
    try:
        descriptor = os.open(
            parts[-1], os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0) | _NOFOLLOW,
            dir_fd=parent_fd,
        )
    finally:
        os.close(parent_fd)
    try:
        mode = os.fstat(descriptor).st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise OSError("Ownership can only be changed for regular files and directories")
        _fchown_if_needed(descriptor, owner)
    finally:
        os.close(descriptor)
    return True
