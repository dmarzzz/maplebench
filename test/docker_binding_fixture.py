"""Inert executable/socket identities for offline Docker-binding tests."""
from pathlib import Path
import socket

from full_client_docker import freeze_binding


def local_binding(test, directory):
    root = Path(directory).resolve()
    executable = root / "docker-fixture"
    endpoint = root / "docker.sock"
    if not executable.exists():
        executable.write_bytes(b"#!/bin/false\n")
        executable.chmod(0o700)
    if not endpoint.exists():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(endpoint))
        endpoint.chmod(0o600)
        test.addCleanup(sock.close)
    return freeze_binding([str(executable)], str(endpoint))
