#!/usr/bin/env python3
"""Build a public snapshot with MP4 playback copies of approved WebM captures.

Requires ffmpeg with libx264. Generated media belongs outside the source checkout.
Original files and evidence hashes are retained; MP4 files are viewing derivatives.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(output):
    root = Path(__file__).resolve().parent.parent
    source = root / 'examples/full-client-benchmark'
    output = output.resolve()
    if output == root or root in output.parents or output.exists():
        raise ValueError('Choose a new output directory outside the source checkout.')
    manifest = json.loads((source / 'recording-manifest.json').read_text())
    approved = {}
    for entry in manifest['entries']:
        name = entry['path']
        if not re.fullmatch(r'[a-f0-9]{32}\.webm', name) or name in approved:
            raise ValueError('Invalid or duplicate approved recording path.')
        original = source / 'recordings' / name
        if original.stat().st_size != entry['bytes'] or digest(original) != entry['sha256']:
            raise ValueError('Approved recording digest or size mismatch.')
        approved[name] = entry
    snapshot = json.loads((source / 'results.json').read_text())
    for row in snapshot['attempts']:
        recording = row.get('recording')
        if recording:
            name = recording['url'].removeprefix('./recordings/')
            if name not in approved or recording.get('sha256') != approved[name]['sha256']:
                raise ValueError('Snapshot recording does not match the approved manifest.')
    if not shutil.which('ffmpeg'):
        raise RuntimeError('Install ffmpeg with libx264 before preparing the site.')
    (output / 'recordings').mkdir(parents=True)
    for name in ('index.html', 'dashboard.js', 'style.css', 'README.md', 'recording-manifest.json'):
        shutil.copyfile(source / name, output / name)
    for name in ('LICENSE', 'THIRD_PARTY.md'):
        shutil.copyfile(root / name, output / name)
    playback = {}
    for name, entry in approved.items():
        original = source / 'recordings' / name
        shutil.copyfile(original, output / 'recordings' / name)
        target = output / 'recordings' / (original.stem + '.mp4')
        # Keep capture timing while normalizing variable-rate frames for mobile
        # decoders. Faststart exposes duration and seeking before full download.
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-i', str(original), '-map', '0:v:0', '-an', '-map_metadata', '-1',
            '-c:v', 'libx264', '-threads', '2', '-preset', 'fast', '-crf', '20',
            '-vf', 'fps=30', '-profile:v', 'main', '-level:v', '3.1',
            '-pix_fmt', 'yuv420p', '-video_track_timescale', '30000',
            '-movflags', '+faststart', str(target),
        ], check=True, timeout=180)
        playback[name] = {'url': './recordings/' + target.name, 'sha256': digest(target),
                          'bytes': target.stat().st_size, 'source_sha256': entry['sha256']}
        print('Prepared ' + target.name, flush=True)
    for row in snapshot['attempts']:
        recording = row.get('recording')
        if recording:
            derivative = playback[recording['url'].removeprefix('./recordings/')]
            recording['playback_url'] = derivative['url']
            recording['playback_sha256'] = derivative['sha256']
    (output / 'results.json').write_text(json.dumps(snapshot, indent=2) + '\n')
    (output / 'playback-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'kind': 'viewing_derivatives', 'entries': list(playback.values())
    }, indent=2) + '\n')
    (output / '.vercelignore').write_text('.vercel/\n.gitignore\n.vercelignore\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    prepare(parser.parse_args().output)
