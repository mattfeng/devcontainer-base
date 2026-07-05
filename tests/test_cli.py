from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devcontainer_configurator import cli


class DevcontainerMountTests(unittest.TestCase):
    def test_generated_dockerfile_includes_postgres_client(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        self.assertIn("postgresql-client", generated_files["Dockerfile"])

    def test_build_devcontainer_uses_masked_and_read_only_mounts(self) -> None:
        devcontainer = cli.build_devcontainer_json(
            host_ports=[],
            masked_paths=[".git", "private/file.txt"],
            read_only_paths=[".devcontainer", "README.md"],
            gpu=cli.DEFAULT_GPU,
            masked_file_paths=["private/file.txt"],
        )

        mounts = devcontainer["mounts"]
        self.assertIn("target=/workspace/.git,type=volume,volume-nocopy", mounts)
        self.assertIn(
            "source=${localWorkspaceFolder}/.devcontainer/.empty-mask,"
            "target=/workspace/private/file.txt,type=bind,readonly",
            mounts,
        )
        self.assertIn(
            "source=${localWorkspaceFolder}/.devcontainer,"
            "target=/workspace/.devcontainer,type=bind,readonly",
            mounts,
        )
        self.assertIn(
            "source=${localWorkspaceFolder}/README.md,"
            "target=/workspace/README.md,type=bind,readonly",
            mounts,
        )

    def test_legacy_hidden_paths_migrate_default_devcontainer_to_read_only(self) -> None:
        config = {"hidden_paths": [".jj", ".git", ".devcontainer", "secret.txt"]}

        self.assertEqual(
            cli.config_masked_paths(config),
            [".jj", ".git", "secret.txt"],
        )
        self.assertEqual(cli.config_read_only_paths(config), [".devcontainer"])

    def test_paths_cannot_be_both_masked_and_read_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "both masked and read-only"):
            cli.build_devcontainer_json(
                host_ports=[],
                masked_paths=["config"],
                read_only_paths=["./config"],
                gpu=cli.DEFAULT_GPU,
            )

    def test_detect_masked_file_paths_uses_workspace_file_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".git").mkdir()
            (workspace / "secret.txt").write_text("secret", encoding="utf-8")

            self.assertEqual(
                cli.detect_masked_file_paths(
                    workspace,
                    [".git", "secret.txt", "missing.txt"],
                ),
                ["secret.txt"],
            )

    def test_render_files_includes_empty_mask_placeholder(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=["secret.txt"],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
            masked_file_paths=["secret.txt"],
        )

        self.assertIn(cli.MASKED_FILE_PLACEHOLDER, generated_files)
        self.assertEqual(generated_files[cli.MASKED_FILE_PLACEHOLDER], "")


class MarkerFileTests(unittest.TestCase):
    def test_marker_filename_describes_managed_file_hashes(self) -> None:
        self.assertEqual(cli.MARKER_FILENAME, ".managed-file-hashes.json")

    def test_find_marker_path_supports_legacy_marker_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            devcontainer_dir = Path(temp_dir)
            legacy_names = [
                ".devcontainer-configurator-managed-file-hashes.json",
                ".codex-claude-devcontainer-configurator.json",
            ]

            for legacy_name in legacy_names:
                legacy_marker_path = devcontainer_dir / legacy_name
                legacy_marker_path.write_text("{}", encoding="utf-8")

                self.assertEqual(
                    cli.find_marker_path(devcontainer_dir),
                    legacy_marker_path,
                )

                legacy_marker_path.unlink()


class PromptTests(unittest.TestCase):
    def test_prompt_keeps_current_value_when_change_declined(self) -> None:
        with patch("builtins.input", return_value="n"), patch.object(
            cli,
            "edit_prompt_value",
        ) as edit_prompt_value:
            self.assertEqual(cli.prompt_masked_paths([".git"]), [".git"])

        edit_prompt_value.assert_not_called()

    def test_prompt_can_clear_paths_with_blank_editor_content(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value="\n",
        ):
            self.assertEqual(cli.prompt_read_only_paths([".devcontainer"]), [])
        print_mock.assert_called_once_with(
            "Workspace paths to mount read-only: changed from .devcontainer to none."
        )

    def test_prompt_accepts_line_or_comma_separated_editor_entries(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value=".git\n.env,private\n",
        ):
            self.assertEqual(
                cli.prompt_masked_paths([".git"]),
                [".git", ".env", "private"],
            )
        print_mock.assert_called_once_with(
            "Workspace paths to mask: changed from .git to .git, .env, private."
        )

    def test_prompt_can_clear_host_ports_with_blank_editor_content(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value="",
        ):
            self.assertEqual(cli.prompt_host_ports([3000, 5000]), [])
        print_mock.assert_called_once_with(
            "Host TCP ports: changed from 3000,5000 to none."
        )

    def test_prompt_reports_when_editor_content_does_not_change_value(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value=".git\n",
        ):
            self.assertEqual(cli.prompt_masked_paths([".git"]), [".git"])
        print_mock.assert_called_once_with("Workspace paths to mask: nothing changed.")

    def test_prompt_reports_gpu_change(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value="all\n",
        ):
            self.assertEqual(
                cli.prompt_gpu({"mode": "device", "device": "0"}),
                {"mode": "all", "device": ""},
            )
        print_mock.assert_called_once_with("GPU access: changed from device=0 to all.")

    def test_edit_prompt_value_seeds_editor_and_returns_saved_content(self) -> None:
        editor_script = (
            "from pathlib import Path; "
            "import sys; "
            "path = Path(sys.argv[1]); "
            "assert path.read_text(encoding='utf-8') == 'old\\n'; "
            "path.write_text('new\\n', encoding='utf-8')"
        )

        with patch.object(
            cli,
            "editor_command",
            return_value=[sys.executable, "-c", editor_script],
        ), patch("builtins.print"):
            self.assertEqual(cli.edit_prompt_value("Example", "old\n"), "new\n")


if __name__ == "__main__":
    unittest.main()
