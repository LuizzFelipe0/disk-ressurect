import os
import sys


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


def set_pkexec_user_ownership(path):
    """Make a newly created file or directory belong to the user who authorized pkexec."""
    owner = _pkexec_owner()
    if owner is None:
        return False

    uid, gid = owner
    try:
        os.chown(path, uid, gid)
    except OSError:
        # Some mounted filesystems expose synthetic ownership and reject chown.
        stat = os.stat(path, follow_symlinks=False)
        if stat.st_uid != uid or stat.st_gid != gid:
            raise
    return True
