"""Pin existing full-client runtime inputs without copying them or changing a host.

This read-only inventory is not a database baseline or an immutable snapshot.
The runtime backend must verify it before and after a trial. Configuration and
the resulting host-specific manifest belong only in private runtime storage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time


SCHEMA_FIELDS = {"schema_version", "working_directory", "wz_path", "inventory_roots",
                 "server_jar", "client_js", "client_wasm", "docker_image", "docker_image_id", "files",
                 "extra_files"}
PATH_FIELDS = ("working_directory", "wz_path", "server_jar", "client_js", "client_wasm")
ARTIFACT_FIELDS = ("server_jar", "client_js", "client_wasm")
SHA = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
IMAGE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,254}\Z")
DEFAULT_LIMITS = {"max_files": 100000, "max_total_bytes": 32 * 1024**3, "timeout_seconds": 120}
HARD_LIMITS = {"max_files": 200000, "max_total_bytes": 128 * 1024**3, "timeout_seconds": 300}
JSON_LIMIT = 64 * 1024**2


class FreezeError(ValueError):
    """Safe fixed failure code; never include file contents or command errors."""


def require(condition, code):
    if not condition:
        raise FreezeError(code)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as error:
        raise FreezeError("invalid_json") from error


def _parse(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate_json_key")
            value[key] = item
        return value
    def invalid(_):
        raise FreezeError("nonfinite_json")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        if isinstance(error, FreezeError):
            raise
        raise FreezeError("invalid_json") from error


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _absolute(value, *, directory=False):
    require(isinstance(value, str) and "\0" not in value and Path(value).is_absolute(), "absolute_path_required")
    try:
        path = Path(value).resolve(strict=True)
        mode = path.stat().st_mode
        require(stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode), "invalid_configured_path")
        return path
    except (OSError, RuntimeError) as error:
        raise FreezeError("configured_path_unavailable") from error


def _limits(value):
    require(value is None or isinstance(value, dict) and set(value) <= set(DEFAULT_LIMITS), "invalid_limits")
    selected = DEFAULT_LIMITS | (value or {})
    for name, maximum in HARD_LIMITS.items():
        require(type(selected[name]) is int and 1 <= selected[name] <= maximum, "invalid_limit_" + name)
    return selected


class Inventory:
    def __init__(self, limits):
        self.limits = limits
        self.deadline = time.monotonic() + limits["timeout_seconds"]
        self.files = {}
        self.directories = {}
        self.total_bytes = 0
        self.entries = 0

    def remaining(self):
        left = self.deadline - time.monotonic()
        require(left > 0, "inventory_timeout")
        return left

    def hash_fd(self, descriptor, path, expected=None):
        self.remaining()
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode), "inventory_non_regular_file")
        require(expected is None or _identity(before) == _identity(expected), "inventory_entry_changed")
        key = str(path)
        if key in self.files:
            require(_identity(before) == self.files[key]["identity"], "inventory_file_changed")
            return self.files[key]["reference"]
        require(len(self.files) < self.limits["max_files"], "inventory_file_limit")
        require(before.st_size <= self.limits["max_total_bytes"] - self.total_bytes, "inventory_byte_limit")
        digest = hashlib.sha256()
        size = 0
        while True:
            self.remaining()
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            require(size <= self.limits["max_total_bytes"] - self.total_bytes, "inventory_byte_limit")
            digest.update(chunk)
        after = os.fstat(descriptor)
        require(size == before.st_size and _identity(before) == _identity(after), "inventory_file_changed")
        reference = {"path": key, "sha256": digest.hexdigest()}
        self.files[key] = {"identity": _identity(after), "reference": reference}
        self.total_bytes += size
        return reference

    def hash_path(self, path):
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            return self.hash_fd(descriptor, path, path.lstat())
        finally:
            os.close(descriptor)

    def tree(self, root):
        """Walk using anchored directory descriptors, rejecting all descendant links."""
        found = []
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

        def visit(descriptor, path, depth):
            self.remaining()
            require(depth <= 128, "inventory_depth_limit")
            before = os.fstat(descriptor)
            require(stat.S_ISDIR(before.st_mode), "inventory_non_directory")
            names = []
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    self.remaining()
                    self.entries += 1
                    require(self.entries <= self.limits["max_files"] * 4 + 64, "inventory_entry_limit")
                    names.append(entry.name)
            for name in sorted(names):
                self.remaining()
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                require(not stat.S_ISLNK(info.st_mode), "inventory_symlink_descendant")
                child_path = path / name
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, flags, dir_fd=descriptor)
                    try:
                        require(_identity(os.fstat(child)) == _identity(info), "inventory_entry_changed")
                        visit(child, child_path, depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    child = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                                    | getattr(os, "O_NONBLOCK", 0), dir_fd=descriptor)
                    try:
                        found.append(self.hash_fd(child, child_path, info))
                    finally:
                        os.close(child)
                else:
                    raise FreezeError("inventory_non_regular_file")
            require(_identity(before) == _identity(os.fstat(descriptor)), "inventory_directory_changed")
            self.directories[str(path)] = _identity(before)

        descriptor = os.open(root, flags)
        try:
            visit(descriptor, root, 0)
        finally:
            os.close(descriptor)
        return found

    def stable(self):
        # Recheck all identities after the full scan, so a previously hashed
        # source cannot be changed while a later source is being inventoried.
        for path, identity in self.directories.items():
            self.remaining()
            require(_identity(Path(path).lstat()) == identity, "inventory_directory_changed")
        for path, value in self.files.items():
            self.remaining()
            require(_identity(Path(path).lstat()) == value["identity"], "inventory_file_changed")


def inspect_image(docker_command, image, timeout_seconds, docker_socket="/var/run/docker.sock"):
    """Inspect one existing image through a fixed local Unix-socket command."""
    require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 300,
            "invalid_docker_timeout")
    require(isinstance(docker_command, list) and len(docker_command) == 1
            and isinstance(docker_command[0], str) and Path(docker_command[0]).is_absolute(),
            "invalid_docker_command")
    require(isinstance(image, str) and IMAGE_REF.fullmatch(image), "invalid_docker_image")
    require(isinstance(docker_socket, str) and "\0" not in docker_socket
            and Path(docker_socket).is_absolute() and ".." not in Path(docker_socket).parts,
            "invalid_docker_socket")
    info = Path(docker_command[0]).stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid in (0, os.geteuid())
            and not info.st_mode & (0o022 | stat.S_ISUID | stat.S_ISGID)
            and os.access(docker_command[0], os.X_OK), "untrusted_docker_executable")
    command = [docker_command[0], "--host", "unix://" + docker_socket, "image", "inspect",
               "--format", "{{.Id}}", "--", image]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, check=False, timeout=min(timeout_seconds, 10),
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError) as error:
        raise FreezeError("docker_image_inspection_failed") from error
    require(result.returncode == 0 and len(result.stdout) <= 256, "docker_image_inspection_failed")
    try:
        identity = result.stdout.decode("ascii").strip()
    except UnicodeError as error:
        raise FreezeError("invalid_docker_image_id") from error
    require(IMAGE_ID.fullmatch(identity), "invalid_docker_image_id")
    return identity


def build_manifest(config):
    """Read and pin current configured inputs; never pull, copy assets, or mutate runtime."""
    required = {*PATH_FIELDS, "docker_image", "docker_command"}
    require(isinstance(config, dict) and required <= set(config)
            and set(config) <= required | {"limits", "docker_socket", "extra_files"}, "invalid_config_fields")
    try:
        inventory = Inventory(_limits(config.get("limits")))
        extra_values = config.get("extra_files", [])
        require(isinstance(extra_values, list) and len(extra_values) <= inventory.limits["max_files"],
                "invalid_extra_files")
        extras = []
        for value in extra_values:
            inventory.remaining()
            extras.append(_absolute(value))
        require(len(set(extras)) == len(extras), "duplicate_extra_file")
        paths = {name: _absolute(config[name], directory=name in ("working_directory", "wz_path"))
                 for name in PATH_FIELDS}
        scripts = _absolute(str(paths["working_directory"] / "scripts"), directory=True)
        configuration = _absolute(str(paths["working_directory"] / "config.yaml"))
        roots = sorted({scripts, paths["wz_path"]})
        require(len(roots) == 2 and not any(left in right.parents for left in roots for right in roots if left != right),
                "distinct_inventory_roots_required")
        socket = config.get("docker_socket", "/var/run/docker.sock")
        image = inspect_image(config["docker_command"], config["docker_image"], inventory.remaining(), socket)
        references = {name: inventory.hash_path(paths[name]) for name in ARTIFACT_FIELDS}
        # These explicit pins cover the served page, wrapper, controller, and
        # imported code outside the game scripts/WZ roots. Never discover or
        # execute imports: the trusted host configuration lists every dependency.
        extra_references = [inventory.hash_path(path) for path in sorted(extras)]
        files = {str(configuration): inventory.hash_path(configuration)}
        for root in roots:
            for reference in inventory.tree(root):
                files[reference["path"]] = reference
        inventory.stable()
        require(inspect_image(config["docker_command"], config["docker_image"], inventory.remaining(), socket) == image,
                "docker_image_changed")
        inventory.stable()
        return {"schema_version": 1, "working_directory": str(paths["working_directory"]),
                "wz_path": str(paths["wz_path"]), "inventory_roots": [str(root) for root in roots],
                **references, "docker_image": config["docker_image"], "docker_image_id": image,
                "files": [files[path] for path in sorted(files)], "extra_files": extra_references}
    except (OSError, RuntimeError) as error:
        raise FreezeError("runtime_input_unavailable") from error


def verify_manifest(manifest, *, docker_command, limits=None, docker_socket="/var/run/docker.sock"):
    """Rebuild the complete inventory and reject edits, additions, deletions, or image drift."""
    require(isinstance(manifest, dict) and set(manifest) == SCHEMA_FIELDS
            and type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1,
            "invalid_manifest_schema")
    require(isinstance(manifest.get("docker_image_id"), str)
            and IMAGE_ID.fullmatch(manifest["docker_image_id"]), "invalid_docker_image_id")
    references = [manifest.get(name) for name in ARTIFACT_FIELDS]
    for name in ("files", "extra_files"):
        require(isinstance(manifest.get(name), list)
                and len(manifest[name]) <= _limits(limits)["max_files"], "invalid_manifest_files")
        references += manifest[name]
    for reference in references:
        require(isinstance(reference, dict) and set(reference) == {"path", "sha256"}
                and isinstance(reference["path"], str) and Path(reference["path"]).is_absolute()
                and isinstance(reference["sha256"], str) and SHA.fullmatch(reference["sha256"]),
                "invalid_manifest_reference")
    for name in ("files", "extra_files"):
        require(len({item["path"] for item in manifest[name]}) == len(manifest[name]),
                "duplicate_manifest_file")
    config = {"working_directory": manifest["working_directory"], "wz_path": manifest["wz_path"],
              **{name: manifest[name]["path"] for name in ARTIFACT_FIELDS},
              "docker_image": manifest["docker_image"], "docker_command": docker_command,
              "docker_socket": docker_socket, "limits": limits,
              "extra_files": [item["path"] for item in manifest["extra_files"]]}
    actual = build_manifest(config)
    require(_json(actual) == _json(manifest), "runtime_manifest_drift")
    return manifest


def read_private_json(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid in (0, os.geteuid())
                and not before.st_mode & 0o077 and before.st_size <= JSON_LIMIT, "private_json_required")
        raw = stream.read(JSON_LIMIT + 1)
        require(len(raw) <= JSON_LIMIT and _identity(before) == _identity(os.fstat(stream.fileno())),
                "private_json_changed")
    return _parse(raw)


def write_manifest(path, manifest):
    """Create a new private manifest under an existing private parent, without overwrite."""
    path = Path(path).absolute()
    parent = path.parent
    info = parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and parent.resolve() == parent
            and info.st_uid == os.geteuid() and not info.st_mode & 0o077, "private_output_parent_required")
    raw = _json(manifest) + b"\n"
    require(len(raw) <= JSON_LIMIT, "manifest_too_large")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Private host configuration, never model output")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = read_private_json(args.config)
        if args.command == "create":
            manifest = build_manifest(config)
            digest = write_manifest(args.output, manifest)
            result = {"frozen": True, "manifest_sha256": digest, "file_count": len(manifest["files"])}
        else:
            manifest = read_private_json(args.manifest)
            # CLI configuration is also authoritative: do not verify an obsolete
            # manifest's old paths after the operator switched configured inputs.
            require(_json(build_manifest(config)) == _json(manifest), "runtime_manifest_drift")
            result = {"verified": True, "file_count": len(manifest["files"])}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        code = str(error) if isinstance(error, FreezeError) else "runtime_freeze_failed"
        print(json.dumps({"frozen": False, "verified": False, "code": code}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
