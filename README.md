# Devcontainer for Claude and Codex CLI

Run the configurator from this repository with:

```bash
uvx --from . configure-devcontainer
```

Or, after publishing/installing the package:

```bash
uvx codex-claude-devcontainer-configurator
```

It configures the current directory by default. To target another workspace:

```bash
uvx --from . configure-devcontainer --workspace /path/to/workspace
```

The configurator prompts for:

- GPU access: no GPUs, all GPUs, or one specific GPU device
- Host TCP ports the container can reach through `host.docker.internal`
- Workspace paths to hide from the container, defaulting to `.jj` and `.git`

The configurator stores its last answers in `.devcontainer-configurator.json`,
so it can be rerun after deleting and recreating the dev container.
