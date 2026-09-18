"""Hash a knowledge pack directory so reference material is a frozen input.

The pack hash pins what a model was allowed to read. It is separate from
`scenario_fingerprint`: fixture identity and reference material version
independently. This script only reads files and prints JSON; it never writes
into the pack, contacts a network, or touches runtime state.

    python3 scripts/knowledge_pack.py knowledge/hero-cave

Exit codes: 0 manifest printed, 1 invalid pack, 2 unreadable path.
"""
import hashlib
import json
import os
import sys

MAX_FILE_BYTES = 1 << 20
MAX_FILES = 64
ALLOWED_SUFFIXES = ('.md',)


class PackError(ValueError):
    pass


def _entries(root):
    """Relative paths of pack files, sorted, with traversal and type checks."""
    if not os.path.isdir(root) or os.path.islink(root):
        raise PackError('pack_root_not_a_directory')
    found = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
        for name in sorted(filenames):
            if name.startswith('.'):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                raise PackError('pack_contains_non_regular_file')
            if not name.endswith(ALLOWED_SUFFIXES):
                raise PackError('pack_contains_unexpected_suffix')
            rel = os.path.relpath(full, root)
            if rel.startswith('..') or os.path.isabs(rel):
                raise PackError('pack_path_escapes_root')
            found.append(rel.replace(os.sep, '/'))
    if not found:
        raise PackError('pack_is_empty')
    if len(found) > MAX_FILES:
        raise PackError('pack_has_too_many_files')
    return sorted(found)


def build(root):
    """Return the manifest for a pack directory."""
    files = []
    overall = hashlib.sha256()
    for rel in _entries(root):
        with open(os.path.join(root, rel), 'rb') as handle:
            raw = handle.read()
        if len(raw) > MAX_FILE_BYTES:
            raise PackError('pack_file_too_large')
        try:
            raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise PackError('pack_file_not_utf8') from error
        digest = hashlib.sha256(raw).hexdigest()
        files.append({'path': rel, 'bytes': len(raw), 'sha256': digest})
        # Bind path and content together so a rename is a different pack.
        overall.update(b'%d:%s\0' % (len(rel), rel.encode('utf-8')))
        overall.update(bytes.fromhex(digest))
    return {
        'schema_version': 1,
        'pack_id': os.path.basename(os.path.normpath(root)),
        'file_count': len(files),
        'total_bytes': sum(entry['bytes'] for entry in files),
        'files': files,
        'pack_sha256': overall.hexdigest(),
    }


def main(argv):
    if len(argv) != 2:
        sys.stderr.write('usage: knowledge_pack.py <pack-directory>\n')
        return 2
    try:
        manifest = build(argv[1])
    except PackError as error:
        sys.stderr.write('invalid pack: %s\n' % error)
        return 1
    except OSError as error:
        sys.stderr.write('unreadable: %s\n' % error)
        return 2
    json.dump(manifest, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
