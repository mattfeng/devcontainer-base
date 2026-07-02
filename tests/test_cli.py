from __future__ import annotations

import sys
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


if __name__ == "__main__":
    unittest.main()
