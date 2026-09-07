"""Derive a private, append-only startup log configuration; never touch a log/service.

The caller supplies the exact original XML hash and every host-specific path. Only
the known main-log routes (Root and non-additive net.packet.logging) are supported.
Existing logging is retained semantically; the generated File appender has no
rollover policy. The lifecycle consumer must still prove the preserved prefix,
current JVM-owned descriptor, exact process identity and listening sockets. This
tool does not certify a startup, create the log, rotate it, or change a service.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid
import xml.etree.ElementTree as ET


MAX_XML_BYTES = 128 * 1024
MAX_ELEMENTS = 2048
SHA = re.compile(r"[0-9a-f]{64}\Z")
DEFERRED_DATE_DIRECTORIES = frozenset({"$${date:yyyy-MM}", "$${date:yyyy-MM-dd}"})
SAFE_CODES = frozenset("""
invalid_sha256 original_hash_mismatch invalid_xml xml_limit xml_declaration_forbidden
unsupported_configuration duplicate_configuration_name conflicting_lifecycle_appender
unsupported_main_log_routes unsupported_main_log_layout invalid_absolute_path
unsupported_log_path
private_parent_required invalid_log_owner log_path_not_private original_not_regular
original_changed original_unavailable output_exists output_unavailable
""".split())


class LogConfigError(ValueError):
    """A fixed safe code; never expose raw XML or an operating-system exception."""


def require(condition, code):
    if not condition:
        raise LogConfigError(code)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def absolute_path(value):
    require(isinstance(value, str) and 0 < len(value) <= 4096
            and all(ord(char) >= 32 for char in value) and "$" not in value,
            "invalid_absolute_path")
    path = Path(value)
    require(path.is_absolute() and str(path) == value and ".." not in path.parts,
            "invalid_absolute_path")
    return path


def _parse(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_XML_BYTES, "xml_limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise LogConfigError("invalid_xml") from error
    # Reject declarations before the XML parser can expand an internal entity.
    require(not re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I), "xml_declaration_forbidden")
    body = re.sub(r"\A<\?xml\s+version=['\"]1\.0['\"](?:\s+encoding=['\"]UTF-8['\"])?\s*\?>",
                  "", text, count=1, flags=re.I)
    require("<?" not in body and not re.search(r"<!\s*\[CDATA\[", body), "xml_declaration_forbidden")
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(text, parser=parser)
    except (ET.ParseError, ValueError) as error:
        raise LogConfigError("invalid_xml") from error
    count = 0
    stack = [(root, 0)]
    while stack:
        element, depth = stack.pop()
        count += 1
        require(count <= MAX_ELEMENTS and depth <= 32, "xml_limit")
        if isinstance(element.tag, str):
            require("{" not in element.tag and ":" not in element.tag, "unsupported_configuration")
        stack.extend((child, depth + 1) for child in element)
    return root


def _children(element):
    return [child for child in element if isinstance(child.tag, str)]


def _single(parent, tag):
    values = [child for child in _children(parent) if child.tag == tag]
    require(len(values) == 1, "unsupported_configuration")
    return values[0]


def _names(elements):
    names = [element.get("name") for element in elements]
    require(all(isinstance(name, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", name) for name in names)
            and len(names) == len(set(names)), "duplicate_configuration_name")


def _expanded_log_value(value, properties, *, deferred_dates=False):
    values = {item.get("name"): item.text or "" for item in _children(properties)}
    require(isinstance(value, str) and 0 < len(value) <= 4096, "unsupported_log_path")
    def without_dates(text):
        if deferred_dates:
            for token in DEFERRED_DATE_DIRECTORIES:
                text = text.replace(token, "")
        return text
    for _ in range(32):
        remaining = without_dates(value)
        if "$" not in remaining:
            break
        require("$${" not in remaining, "unsupported_log_path")
        def replace(match):
            require(match[1] in values, "unsupported_log_path")
            return values[match[1]]
        updated = re.sub(r"\$\{([A-Za-z][A-Za-z0-9_.-]{0,127})\}", replace, value)
        require(updated != value and 0 < len(updated) <= 4096, "unsupported_log_path")
        value = updated
    require("$" not in without_dates(value) and all(ord(char) >= 32 for char in value), "unsupported_log_path")
    return value


def _expanded_log_path(value, properties, working_directory):
    value = _expanded_log_value(value, properties)
    path = Path(value)
    # Collapsing '..' before resolving symlinks could hide a real collision.
    require(".." not in path.parts, "unsupported_log_path")
    if not path.is_absolute():
        path = working_directory / path
    return path


def _existing_log_paths(appenders, properties, working_directory):
    for appender in _children(appenders):
        if appender.tag in {"File", "RollingFile"}:
            yield _expanded_log_path(appender.get("fileName"), properties, working_directory)


def _archive_directories(appenders, properties, working_directory):
    for appender in _children(appenders):
        if appender.tag == "RollingFile":
            value = _expanded_log_value(appender.get("filePattern"), properties, deferred_dates=True)
            pattern = Path(value)
            require(".." not in pattern.parts and "$" not in pattern.name, "unsupported_log_path")
            directories = pattern.parts[:-1]
            dynamic = []
            for index, component in enumerate(directories):
                if "$" in component:
                    require(component in DEFERRED_DATE_DIRECTORIES, "unsupported_log_path")
                    dynamic.append(index)
                else:
                    require("%" not in component, "unsupported_log_path")
            if dynamic:
                # The deployed logger has two deferred date-only directory
                # components. Neither format can produce a path separator.
                # Exclude the ENTIRE static prefix, including all future dates;
                # never substitute today's date or guess a generated filename.
                require(len(dynamic) <= 2, "unsupported_log_path")
                prefix = directories[:dynamic[0]]
                require(any(part not in {"", ".", pattern.anchor} for part in prefix),
                        "unsupported_log_path")
                directory = Path(*prefix)
            else:
                directory = pattern.parent
            if not directory.is_absolute():
                directory = working_directory / directory
            yield directory


def _separate_from_logs(destination, active_paths, archive_directories):
    require(destination not in active_paths, "conflicting_lifecycle_appender")
    require(not any(destination == directory or directory in destination.parents
                    for directory in archive_directories), "conflicting_lifecycle_appender")


def derive_config(original, expected_sha256, log_path, working_directory):
    """Return deterministic XML bytes; no filesystem access or mutable defaults."""
    require(isinstance(expected_sha256, str) and SHA.fullmatch(expected_sha256), "invalid_sha256")
    require(isinstance(original, bytes) and 0 < len(original) <= MAX_XML_BYTES, "xml_limit")
    require(sha256(original) == expected_sha256, "original_hash_mismatch")
    log_path = absolute_path(log_path)
    working_directory = absolute_path(working_directory)
    root = _parse(original)
    require(root.tag == "Configuration" and root.get("monitorInterval", "0") == "0"
            and {item.tag for item in _children(root)} == {"Properties", "Appenders", "Loggers"},
            "unsupported_configuration")
    properties, appenders, loggers = (_single(root, name) for name in ("Properties", "Appenders", "Loggers"))
    require(all(item.tag == "Property" for item in _children(properties)), "unsupported_configuration")
    _names(_children(properties))
    require(all(item.tag in {"Console", "File", "RollingFile"} for item in _children(appenders)),
            "unsupported_configuration")
    _names(_children(appenders))
    appender_names = {item.get("name") for item in _children(appenders)}
    require(not any(item.get("name") == "Lifecycle" for item in _children(appenders)),
            "conflicting_lifecycle_appender")
    _separate_from_logs(log_path, set(_existing_log_paths(appenders, properties, working_directory)),
                        set(_archive_directories(appenders, properties, working_directory)))
    main = [item for item in _children(appenders) if item.get("name") == "File"]
    require(len(main) == 1 and main[0].tag == "RollingFile", "unsupported_configuration")
    require({item.tag for item in _children(main[0])} == {"PatternLayout", "Policies"},
            "unsupported_main_log_layout")
    layout = _single(main[0], "PatternLayout")
    _single(main[0], "Policies")
    require(all(item.tag in {"Root", "Logger"} for item in _children(loggers)), "unsupported_configuration")
    logger_root = _single(loggers, "Root")
    named = [item for item in _children(loggers) if item.tag == "Logger"]
    _names(named)
    packet = [item for item in named if item.get("name") == "net.packet.logging"]
    require(len(packet) == 1 and packet[0].get("additivity") == "false", "unsupported_main_log_routes")
    routes = []
    for logger in _children(loggers):
        refs = [item for item in _children(logger) if item.tag == "AppenderRef"]
        names = [item.get("ref") for item in refs]
        require(all(isinstance(name, str) and name for name in names) and len(names) == len(set(names)),
                "duplicate_configuration_name")
        require(set(names) <= appender_names, "unsupported_main_log_routes")
        require("Lifecycle" not in names, "conflicting_lifecycle_appender")
        routes.extend((logger, ref) for ref in refs if ref.get("ref") == "File")
    require(len(routes) == 2 and {id(logger) for logger, _ in routes} == {id(logger_root), id(packet[0])},
            "unsupported_main_log_routes")
    appender = ET.SubElement(appenders, "File", {"name": "Lifecycle", "fileName": str(log_path),
                                               "append": "true", "immediateFlush": "true"})
    appender.append(copy.deepcopy(layout))
    for logger, reference in routes:
        cloned = copy.deepcopy(reference)
        cloned.set("ref", "Lifecycle")
        logger.append(cloned)
    result = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    require(len(result) <= MAX_XML_BYTES, "xml_limit")
    return result


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def read_original(path):
    path = absolute_path(str(path))
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            require(stat.S_ISREG(before.st_mode), "original_not_regular")
            require(0 < before.st_size <= MAX_XML_BYTES, "xml_limit")
            chunks = []
            remaining = MAX_XML_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            require(len(raw) <= MAX_XML_BYTES, "xml_limit")
            require(len(raw) == before.st_size and _identity(before) == _identity(os.fstat(descriptor))
                    == _identity(path.lstat()), "original_changed")
            return raw
        finally:
            os.close(descriptor)
    except OSError as error:
        raise LogConfigError("original_unavailable") from error


def _parent(path, uid):
    try:
        require(path.parent.resolve(strict=True) == path.parent, "private_parent_required")
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if not (stat.S_ISDIR(info.st_mode) and info.st_uid == uid
                and stat.S_IMODE(info.st_mode) == 0o700):
            os.close(descriptor)
            raise LogConfigError("private_parent_required")
        return descriptor
    except OSError as error:
        raise LogConfigError("private_parent_required") from error


def _log_path(path, owner_uid):
    require(type(owner_uid) is int and 0 <= owner_uid <= 2**32 - 2, "invalid_log_owner")
    descriptor = _parent(path, owner_uid)
    try:
        try:
            info = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return
        require(stat.S_ISREG(info.st_mode) and info.st_uid == owner_uid
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1, "log_path_not_private")
    except OSError as error:
        raise LogConfigError("log_path_not_private") from error
    finally:
        os.close(descriptor)


def _publish(path, raw):
    descriptor = _parent(path, os.geteuid())
    temporary = ".lifecycle-log-config-" + uuid.uuid4().hex
    created = False
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
        created = True
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        # Link publication is atomic and refuses every existing destination,
        # including a symlink. A crash leaves either no output or complete bytes.
        os.link(temporary, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
        os.fsync(descriptor)
    except FileExistsError as error:
        raise LogConfigError("output_exists") from error
    except OSError as error:
        raise LogConfigError("output_unavailable") from error
    finally:
        if created:
            os.unlink(temporary, dir_fd=descriptor)
            os.fsync(descriptor)
        os.close(descriptor)


def prepare_config(original_path, expected_sha256, output_path, log_path, log_owner_uid, working_directory):
    original_path, output_path, log_path = (absolute_path(str(value)) for value in
                                           (original_path, output_path, log_path))
    require(len({original_path, output_path, log_path}) == 3, "invalid_absolute_path")
    original = read_original(original_path)
    working_directory = absolute_path(str(working_directory))
    try:
        require(working_directory.resolve(strict=True) == working_directory and working_directory.is_dir(),
                "invalid_absolute_path")
    except OSError as error:
        raise LogConfigError("invalid_absolute_path") from error
    result = derive_config(original, expected_sha256, str(log_path), str(working_directory))
    _log_path(log_path, log_owner_uid)
    # Also reject actual filesystem aliases; the pure transformer can resolve
    # property/relative paths, while only preparation can inspect their identity.
    tree = _parse(original)
    appenders, properties = _single(tree, "Appenders"), _single(tree, "Properties")
    active_paths = set(_existing_log_paths(appenders, properties, working_directory))
    archive_directories = set(_archive_directories(appenders, properties, working_directory))
    try:
        for destination in (log_path, output_path):
            _separate_from_logs(destination, active_paths, archive_directories)
            _separate_from_logs(destination.resolve(), {path.resolve() for path in active_paths},
                                {path.resolve() for path in archive_directories})
            for existing in active_paths:
                if existing.exists() and destination.exists():
                    require(not os.path.samefile(existing, destination), "conflicting_lifecycle_appender")
    except (OSError, RuntimeError) as error:
        raise LogConfigError("unsupported_log_path") from error
    _publish(output_path, result)
    return {"schema_version": 1, "kind": "lifecycle_log_configuration",
            "original_sha256": sha256(original), "output_sha256": sha256(result),
            "output_bytes": len(result), "log_created": False, "services_changed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True)
    parser.add_argument("--original-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--log-owner-uid", required=True, type=int)
    parser.add_argument("--working-directory", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_config(args.original, args.original_sha256, args.output, args.log_path,
                                args.log_owner_uid, args.working_directory)
    except (LogConfigError, OSError) as error:
        code = str(error) if isinstance(error, LogConfigError) and str(error) in SAFE_CODES else "output_unavailable"
        print(json.dumps({"ok": False, "error": code}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
