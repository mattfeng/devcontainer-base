"""Interactive CLI for configuring Codex/Claude Code dev containers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEVCONTAINER_FILENAME = "devcontainer.json"
STATE_FILENAME = ".devcontainer-configurator.json"

DEFAULT_HIDDEN_PATHS = [".jj", ".git"]
DEFAULT_HOST_PORTS: list[int] = []
HOST_PORTS_ENV = "DEVCONTAINER_HOST_PORTS"
HOST_GATEWAY_ARG = "--add-host=host.docker.internal:host-gateway"
DEFAULT_GPU = {"mode": "none", "device": ""}
GPU_MODES = {"none", "device", "all"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configure a Codex/Claude Code devcontainer.json."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace containing devcontainer.json. Defaults to the current directory.",
    )
    args = parser.parse_args(argv)

    try:
        return configure(args.workspace.resolve())
    except ValueError as exc:
        print(f"error: {exc}")
        return 1


def configure(workspace: Path) -> int:
    devcontainer_path = workspace / DEVCONTAINER_FILENAME
    state_path = workspace / STATE_FILENAME

    devcontainer = read_json(devcontainer_path)
    state = read_json(state_path, missing_ok=True)

    current_host_ports = list_from_state_or_devcontainer(
        state, "host_ports", read_ports_from_devcontainer(devcontainer)
    )
    current_hidden_paths = list_from_state_or_devcontainer(
        state, "hidden_paths", read_hidden_paths_from_devcontainer(devcontainer)
    )
    current_gpu = gpu_from_state_or_devcontainer(
        state, read_gpu_from_devcontainer(devcontainer)
    )

    host_ports = prompt_host_ports(current_host_ports)
    hidden_paths = prompt_hidden_paths(current_hidden_paths)
    gpu = prompt_gpu(current_gpu)

    update_devcontainer(devcontainer, host_ports, hidden_paths, gpu)
    write_json(devcontainer_path, devcontainer)
    write_json(
        state_path,
        {
            "version": 1,
            "host_ports": host_ports,
            "hidden_paths": hidden_paths,
            "gpu": gpu,
        },
    )

    print()
    print(f"Updated {devcontainer_path}")
    print(f"Remembered answers in {state_path}")
    print("Rebuild or recreate the dev container for changes to take effect.")
    return 0


def read_json(path: Path, *, missing_ok: bool = False) -> dict[str, Any]:
    if missing_ok and not path.exists():
        return {}
    if not path.exists():
        raise ValueError(f"{path} does not exist")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def list_from_state_or_devcontainer(
    state: dict[str, Any], key: str, devcontainer_value: list[Any]
) -> list[Any]:
    value = state.get(key)
    if isinstance(value, list):
        return value
    if key == "hidden_paths":
        if devcontainer_value:
            paths = normalize_hidden_paths(devcontainer_value)
            if set(paths) == set(DEFAULT_HIDDEN_PATHS):
                return DEFAULT_HIDDEN_PATHS[:]
            return paths
        return DEFAULT_HIDDEN_PATHS[:]
    if devcontainer_value:
        return devcontainer_value
    return DEFAULT_HOST_PORTS[:]


def prompt_host_ports(current: list[Any]) -> list[int]:
    normalized_current = normalize_host_ports(current)
    default = format_ports(normalized_current) or "none"
    raw = input(
        "Host TCP ports reachable from the container through "
        f"host.docker.internal [{default}]: "
    ).strip()
    if not raw:
        return normalized_current
    return parse_host_ports(raw)


def prompt_hidden_paths(current: list[Any]) -> list[str]:
    normalized_current = normalize_hidden_paths(current)
    default = ", ".join(normalized_current) or "none"
    raw = input(
        "Workspace paths to hide from the container, comma-separated "
        f"[{default}]: "
    ).strip()
    if not raw:
        return normalized_current
    if raw.lower() in {"none", "no", "-"}:
        return []
    return normalize_hidden_paths(raw.split(","))


def prompt_gpu(current: dict[str, str]) -> dict[str, str]:
    current = normalize_gpu(current)
    default = format_gpu(current)
    raw = input("GPU access: none, all, or device number " f"[{default}]: ").strip()
    if not raw:
        return current
    return parse_gpu(raw)


def parse_host_ports(raw: str) -> list[int]:
    if raw.lower() in {"none", "no", "-"}:
        return []

    ports: list[int] = []
    for token in re.split(r"[\s,]+", raw):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = parse_port(start_text)
            end = parse_port(end_text)
            if start > end:
                raise ValueError(f"Invalid port range {token!r}: start is after end")
            ports.extend(range(start, end + 1))
        else:
            ports.append(parse_port(token))
    return sorted(set(ports))


def parse_port(value: Any) -> int:
    try:
        port = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"Invalid port {value!r}") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"Port {port} is outside 1-65535")
    return port


def normalize_host_ports(values: list[Any]) -> list[int]:
    ports = [parse_port(value) for value in values]
    return sorted(set(ports))


def normalize_hidden_paths(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        path = str(value).strip().replace("\\", "/")
        if not path:
            continue
        path = path.lstrip("/")
        while path.startswith("./"):
            path = path[2:]
        if not path or path == ".":
            raise ValueError("Hidden paths must be inside the workspace")
        parts = Path(path).parts
        if ".." in parts:
            raise ValueError(f"Hidden path {value!r} must not contain '..'")
        if "," in path:
            raise ValueError(f"Hidden path {value!r} must not contain commas")
        if path not in seen:
            normalized.append(path)
            seen.add(path)
    return normalized


def gpu_from_state_or_devcontainer(
    state: dict[str, Any], devcontainer_value: dict[str, str]
) -> dict[str, str]:
    value = state.get("gpu")
    if isinstance(value, dict):
        return normalize_gpu(value)
    return normalize_gpu(devcontainer_value)


def parse_gpu(raw: str) -> dict[str, str]:
    value = raw.strip().lower()
    if value in {"none", "no", "-"}:
        return {"mode": "none", "device": ""}
    if value in {"all", "*"}:
        return {"mode": "all", "device": ""}
    if value.startswith("device="):
        return normalize_gpu({"mode": "device", "device": value.removeprefix("device=")})
    if value.startswith("gpu="):
        return normalize_gpu({"mode": "device", "device": value.removeprefix("gpu=")})
    return normalize_gpu({"mode": "device", "device": raw})


def normalize_gpu(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return DEFAULT_GPU.copy()
    mode = str(value.get("mode", "none")).strip().lower()
    device = str(value.get("device", "")).strip()
    if mode not in GPU_MODES:
        raise ValueError(f"Invalid GPU mode {mode!r}")
    if mode == "device":
        if not re.fullmatch(r"\d+", device):
            raise ValueError("GPU device must be a non-negative device number")
        return {"mode": "device", "device": str(int(device))}
    return {"mode": mode, "device": ""}


def format_gpu(gpu: dict[str, str]) -> str:
    gpu = normalize_gpu(gpu)
    if gpu["mode"] == "device":
        return f"device={gpu['device']}"
    return gpu["mode"]


def read_ports_from_devcontainer(devcontainer: dict[str, Any]) -> list[int]:
    container_env = devcontainer.get("containerEnv", {})
    if not isinstance(container_env, dict):
        return []
    value = container_env.get(HOST_PORTS_ENV, "")
    if not isinstance(value, str) or not value.strip():
        return []
    return parse_host_ports(value)


def read_hidden_paths_from_devcontainer(devcontainer: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for mount in devcontainer.get("mounts", []):
        if not isinstance(mount, str):
            continue
        spec = parse_mount_spec(mount)
        target = spec.get("target", "")
        if (
            spec.get("type") == "volume"
            and "source" not in spec
            and "volume-nocopy" in spec
            and target.startswith("/workspace/")
        ):
            paths.append(target.removeprefix("/workspace/"))
    return normalize_hidden_paths(paths)


def read_gpu_from_devcontainer(devcontainer: dict[str, Any]) -> dict[str, str]:
    run_args = devcontainer.get("runArgs", [])
    if not isinstance(run_args, list):
        return DEFAULT_GPU.copy()
    for index, arg in enumerate(run_args):
        if arg == "--gpus":
            if index + 1 >= len(run_args):
                raise ValueError("devcontainer.json has --gpus without a value")
            return parse_gpu_arg(str(run_args[index + 1]))
        if isinstance(arg, str) and arg.startswith("--gpus="):
            return parse_gpu_arg(arg.removeprefix("--gpus="))
    return DEFAULT_GPU.copy()


def parse_gpu_arg(value: str) -> dict[str, str]:
    if value == "all":
        return {"mode": "all", "device": ""}
    if value.startswith("device="):
        return normalize_gpu({"mode": "device", "device": value.removeprefix("device=")})
    raise ValueError(f"Unsupported --gpus value {value!r}")


def update_devcontainer(
    devcontainer: dict[str, Any],
    host_ports: list[int],
    hidden_paths: list[str],
    gpu: dict[str, str],
) -> None:
    run_args = devcontainer.setdefault("runArgs", [])
    if not isinstance(run_args, list):
        raise ValueError("devcontainer.json runArgs must be a list")
    if HOST_GATEWAY_ARG not in run_args:
        run_args.append(HOST_GATEWAY_ARG)
    devcontainer["runArgs"] = update_gpu_run_args(run_args, gpu)

    container_env = devcontainer.setdefault("containerEnv", {})
    if not isinstance(container_env, dict):
        raise ValueError("devcontainer.json containerEnv must be an object")
    container_env[HOST_PORTS_ENV] = format_ports(host_ports)

    existing_mounts = devcontainer.setdefault("mounts", [])
    if not isinstance(existing_mounts, list):
        raise ValueError("devcontainer.json mounts must be a list")

    retained_mounts = [
        mount for mount in existing_mounts if not is_managed_hidden_mount(mount)
    ]
    retained_mounts.extend(hidden_mount(path) for path in hidden_paths)
    devcontainer["mounts"] = retained_mounts


def update_gpu_run_args(run_args: list[Any], gpu: dict[str, str]) -> list[Any]:
    normalized_gpu = normalize_gpu(gpu)
    retained_args: list[Any] = []
    skip_next = False
    for arg in run_args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--gpus":
            skip_next = True
            continue
        if isinstance(arg, str) and arg.startswith("--gpus="):
            continue
        retained_args.append(arg)

    if normalized_gpu["mode"] == "all":
        retained_args.append("--gpus=all")
    elif normalized_gpu["mode"] == "device":
        retained_args.append(f"--gpus=device={normalized_gpu['device']}")
    return retained_args


def format_ports(ports: list[int]) -> str:
    return ",".join(str(port) for port in normalize_host_ports(ports))


def hidden_mount(path: str) -> str:
    return f"target=/workspace/{path},type=volume,volume-nocopy"


def is_managed_hidden_mount(mount: Any) -> bool:
    if not isinstance(mount, str):
        return False
    spec = parse_mount_spec(mount)
    target = spec.get("target", "")
    return (
        spec.get("type") == "volume"
        and "source" not in spec
        and "volume-nocopy" in spec
        and target.startswith("/workspace/")
    )


def parse_mount_spec(mount: str) -> dict[str, str | bool]:
    spec: dict[str, str | bool] = {}
    for part in mount.split(","):
        key, separator, value = part.partition("=")
        key = key.strip()
        if not key:
            continue
        spec[key] = value.strip() if separator else True
    return spec


if __name__ == "__main__":
    raise SystemExit(main())
