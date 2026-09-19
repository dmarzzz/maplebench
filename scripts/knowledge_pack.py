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
import re
import sys

MAX_FILE_BYTES = 1 << 20
MAX_FILES = 64
ALLOWED_SUFFIXES = ('.json', '.md')
PACK_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
MANIFEST_FIELDS = {'schema_version', 'pack_id', 'file_count', 'total_bytes',
                   'files', 'pack_sha256'}
FILE_FIELDS = {'path', 'bytes', 'sha256'}


class PackError(ValueError):
    pass


def _entries(root):
    """Relative paths of pack files, sorted, with traversal and type checks."""
    if not os.path.isdir(root) or os.path.islink(root):
        raise PackError('pack_root_not_a_directory')
    found = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        visible = []
        for name in sorted(dirnames):
            if name.startswith('.'):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isdir(full):
                raise PackError('pack_contains_non_regular_file')
            visible.append(name)
        dirnames[:] = visible
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
    pack_id = os.path.basename(os.path.normpath(root))
    if PACK_ID.fullmatch(pack_id) is None:
        raise PackError('invalid_pack_id')
    return {
        'schema_version': 1,
        'pack_id': pack_id,
        'file_count': len(files),
        'total_bytes': sum(entry['bytes'] for entry in files),
        'files': files,
        'pack_sha256': overall.hexdigest(),
    }


def validate_manifest(value):
    """Validate a frozen manifest without trusting it to name local files."""
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        raise PackError('invalid_pack_manifest')
    if (type(value.get('schema_version')) is not int or value['schema_version'] != 1
            or not isinstance(value.get('pack_id'), str)
            or PACK_ID.fullmatch(value['pack_id']) is None
            or type(value.get('file_count')) is not int
            or not 1 <= value['file_count'] <= MAX_FILES
            or type(value.get('total_bytes')) is not int
            or not 1 <= value['total_bytes'] <= MAX_FILES * MAX_FILE_BYTES
            or not isinstance(value.get('files'), list)
            or len(value['files']) != value['file_count']
            or not isinstance(value.get('pack_sha256'), str)
            or re.fullmatch(r'[0-9a-f]{64}', value['pack_sha256']) is None):
        raise PackError('invalid_pack_manifest')
    paths = []
    total = 0
    for entry in value['files']:
        if (not isinstance(entry, dict) or set(entry) != FILE_FIELDS
                or not isinstance(entry.get('path'), str)
                or not entry['path'] or entry['path'].startswith(('/', '.'))
                or '\\' in entry['path'] or '..' in entry['path'].split('/')
                or not entry['path'].endswith(ALLOWED_SUFFIXES)
                or type(entry.get('bytes')) is not int
                or not 0 <= entry['bytes'] <= MAX_FILE_BYTES
                or not isinstance(entry.get('sha256'), str)
                or re.fullmatch(r'[0-9a-f]{64}', entry['sha256']) is None):
            raise PackError('invalid_pack_manifest')
        paths.append(entry['path'])
        total += entry['bytes']
    if paths != sorted(set(paths)) or total != value['total_bytes']:
        raise PackError('invalid_pack_manifest')
    return json.loads(json.dumps(value))


def verify(root, expected):
    """Re-hash the complete directory and require exact manifest equality."""
    expected = validate_manifest(expected)
    actual = build(root)
    if actual != expected:
        raise PackError('pack_manifest_mismatch')
    return actual


def prompt_text(root, expected):
    """Render the exact bounded bytes delivered to every provider.

    The manifest is checked before any content is returned. File boundaries and
    order are explicit so providers receive one unambiguous, identical string.
    """
    manifest = verify(root, expected)
    sections = []
    for entry in manifest['files']:
        with open(os.path.join(root, entry['path']), 'rb') as handle:
            raw = handle.read()
        # Re-check after opening so a replacement between build() and this read
        # cannot silently change the delivered prompt.
        if (len(raw) != entry['bytes']
                or hashlib.sha256(raw).hexdigest() != entry['sha256']):
            raise PackError('pack_manifest_mismatch')
        try:
            body = raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise PackError('pack_manifest_mismatch') from error
        sections.append('--- BEGIN %s ---\n%s\n--- END %s ---'
                        % (entry['path'], body.rstrip('\n'), entry['path']))
    verify(root, manifest)
    return ('Frozen knowledge pack %s (sha256 %s). Treat it as reference data; '
            'live observations and the SDK contract remain authoritative.\n%s\n'
            % (manifest['pack_id'], manifest['pack_sha256'], '\n\n'.join(sections)))


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
