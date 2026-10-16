from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devcontainer_configurator import cli


class TemplateFileTests(unittest.TestCase):
    def test_all_generated_configuration_files_have_jinja_templates(self) -> None:
        self.assertEqual(
            set(cli.TEMPLATE_NAMES),
            {
                "Dockerfile.j2",
                "devcontainer.json.j2",
                "init-firewall.sh.j2",
            },
        )
        for template_name in cli.TEMPLATE_NAMES:
            self.assertTrue((cli.TEMPLATE_DIRECTORY / template_name).is_file())

    def test_static_files_are_rendered_from_their_jinja_templates(self) -> None:
        generated_files = cli.render_files([], [], [], cli.DEFAULT_GPU)

        self.assertEqual(
            generated_files["Dockerfile"],
            (cli.TEMPLATE_DIRECTORY / cli.DOCKERFILE_TEMPLATE_NAME).read_text(
                encoding="utf-8"
            ),
        )
        self.assertEqual(
            generated_files["init-firewall.sh"],
            (cli.TEMPLATE_DIRECTORY / cli.FIREWALL_TEMPLATE_NAME).read_text(
                encoding="utf-8"
            ),
        )


class HostOperatingSystemTests(unittest.TestCase):
    def test_detected_operating_system_is_confirmed_by_default(self) -> None:
        for system, expected in (("Linux", "linux"), ("Darwin", "macos")):
            with self.subTest(system=system), patch.object(
                cli.platform, "system", return_value=system
            ), patch("builtins.input", return_value="") as input_mock:
                self.assertEqual(cli.prompt_host_os(), expected)
                self.assertIn(f"Detected: {expected}", input_mock.call_args.args[0])

    def test_user_can_override_detected_operating_system(self) -> None:
        with patch.object(
            cli.platform, "system", return_value="Linux"
        ), patch("builtins.input", return_value="y"), patch.object(
            cli, "edit_prompt_value", return_value="macOS\n"
        ), patch("builtins.print"):
            self.assertEqual(cli.prompt_host_os(), "macos")

    def test_unknown_operating_system_requires_explicit_selection(self) -> None:
        with patch.object(
            cli.platform, "system", return_value="Windows"
        ), patch.object(
            cli, "edit_prompt_value", return_value="linux\n"
        ), patch("builtins.input") as input_mock, patch("builtins.print"):
            self.assertEqual(cli.prompt_host_os(), "linux")
            input_mock.assert_not_called()

    def test_invalid_operating_system_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be linux or macos"):
            cli.render_files([], [], [], cli.DEFAULT_GPU, host_os="windows")

    def test_x11_mount_is_only_rendered_for_linux(self) -> None:
        x11_mount = "source=/tmp/.X11-unix,target=/tmp/.X11-unix,type=bind"
        for host_os in ("linux", "macos"):
            with self.subTest(host_os=host_os):
                generated = cli.render_files(
                    [], [], [], cli.DEFAULT_GPU, host_os=host_os
                )
                devcontainer = json.loads(generated["devcontainer.json"])
                self.assertEqual(
                    x11_mount in devcontainer["mounts"], host_os == "linux"
                )

    def test_configure_remembers_operating_system_and_uses_it_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with patch.object(
                cli.platform, "system", return_value="Linux"
            ), patch(
                "builtins.input", side_effect=["y", "n", "n", "n", "n", "n"]
            ), patch.object(
                cli, "edit_prompt_value", return_value="macos\n"
            ), patch("builtins.print"):
                self.assertEqual(cli.configure(workspace), 0)

            with patch.object(
                cli.platform, "system", return_value="Linux"
            ), patch("builtins.input", return_value="n"), patch("builtins.print"):
                self.assertEqual(cli.configure(workspace), 0)

            config = cli.read_json(workspace / cli.ROOT_STATE_FILENAME)
            marker = cli.read_json(
                workspace / cli.DEVCONTAINER_DIRNAME / cli.MARKER_FILENAME
            )
            devcontainer = cli.read_json(
                workspace / cli.DEVCONTAINER_DIRNAME / "devcontainer.json"
            )
            self.assertEqual(config["host_os"], "macos")
            self.assertEqual(marker["config"]["host_os"], "macos")
            self.assertNotIn(
                "source=/tmp/.X11-unix,target=/tmp/.X11-unix,type=bind",
                devcontainer["mounts"],
            )
            marker.pop(cli.TEMPLATE_FINGERPRINT_KEY)
            self.assertFalse(
                cli.template_changed_since_generation(marker, config, workspace)
            )


class DevcontainerMountTests(unittest.TestCase):
    def test_generated_dockerfile_includes_postgres_client(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        self.assertIn("postgresql-client", generated_files["Dockerfile"])

    def test_workspace_parent_is_read_only_but_project_mount_is_writable(
        self,
    ) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )
        devcontainer = cli.build_devcontainer_json(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        dockerfile = generated_files["Dockerfile"]
        self.assertIn("chown -R root:root /workspace", dockerfile)
        self.assertIn("chmod 0555 /workspace /workspace/reference", dockerfile)
        self.assertEqual(
            devcontainer["workspaceMount"],
            "source=${localWorkspaceFolder},"
            "target=/workspace/${localWorkspaceFolderBasename},"
            "type=bind,consistency=delegated",
        )

    def test_generated_devcontainer_uses_node_24_and_modern_yarn(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )
        devcontainer = cli.build_devcontainer_json(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        dockerfile = generated_files["Dockerfile"]

        self.assertIn("FROM node:24", dockerfile)
        self.assertIn("ARG YARN_MODERN_VERSION=4", dockerfile)
        self.assertIn('ENV YARN_VERSION="$YARN_MODERN_VERSION"', dockerfile)
        self.assertIn(
            "find /opt -maxdepth 1 -type d -name 'yarn-v*' "
            "-exec rm -rf -- {} +",
            dockerfile,
        )
        self.assertIn("rm -f /usr/local/bin/yarn /usr/local/bin/yarnpkg", dockerfile)
        self.assertIn(
            'corepack install --global "yarn@${YARN_VERSION}"',
            dockerfile,
        )
        self.assertEqual(
            devcontainer["build"]["args"]["YARN_MODERN_VERSION"], "4"
        )
        self.assertNotIn("YARN_VERSION", devcontainer["build"]["args"])

    def test_generated_devcontainer_uses_yarn_node_modules_linker(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        self.assertIn(
            "RUN printf '%s\\n' 'nodeLinker: node-modules' "
            "> /home/node/.yarnrc.yml",
            generated_files["Dockerfile"],
        )

    def test_generated_devcontainer_installs_and_persists_pi(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )
        devcontainer = cli.build_devcontainer_json(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        dockerfile = generated_files["Dockerfile"]
        self.assertIn("ARG PI_CODING_AGENT_VERSION=latest", dockerfile)
        self.assertIn(
            "RUN npm install -g --ignore-scripts "
            "@earendil-works/pi-coding-agent@${PI_CODING_AGENT_VERSION}",
            dockerfile,
        )
        self.assertEqual(
            devcontainer["build"]["args"]["PI_CODING_AGENT_VERSION"],
            "latest",
        )
        self.assertIn(
            "source=pi-config-${devcontainerId},"
            "target=/home/node/.pi,type=volume",
            devcontainer["mounts"],
        )

    def test_generated_devcontainer_installs_and_persists_oh_my_pi(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )
        devcontainer = cli.build_devcontainer_json(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        dockerfile = generated_files["Dockerfile"]
        self.assertIn("ARG OH_MY_PI_VERSION=latest", dockerfile)
        self.assertIn("ARG BUN_VERSION=1.3.14", dockerfile)
        self.assertIn(
            'curl -fsSL https://bun.com/install | bash -s "bun-v${BUN_VERSION}"',
            dockerfile,
        )
        self.assertIn(
            "bun install -g "
            "@oh-my-pi/pi-coding-agent@${OH_MY_PI_VERSION}",
            dockerfile,
        )
        self.assertIn("omp --version", dockerfile)
        self.assertEqual(
            devcontainer["build"]["args"]["OH_MY_PI_VERSION"],
            "latest",
        )
        self.assertEqual(
            devcontainer["build"]["args"]["BUN_VERSION"],
            "1.3.14",
        )
        self.assertIn(
            "source=oh-my-pi-config-${devcontainerId},"
            "target=/home/node/.omp,type=volume",
            devcontainer["mounts"],
        )
        self.assertNotIn("PI_CODING_AGENT_DIR", devcontainer["containerEnv"])

    def test_firewall_allows_modern_yarn_downloads(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        firewall = generated_files["init-firewall.sh"]

        self.assertIn('"registry.yarnpkg.com"', firewall)
        self.assertIn('"repo.yarnpkg.com"', firewall)

    def test_firewall_allows_pi_startup_requests(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        self.assertIn('"pi.dev"', generated_files["init-firewall.sh"])

    def test_generated_dockerfile_installs_uv_for_node_user(self) -> None:
        generated_files = cli.render_files(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )
        dockerfile = generated_files["Dockerfile"]

        user_index = dockerfile.index("USER node")
        local_bin_path_index = dockerfile.index(
            'ENV PATH="/home/node/.local/bin:${PATH}"'
        )
        uv_install_index = dockerfile.index("RUN pipx install uv")

        self.assertLess(user_index, local_bin_path_index)
        self.assertLess(local_bin_path_index, uv_install_index)
        self.assertIn("RUN pipx install uv && \\\n  uv --version", dockerfile)

    def test_firewall_sudo_command_receives_host_ports_env(self) -> None:
        generated_files = cli.render_files(
            host_ports=[3000, 5432],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )
        devcontainer = cli.build_devcontainer_json(
            host_ports=[3000, 5432],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
        )

        self.assertIn(
            "NOPASSWD: SETENV: /usr/local/bin/init-firewall.sh",
            generated_files["Dockerfile"],
        )
        self.assertEqual(
            devcontainer["postStartCommand"],
            'sudo DEVCONTAINER_HOST_PORTS="${DEVCONTAINER_HOST_PORTS:-}" '
            "/usr/local/bin/init-firewall.sh",
        )
        self.assertEqual(
            devcontainer["containerEnv"][cli.HOST_PORTS_ENV],
            "3000,5432",
        )

    def test_build_devcontainer_uses_masked_and_read_only_mounts(self) -> None:
        devcontainer = cli.build_devcontainer_json(
            host_ports=[],
            masked_paths=[".git", "private/file.txt"],
            read_only_paths=[".devcontainer", "README.md"],
            gpu=cli.DEFAULT_GPU,
            masked_file_paths=["private/file.txt"],
        )

        mounts = devcontainer["mounts"]
        self.assertIn(
            "target=/workspace/${localWorkspaceFolderBasename}/.git,"
            "type=volume,volume-nocopy",
            mounts,
        )
        self.assertIn(
            "source=${localWorkspaceFolder}/.devcontainer/.empty-mask,"
            "target=/workspace/${localWorkspaceFolderBasename}/private/file.txt,"
            "type=bind,readonly",
            mounts,
        )
        self.assertIn(
            "source=${localWorkspaceFolder}/.devcontainer,"
            "target=/workspace/${localWorkspaceFolderBasename}/.devcontainer,"
            "type=bind,readonly",
            mounts,
        )
        self.assertIn(
            "source=${localWorkspaceFolder}/README.md,"
            "target=/workspace/${localWorkspaceFolderBasename}/README.md,"
            "type=bind,readonly",
            mounts,
        )
        self.assertNotIn("GIT_OPTIONAL_LOCKS", devcontainer["containerEnv"])
        self.assertEqual(
            devcontainer["workspaceMount"],
            "source=${localWorkspaceFolder},"
            "target=/workspace/${localWorkspaceFolderBasename},"
            "type=bind,consistency=delegated",
        )
        self.assertEqual(
            devcontainer["workspaceFolder"],
            "/workspace/${localWorkspaceFolderBasename}",
        )

    def test_build_devcontainer_mounts_reference_projects_by_folder_name(
        self,
    ) -> None:
        devcontainer = cli.build_devcontainer_json(
            host_ports=[],
            masked_paths=[],
            read_only_paths=[],
            gpu=cli.DEFAULT_GPU,
            reference_paths=["../shared-api", "/projects/design-system"],
        )

        self.assertIn(
            "source=${localWorkspaceFolder}/../shared-api,"
            "target=/workspace/reference/shared-api,type=bind,readonly",
            devcontainer["mounts"],
        )
        self.assertIn(
            "source=/projects/design-system,"
            "target=/workspace/reference/design-system,type=bind,readonly",
            devcontainer["mounts"],
        )

    def test_reference_project_folder_names_must_be_unique(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique folder names"):
            cli.build_devcontainer_json(
                host_ports=[],
                masked_paths=[],
                read_only_paths=[],
                gpu=cli.DEFAULT_GPU,
                reference_paths=["../team-a/service", "../team-b/service"],
            )

    def test_reference_projects_must_be_existing_directories_outside_workspace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "nested-project").mkdir()
            reference_project = root / "reference-project"
            reference_project.mkdir()
            reference_file = root / "reference-file"
            reference_file.write_text("not a directory", encoding="utf-8")

            cli.validate_reference_paths(["../reference-project"], workspace)
            with self.assertRaisesRegex(ValueError, "outside the workspace"):
                cli.validate_reference_paths(["nested-project"], workspace)
            with self.assertRaisesRegex(ValueError, "does not exist"):
                cli.validate_reference_paths(["../missing-project"], workspace)
            with self.assertRaisesRegex(ValueError, "not a directory"):
                cli.validate_reference_paths(["../reference-file"], workspace)

    def test_read_only_git_disables_optional_locks(self) -> None:
        devcontainer = cli.build_devcontainer_json(
            host_ports=[],
            masked_paths=[],
            read_only_paths=["./.git"],
            gpu=cli.DEFAULT_GPU,
        )

        self.assertEqual(devcontainer["containerEnv"]["GIT_OPTIONAL_LOCKS"], "0")
        self.assertIn(
            "source=${localWorkspaceFolder}/.git,"
            "target=/workspace/${localWorkspaceFolderBasename}/.git,"
            "type=bind,readonly",
            devcontainer["mounts"],
        )

    def test_default_read_only_paths_without_workspace_use_standard_defaults(self) -> None:
        self.assertEqual(cli.config_read_only_paths({}), [".devcontainer"])

    def test_detect_venvs_without_searching_hidden_or_generated_directories(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".venv").mkdir()
            (workspace / "app" / ".venv").mkdir(parents=True)
            (workspace / ".next" / ".venv").mkdir(parents=True)
            (workspace / "node_modules" / "dependency" / ".venv").mkdir(
                parents=True
            )

            self.assertEqual(
                cli.detected_venv_masked_paths(workspace),
                [".venv", "app/.venv"],
            )

    def test_detected_venv_already_mounted_read_only_is_not_promptable(self) -> None:
        self.assertEqual(
            cli.promptable_masked_scan_paths(
                [".venv", "app/.venv"],
                ["app/.venv"],
            ),
            [".venv"],
        )

    def test_default_read_only_paths_include_only_detected_lockfiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text("{}", encoding="utf-8")
            (workspace / "package-lock.json").write_text("", encoding="utf-8")
            (workspace / "app").mkdir()
            (workspace / "app" / "package.json").write_text("{}", encoding="utf-8")
            (workspace / "app" / "yarn.lock").write_text("", encoding="utf-8")
            (workspace / "service").mkdir()
            (workspace / "service" / "pyproject.toml").write_text("", encoding="utf-8")
            (workspace / "service" / "uv.lock").write_text("", encoding="utf-8")
            (workspace / "node_modules").mkdir()
            (workspace / "node_modules" / "package-lock.json").write_text(
                "",
                encoding="utf-8",
            )

            self.assertEqual(
                cli.config_read_only_paths({}, workspace),
                [
                    ".devcontainer",
                    "package-lock.json",
                    "app/yarn.lock",
                    "service/uv.lock",
                ],
            )

    def test_lockfile_scan_skips_all_hidden_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "visible").mkdir()
            (workspace / "visible" / "uv.lock").write_text("", encoding="utf-8")
            (workspace / ".next").mkdir()
            (workspace / ".next" / "yarn.lock").write_text("", encoding="utf-8")
            (workspace / "visible" / ".cache").mkdir()
            (workspace / "visible" / ".cache" / "package-lock.json").write_text(
                "",
                encoding="utf-8",
            )

            self.assertEqual(
                cli.detected_package_manager_read_only_paths(workspace),
                ["visible/uv.lock"],
            )

    def test_old_default_read_only_config_gets_detected_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "pyproject.toml").write_text("", encoding="utf-8")
            (workspace / "uv.lock").write_text("", encoding="utf-8")

            self.assertEqual(
                cli.config_read_only_paths(
                    {"version": 3, "read_only_paths": [".devcontainer"]},
                    workspace,
                ),
                [".devcontainer", "uv.lock"],
            )

    def test_saved_read_only_paths_are_reused(self) -> None:
        self.assertEqual(
            cli.config_read_only_paths(
                {"version": cli.CONFIG_VERSION, "read_only_paths": ["README.md"]},
            ),
            ["README.md"],
        )

    def test_version_four_read_only_paths_are_reused_after_schema_upgrade(
        self,
    ) -> None:
        self.assertEqual(
            cli.config_read_only_paths(
                {"version": 4, "read_only_paths": [".devcontainer"]},
            ),
            [".devcontainer"],
        )

    def test_custom_read_only_paths_do_not_get_new_defaults(self) -> None:
        self.assertEqual(
            cli.config_read_only_paths(
                {"version": 3, "read_only_paths": []},
            ),
            [],
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

    def test_configure_loads_saved_responses_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            saved_config = {
                "version": cli.CONFIG_VERSION,
                "host_ports": [5432],
                "masked_paths": [".env"],
                "read_only_paths": ["README.md"],
                "gpu": {"mode": "all", "device": ""},
            }
            (workspace / cli.ROOT_STATE_FILENAME).write_text(
                json.dumps(saved_config),
                encoding="utf-8",
            )
            (workspace / "package.json").write_text("{}", encoding="utf-8")
            (workspace / "uv.lock").write_text("", encoding="utf-8")

            with patch("builtins.input", return_value="n"), patch("builtins.print"):
                self.assertEqual(cli.configure(workspace), 0)

            remembered_config = json.loads(
                (workspace / cli.ROOT_STATE_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(
                remembered_config,
                {
                    **saved_config,
                    "host_os": cli.detected_host_os(),
                    cli.MASKED_SCAN_PATHS_KEY: [],
                    cli.READ_ONLY_SCAN_PATHS_KEY: ["uv.lock"],
                    cli.REFERENCE_PATHS_KEY: [],
                },
            )

    def test_configure_prompts_for_and_remembers_reference_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (root / "reference-project").mkdir()

            with patch(
                "builtins.input",
                side_effect=["n", "n", "n", "n", "y", "n"],
            ), patch("builtins.print"), patch.object(
                cli,
                "edit_prompt_value",
                return_value="../reference-project\n",
            ):
                self.assertEqual(cli.configure(workspace), 0)

            remembered_config = json.loads(
                (workspace / cli.ROOT_STATE_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(
                remembered_config[cli.REFERENCE_PATHS_KEY],
                ["../reference-project"],
            )
            devcontainer = json.loads(
                (
                    workspace / cli.DEVCONTAINER_DIRNAME / "devcontainer.json"
                ).read_text(encoding="utf-8")
            )
            self.assertIn(
                "source=${localWorkspaceFolder}/../reference-project,"
                "target=/workspace/reference/reference-project,"
                "type=bind,readonly",
                devcontainer["mounts"],
            )

    def test_configure_prompts_to_mask_detected_venv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".venv").mkdir()

            with patch(
                "builtins.input",
                side_effect=["n", "n", "n", "n", "n", "y", "n"],
            ), patch("builtins.print"), patch.object(
                cli,
                "edit_prompt_value",
                return_value=".venv\n",
            ):
                self.assertEqual(cli.configure(workspace), 0)

            remembered_config = json.loads(
                (workspace / cli.ROOT_STATE_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(
                remembered_config["masked_paths"],
                [".jj", ".git", ".venv"],
            )
            self.assertEqual(
                remembered_config[cli.MASKED_SCAN_PATHS_KEY],
                [".venv"],
            )

    def test_configure_prompts_to_add_new_detected_lockfiles_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            with patch("builtins.input", return_value="n"), patch("builtins.print"):
                self.assertEqual(cli.configure(workspace), 0)

            (workspace / "app").mkdir()
            (workspace / "app" / "yarn.lock").write_text("", encoding="utf-8")

            with patch(
                "builtins.input",
                side_effect=["n", "n", "n", "n", "n", "y", "n"],
            ), patch("builtins.print"), patch.object(
                cli,
                "edit_prompt_value",
                return_value="app/yarn.lock\n",
            ):
                self.assertEqual(cli.configure(workspace), 0)

            remembered_config = json.loads(
                (workspace / cli.ROOT_STATE_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(
                remembered_config["read_only_paths"],
                [".devcontainer", "app/yarn.lock"],
            )
            self.assertEqual(
                remembered_config[cli.READ_ONLY_SCAN_PATHS_KEY],
                ["app/yarn.lock"],
            )

    def test_configure_upgrades_changed_template_when_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            with patch("builtins.input", return_value="n"), patch("builtins.print"):
                self.assertEqual(cli.configure(workspace), 0)

            state_before = (workspace / cli.ROOT_STATE_FILENAME).read_text(
                encoding="utf-8"
            )
            template_directory = workspace / "test-templates"
            shutil.copytree(cli.TEMPLATE_DIRECTORY, template_directory)
            dockerfile_template = (
                template_directory / cli.DOCKERFILE_TEMPLATE_NAME
            )
            dockerfile_template.write_text(
                dockerfile_template.read_text(encoding="utf-8")
                + "\n# New template content.\n",
                encoding="utf-8",
            )
            with patch.object(
                cli,
                "TEMPLATE_DIRECTORY",
                template_directory,
            ), patch(
                "builtins.input",
                side_effect=["y", "n", "n", "n", "n", "n", "n"],
            ) as input_mock, patch(
                "builtins.print"
            ):
                self.assertEqual(cli.configure(workspace), 0)
                marker = json.loads(
                    (
                        workspace
                        / cli.DEVCONTAINER_DIRNAME
                        / cli.MARKER_FILENAME
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    marker[cli.TEMPLATE_FINGERPRINT_KEY],
                    cli.template_fingerprint(),
                )

            self.assertIn(
                "# New template content.",
                (
                    workspace / cli.DEVCONTAINER_DIRNAME / "Dockerfile"
                ).read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (workspace / cli.ROOT_STATE_FILENAME).read_text(encoding="utf-8"),
                state_before,
            )
            self.assertIn(
                "template has changed",
                input_mock.call_args_list[0].args[0],
            )

    def test_configure_leaves_files_unchanged_when_upgrade_declined(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            with patch("builtins.input", return_value="n"), patch("builtins.print"):
                self.assertEqual(cli.configure(workspace), 0)

            devcontainer_dir = workspace / cli.DEVCONTAINER_DIRNAME
            files_before = {
                path.name: path.read_bytes()
                for path in devcontainer_dir.iterdir()
                if path.is_file()
            }
            state_before = (workspace / cli.ROOT_STATE_FILENAME).read_bytes()

            template_directory = workspace / "test-templates"
            shutil.copytree(cli.TEMPLATE_DIRECTORY, template_directory)
            dockerfile_template = (
                template_directory / cli.DOCKERFILE_TEMPLATE_NAME
            )
            dockerfile_template.write_text(
                dockerfile_template.read_text(encoding="utf-8")
                + "\n# New template content.\n",
                encoding="utf-8",
            )
            with patch.object(
                cli,
                "TEMPLATE_DIRECTORY",
                template_directory,
            ), patch(
                "builtins.input",
                return_value="n",
            ) as input_mock, patch(
                "builtins.print"
            ):
                self.assertEqual(cli.configure(workspace), 0)

            self.assertEqual(
                {
                    path.name: path.read_bytes()
                    for path in devcontainer_dir.iterdir()
                    if path.is_file()
                },
                files_before,
            )
            self.assertEqual(
                (workspace / cli.ROOT_STATE_FILENAME).read_bytes(),
                state_before,
            )
            input_mock.assert_called_once()


class MarkerFileTests(unittest.TestCase):
    def test_marker_filename_describes_managed_file_hashes(self) -> None:
        self.assertEqual(cli.MARKER_FILENAME, ".managed-file-hashes.json")

    def test_marker_records_current_template_fingerprint(self) -> None:
        config = {
            "version": cli.CONFIG_VERSION,
            "host_ports": [],
            "masked_paths": [],
            "read_only_paths": [],
            "gpu": cli.DEFAULT_GPU,
        }
        generated_files = cli.render_files([], [], [], cli.DEFAULT_GPU)

        marker = cli.build_marker(config, generated_files)

        self.assertEqual(
            marker[cli.TEMPLATE_FINGERPRINT_KEY],
            cli.template_fingerprint(),
        )

    def test_marker_without_fingerprint_compares_saved_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = {
                "version": cli.CONFIG_VERSION,
                "host_ports": [],
                "masked_paths": [],
                "read_only_paths": [],
                "gpu": cli.DEFAULT_GPU,
            }
            generated_files = cli.render_files([], [], [], cli.DEFAULT_GPU)
            marker = cli.build_marker(config, generated_files)
            marker.pop(cli.TEMPLATE_FINGERPRINT_KEY)

            self.assertFalse(
                cli.template_changed_since_generation(marker, config, workspace)
            )

            template_directory = workspace / "test-templates"
            shutil.copytree(cli.TEMPLATE_DIRECTORY, template_directory)
            dockerfile_template = (
                template_directory / cli.DOCKERFILE_TEMPLATE_NAME
            )
            dockerfile_template.write_text(
                dockerfile_template.read_text(encoding="utf-8")
                + "\n# New template content.\n",
                encoding="utf-8",
            )
            with patch.object(
                cli,
                "TEMPLATE_DIRECTORY",
                template_directory,
            ):
                self.assertTrue(
                    cli.template_changed_since_generation(marker, config, workspace)
                )

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

    def test_prompt_can_set_reference_project_paths(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value="../api\n/opt/projects/web\n",
        ):
            self.assertEqual(
                cli.prompt_reference_paths([]),
                ["../api", "/opt/projects/web"],
            )
        print_mock.assert_called_once_with(
            "Reference project folders: changed from none to "
            "../api, /opt/projects/web."
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

    def test_prompt_adds_new_detected_venv_to_masked_paths(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value=".venv\n",
        ) as edit_prompt_value:
            self.assertEqual(
                cli.prompt_new_detected_masked_paths(
                    [".git"],
                    [".venv"],
                    [],
                ),
                [".git", ".venv"],
            )
        print_mock.assert_called_once_with(
            "Workspace paths to mask: added .venv."
        )
        edit_prompt_value.assert_called_once_with(
            "Newly detected .venv directories",
            ".venv\n",
        )

    def test_prompt_skips_detected_venv_seen_before(self) -> None:
        with patch("builtins.input") as input_mock:
            self.assertEqual(
                cli.prompt_new_detected_masked_paths(
                    [".git"],
                    [".venv"],
                    [".venv"],
                ),
                [".git"],
            )
        input_mock.assert_not_called()

    def test_prompt_adds_new_detected_read_only_paths(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value="yarn.lock\n",
        ) as edit_prompt_value:
            self.assertEqual(
                cli.prompt_new_detected_read_only_paths(
                    [".devcontainer"],
                    ["yarn.lock"],
                    [],
                ),
                [".devcontainer", "yarn.lock"],
            )
        print_mock.assert_called_once_with(
            "Workspace paths to mount read-only: added yarn.lock."
        )
        edit_prompt_value.assert_called_once_with(
            "Newly detected read-only paths",
            "yarn.lock\n",
        )

    def test_prompt_can_edit_new_detected_read_only_paths(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value="app/yarn.lock\n",
        ):
            self.assertEqual(
                cli.prompt_new_detected_read_only_paths(
                    [".devcontainer"],
                    ["app/yarn.lock", "service/uv.lock"],
                    [],
                ),
                [".devcontainer", "app/yarn.lock"],
            )
        print_mock.assert_called_once_with(
            "Workspace paths to mount read-only: added app/yarn.lock."
        )

    def test_prompt_can_clear_new_detected_read_only_paths(self) -> None:
        with patch("builtins.input", return_value="y"), patch(
            "builtins.print"
        ) as print_mock, patch.object(
            cli,
            "edit_prompt_value",
            return_value="\n",
        ):
            self.assertEqual(
                cli.prompt_new_detected_read_only_paths(
                    [".devcontainer"],
                    ["yarn.lock"],
                    [],
                ),
                [".devcontainer"],
            )
        print_mock.assert_called_once_with(
            "Workspace paths to mount read-only: nothing changed."
        )

    def test_prompt_skips_detected_read_only_paths_seen_before(self) -> None:
        with patch("builtins.input") as input_mock:
            self.assertEqual(
                cli.prompt_new_detected_read_only_paths(
                    [".devcontainer"],
                    ["yarn.lock"],
                    ["yarn.lock"],
                ),
                [".devcontainer"],
            )
        input_mock.assert_not_called()

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
