import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.filesystem.user_ownership import set_pkexec_user_ownership


class LinuxUserOwnershipTests(unittest.TestCase):
    def test_chowns_new_paths_to_pkexec_authorizing_user(self):
        fake_pwd = types.SimpleNamespace(getpwuid=lambda uid: types.SimpleNamespace(pw_gid=1002))
        with (
            patch("infrastructure.filesystem.user_ownership.sys.platform", "linux"),
            patch("infrastructure.filesystem.user_ownership.os.geteuid", return_value=0, create=True),
            patch.dict(os.environ, {"PKEXEC_UID": "1001"}),
            patch.dict(sys.modules, {"pwd": fake_pwd}),
            patch("infrastructure.filesystem.user_ownership.os.chown", create=True) as chown,
        ):
            changed = set_pkexec_user_ownership("/home/tester/recovered.bin")

        self.assertTrue(changed)
        chown.assert_called_once_with("/home/tester/recovered.bin", 1001, 1002)

    def test_accepts_mounts_that_already_map_ownership_to_the_user(self):
        fake_pwd = types.SimpleNamespace(getpwuid=lambda uid: types.SimpleNamespace(pw_gid=1002))
        user_stat = types.SimpleNamespace(st_uid=1001, st_gid=1002)
        with (
            patch("infrastructure.filesystem.user_ownership.sys.platform", "linux"),
            patch("infrastructure.filesystem.user_ownership.os.geteuid", return_value=0, create=True),
            patch.dict(os.environ, {"PKEXEC_UID": "1001"}),
            patch.dict(sys.modules, {"pwd": fake_pwd}),
            patch("infrastructure.filesystem.user_ownership.os.chown", side_effect=PermissionError, create=True),
            patch("infrastructure.filesystem.user_ownership.os.stat", return_value=user_stat),
        ):
            changed = set_pkexec_user_ownership("/media/tester/recovered.bin")

        self.assertTrue(changed)

    def test_does_nothing_when_not_running_as_pkexec_root(self):
        with (
            patch("infrastructure.filesystem.user_ownership.sys.platform", "linux"),
            patch("infrastructure.filesystem.user_ownership.os.geteuid", return_value=1001, create=True),
            patch.dict(os.environ, {"PKEXEC_UID": "1001"}),
            patch("infrastructure.filesystem.user_ownership.os.chown", create=True) as chown,
        ):
            changed = set_pkexec_user_ownership("/home/tester/recovered.bin")

        self.assertFalse(changed)
        chown.assert_not_called()

    def test_ignores_missing_or_invalid_pkexec_user_identity(self):
        with (
            patch("infrastructure.filesystem.user_ownership.sys.platform", "linux"),
            patch("infrastructure.filesystem.user_ownership.os.geteuid", return_value=0, create=True),
            patch.dict(os.environ, {"PKEXEC_UID": "not-a-uid"}),
            patch("infrastructure.filesystem.user_ownership.os.chown", create=True) as chown,
        ):
            changed = set_pkexec_user_ownership("/home/tester/recovered.bin")

        self.assertFalse(changed)
        chown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
