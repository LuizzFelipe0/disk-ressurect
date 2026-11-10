import os
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.filesystem.user_ownership import (
    ensure_pkexec_user_owned_directory,
    set_pkexec_user_ownership,
    set_pkexec_user_ownership_fd,
)


class LinuxUserOwnershipTests(unittest.TestCase):
    @contextmanager
    def _mock_pkexec_root(self):
        fake_pwd = types.SimpleNamespace(getpwuid=lambda uid: types.SimpleNamespace(pw_gid=1002))
        with ExitStack() as stack:
            stack.enter_context(patch("infrastructure.filesystem.user_ownership.sys.platform", "linux"))
            stack.enter_context(patch("infrastructure.filesystem.user_ownership.os.geteuid", return_value=0, create=True))
            stack.enter_context(patch.dict(os.environ, {"PKEXEC_UID": "1001"}))
            stack.enter_context(patch.dict(sys.modules, {"pwd": fake_pwd}))
            yield

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux ownership primitives")
    def test_chowns_an_open_descriptor_to_pkexec_authorizing_user(self):
        with (
            self._mock_pkexec_root(),
            patch("infrastructure.filesystem.user_ownership.os.fchown") as fchown,
        ):
            changed = set_pkexec_user_ownership_fd(41)

        self.assertTrue(changed)
        fchown.assert_called_once_with(41, 1001, 1002)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux openat protections")
    def test_path_ownership_refuses_a_symlink_without_chowning_its_target(self):
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            target = os.path.join(directory, "protected")
            link = os.path.join(directory, "link")
            with open(target, "w", encoding="utf-8") as target_file:
                target_file.write("keep ownership")
            os.symlink(target, link)

            with (
                self._mock_pkexec_root(),
                patch("infrastructure.filesystem.user_ownership.os.fchown") as fchown,
                self.assertRaises(OSError),
            ):
                set_pkexec_user_ownership(link)

        fchown.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux openat protections")
    def test_directory_creation_stops_at_symlink_without_creating_outside(self):
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            output = os.path.join(directory, "output")
            outside = os.path.join(directory, "outside")
            os.mkdir(output)
            os.mkdir(outside)
            os.symlink(outside, os.path.join(output, "redirect"))

            with self._mock_pkexec_root(), self.assertRaises(OSError):
                ensure_pkexec_user_owned_directory(os.path.join(output, "redirect", "created"))

            self.assertFalse(os.path.exists(os.path.join(outside, "created")))

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux directory descriptors")
    def test_created_directories_are_owned_through_open_descriptors(self):
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            target = os.path.join(directory, "created", "nested")
            with self._mock_pkexec_root(), patch("infrastructure.filesystem.user_ownership.os.fchown") as fchown:
                changed = ensure_pkexec_user_owned_directory(target)

        self.assertTrue(changed)
        self.assertTrue(os.path.isdir(target))
        self.assertEqual(fchown.call_count, 2)
        self.assertTrue(all(call.args[0] >= 0 for call in fchown.call_args_list))

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux ownership primitives")
    def test_accepts_mounts_that_already_map_ownership_to_the_user(self):
        user_stat = types.SimpleNamespace(st_uid=1001, st_gid=1002)
        with (
            self._mock_pkexec_root(),
            patch("infrastructure.filesystem.user_ownership.os.fchown", side_effect=PermissionError),
            patch("infrastructure.filesystem.user_ownership.os.fstat", return_value=user_stat),
        ):
            changed = set_pkexec_user_ownership_fd(42)

        self.assertTrue(changed)

    def test_does_nothing_when_not_running_as_pkexec_root(self):
        with (
            patch("infrastructure.filesystem.user_ownership.sys.platform", "linux"),
            patch("infrastructure.filesystem.user_ownership.os.geteuid", return_value=1001, create=True),
            patch.dict(os.environ, {"PKEXEC_UID": "1001"}),
            patch("infrastructure.filesystem.user_ownership.os.fchown") as fchown,
        ):
            changed = set_pkexec_user_ownership_fd(43)

        self.assertFalse(changed)
        fchown.assert_not_called()

    def test_ignores_missing_or_invalid_pkexec_user_identity(self):
        with (
            patch("infrastructure.filesystem.user_ownership.sys.platform", "linux"),
            patch("infrastructure.filesystem.user_ownership.os.geteuid", return_value=0, create=True),
            patch.dict(os.environ, {"PKEXEC_UID": "not-a-uid"}),
            patch("infrastructure.filesystem.user_ownership.os.fchown") as fchown,
        ):
            changed = set_pkexec_user_ownership_fd(44)

        self.assertFalse(changed)
        fchown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
