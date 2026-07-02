from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devcontainer_configurator import cli


class DevcontainerMountTests(unittest.TestCase):
    def test_build_devcontainer_uses_masked_and_read_only_mounts(self) -> None:
        devcontainer = cli.build_devcontainer_json(
            host_ports=[],
            masked_paths=[".git", "private/file.txt"],
            read_only_paths=[".devcontainer", "README.md"],
            gpu=cli.DEFAULT_GPU,
        )

        mounts = devcontainer["mounts"]
        self.assertIn("target=/workspace/.git,type=volume,volume-nocopy", mounts)
        self.assertIn(
            "target=/workspace/private/file.txt,type=volume,volume-nocopy",
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


if __name__ == "__main__":
    unittest.main()
