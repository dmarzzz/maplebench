"""Frozen local Docker invocation for full-client trials; no inherited routing.

The optional launcher is exactly /usr/bin/sudo -n. This is an operator-owned
privilege boundary, never a generated command. Image execution and cleanup use
the same invocation, including its fresh empty Docker configuration.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import time


DOCKER_ERROR_CODES = frozenset({"invalid_docker_binding", "docker_binding_required",
    "docker_binding_mismatch", "docker_executable_changed", "untrusted_docker_executable",
    "invalid_docker_socket", "invalid_docker_command", "docker_binding_unavailable"})


class DockerBindingError(ValueError):
    """Fixed, credential-free failure code."""


def require(value, code):
    if not value:
        raise DockerBindingError(code)


def _path(value):
    require(isinstance(value, str) and 0 < len(value) <= 4096
            and Path(value).is_absolute() and ".." not in Path(value).parts
            and not any(ord(c) < 32 for c in value), "invalid_docker_binding")
    return Path(value)


def executable_reference(path, *, launcher=False):
    path = _path(path)
    try:
        require(path.resolve(strict=True) == path, "untrusted_docker_executable")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 128 * 1024**2
                    and before.st_uid in ((0,) if launcher else (0, os.geteuid()))
                    and not before.st_mode & (0o022 | stat.S_ISGID)
                    and (launcher or not before.st_mode & stat.S_ISUID)
                    and os.access(path, os.X_OK), "untrusted_docker_executable")
            digest = hashlib.sha256()
            count, deadline = 0, time.monotonic() + 10
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                count += len(chunk)
                require(count <= 128 * 1024**2 and time.monotonic() < deadline, "docker_executable_changed")
                digest.update(chunk)
            identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                                     info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_uid)
            require(identity(before) == identity(os.fstat(stream.fileno()))
                    == identity(path.lstat()), "docker_executable_changed")
        return {"path": str(path), "sha256": digest.hexdigest()}
    except OSError as error:
        raise DockerBindingError("docker_binding_unavailable") from error


def validate_binding(binding, *, verify_files=True):
    require(isinstance(binding, dict)
            and set(binding) == {"schema_version", "executable", "launcher", "socket_path"}
            and type(binding["schema_version"]) is int and binding["schema_version"] == 1,
            "invalid_docker_binding")
    result = {"schema_version": 1, "socket_path": str(_path(binding["socket_path"]))}
    for name in ("executable", "launcher"):
        value = binding[name]
        if name == "launcher" and value is None:
            result[name] = None
            continue
        require(isinstance(value, dict) and set(value) == {"path", "sha256"}
                and isinstance(value["sha256"], str)
                and re.fullmatch("[0-9a-f]{64}", value["sha256"]), "invalid_docker_binding")
        path = str(_path(value["path"]))
        require(name != "launcher" or path == "/usr/bin/sudo", "invalid_docker_command")
        result[name] = {"path": path, "sha256": value["sha256"]}
        if verify_files:
            require(executable_reference(path, launcher=name == "launcher") == result[name],
                    "docker_executable_changed")
    if verify_files:
        try:
            path = Path(result["socket_path"])
            info = path.lstat()
            require(path.resolve(strict=True) == path and stat.S_ISSOCK(info.st_mode)
                    and info.st_uid in (0, os.geteuid()) and not info.st_mode & 0o002,
                    "invalid_docker_socket")
        except OSError as error:
            raise DockerBindingError("docker_binding_unavailable") from error
    return result


def freeze_binding(command, socket_path):
    require(isinstance(command, list) and (len(command) == 1
            or len(command) == 3 and command[:2] == ["/usr/bin/sudo", "-n"]),
            "invalid_docker_command")
    try:
        executable = str(_path(command[-1]).resolve(strict=True))
        endpoint = str(_path(socket_path).resolve(strict=True))
    except OSError as error:
        raise DockerBindingError("docker_binding_unavailable") from error
    binding = {"schema_version": 1, "executable": executable_reference(executable),
               "launcher": executable_reference("/usr/bin/sudo", launcher=True) if len(command) == 3 else None,
               "socket_path": endpoint}
    return validate_binding(binding)


def configured_command(binding):
    binding = validate_binding(binding, verify_files=False)
    return (["/usr/bin/sudo", "-n"] if binding["launcher"] else []) + [binding["executable"]["path"]]


@contextmanager
def bound_invocation(binding):
    binding = validate_binding(binding)
    # CLI flags survive sudo's environment reset. Empty config also prevents
    # currentContext, credential helpers and ~/.docker/config.json discovery.
    with tempfile.TemporaryDirectory(prefix="maplebench-docker-", dir="/tmp") as config:
        Path(config, "config.json").write_text("{}\n")
        prefix = configured_command(binding) + ["--config", config, "--host", "unix://" + binding["socket_path"]]
        yield prefix, {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": config, "DOCKER_CONFIG": config}
