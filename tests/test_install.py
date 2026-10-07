import os
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import hume


class TestInstall(unittest.TestCase):
    def test_generate_wrapper_script_default(self) -> None:
        content = hume.generate_wrapper_script()
        self.assertTrue(content.startswith("#!/usr/bin/env bash"))
        self.assertIn('"$@"', content)
        self.assertIn("SCRIPT_PATH=", content)
        self.assertIn("PROJECT_DIR=", content)
        self.assertIn("uv run --project", content)
        self.assertIn(".venv/bin/python", content)
        self.assertIn("python3", content)

    def test_generate_wrapper_script_custom_path(self) -> None:
        custom_script = "/opt/myapp/bin/hume.py"
        content = hume.generate_wrapper_script(script_path=custom_script)
        self.assertIn('SCRIPT_PATH="/opt/myapp/bin/hume.py"', content)
        self.assertIn('PROJECT_DIR="/opt/myapp/bin"', content)
        self.assertIn('"$@"', content)

    def test_find_install_dir_empty_or_none(self) -> None:
        self.assertIsNone(hume.find_install_dir(path_env=""))
        with patch.dict(os.environ, {"PATH": ""}, clear=True):
            self.assertIsNone(hume.find_install_dir())

    def test_find_install_dir_prefers_user_home_writable_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_root:
            fake_home = os.path.join(tmp_root, "home", "testuser")
            fake_user_bin = os.path.join(fake_home, ".local", "bin")
            fake_sys_bin = os.path.join(tmp_root, "usr", "local", "bin")

            os.makedirs(fake_user_bin, exist_ok=True)
            os.makedirs(fake_sys_bin, exist_ok=True)

            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", fake_home)):
                fake_path = f"{fake_sys_bin}:{fake_user_bin}"
                chosen = hume.find_install_dir(path_env=fake_path)
                self.assertEqual(chosen, fake_user_bin)

    def test_find_install_dir_creates_missing_user_dir_if_parent_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_root:
            fake_home = os.path.join(tmp_root, "home", "testuser")
            fake_local = os.path.join(fake_home, ".local")
            fake_user_bin = os.path.join(fake_local, "bin")

            os.makedirs(fake_local, exist_ok=True)
            # fake_user_bin does not exist yet

            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", fake_home)):
                fake_path = f"{fake_user_bin}"
                chosen = hume.find_install_dir(path_env=fake_path)
                self.assertEqual(chosen, fake_user_bin)

    def test_find_install_dir_falls_back_to_system_writable_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_root:
            fake_home = os.path.join(tmp_root, "home", "testuser")
            fake_sys_bin = os.path.join(tmp_root, "usr", "local", "bin")

            os.makedirs(fake_sys_bin, exist_ok=True)

            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", fake_home)):
                fake_path = f"{fake_sys_bin}"
                chosen = hume.find_install_dir(path_env=fake_path)
                self.assertEqual(chosen, fake_sys_bin)

    def test_find_install_dir_no_writable_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_root:
            fake_home = os.path.join(tmp_root, "home", "testuser")
            fake_unwritable = os.path.join(tmp_root, "unwritable", "bin")

            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", fake_home)), patch(
                "os.access", return_value=False
            ):
                chosen = hume.find_install_dir(path_env=fake_unwritable)
                self.assertIsNone(chosen)

    def test_install_hume_script_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            success, dest = hume.install_hume_script(target_dir=tmp_dir)
            self.assertTrue(success)
            expected_dest = os.path.join(tmp_dir, "hume")
            self.assertEqual(dest, expected_dest)
            self.assertTrue(os.path.exists(dest))

            # Verify file content
            with open(dest, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertTrue(content.startswith("#!/usr/bin/env bash"))
            self.assertIn('"$@"', content)

            # Verify permissions include executable bits
            mode = os.stat(dest).st_mode
            self.assertTrue(bool(mode & stat.S_IXUSR))

    def test_install_hume_script_no_writable_path(self) -> None:
        with patch("hume.find_install_dir", return_value=None):
            success, dest = hume.install_hume_script()
            self.assertFalse(success)
            self.assertEqual(dest, "")

    def test_install_hume_script_os_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("builtins.open", side_effect=OSError("Permission denied")):
                success, dest = hume.install_hume_script(target_dir=tmp_dir)
                self.assertFalse(success)
                self.assertEqual(dest, "")

    def test_cli_entrypoint_install_short_flag(self) -> None:
        with patch("hume.install_hume_script", return_value=(True, "/usr/local/bin/hume")) as mock_inst, patch(
            "builtins.print"
        ) as mock_print:
            rc = hume.cli_entrypoint(["-i"])
            self.assertEqual(rc, 0)
            mock_inst.assert_called_once()
            mock_print.assert_called_once_with("hume installed successfully to /usr/local/bin/hume")

    def test_cli_entrypoint_install_long_flag(self) -> None:
        with patch("hume.install_hume_script", return_value=(True, "/home/user/.local/bin/hume")) as mock_inst, patch(
            "builtins.print"
        ) as mock_print:
            rc = hume.cli_entrypoint(["--install"])
            self.assertEqual(rc, 0)
            mock_inst.assert_called_once()
            mock_print.assert_called_once_with("hume installed successfully to /home/user/.local/bin/hume")

    def test_cli_entrypoint_install_failure_returns_one(self) -> None:
        with patch("hume.install_hume_script", return_value=(False, "")) as mock_inst:
            rc = hume.cli_entrypoint(["--install"])
            self.assertEqual(rc, 1)
            mock_inst.assert_called_once()

    def test_cli_help_includes_install_option(self) -> None:
        with patch("builtins.print") as mock_print:
            rc = hume.cli_entrypoint(["-h"])
            self.assertEqual(rc, 0)
            mock_print.assert_called_once()
            help_output = mock_print.call_args[0][0]
            self.assertIn("-i, --install", help_output)

    def test_wrapper_script_execution(self) -> None:
        """Integration test: Generate wrapper script, execute it with --help, and verify output."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            success, dest = hume.install_hume_script(target_dir=tmp_dir)
            self.assertTrue(success)

            proc = subprocess.run(
                [dest, "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10.0,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("Usage: python hume.py [options]", proc.stdout)
            self.assertIn("-i, --install", proc.stdout)


if __name__ == "__main__":
    unittest.main()
