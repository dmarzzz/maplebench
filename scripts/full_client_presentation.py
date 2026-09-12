"""Refresh a verified public cohort's UI without changing results or recordings.

Produces a new immutable package; does not run a model, alter old evidence,
claim a deployment, or publish. The parent content hash records its provenance.
"""
import os
from pathlib import Path
import shutil
import tempfile

from full_client_gallery import copy_recording, directory
from full_client_publication import (ASSETS, ADAPTIVE_PROTOCOL, XP_PROTOCOL, MAX_ADAPTIVE_VIDEO,
    MAX_VIDEO, digest, encoded, file_inventory, require, stable_bytes,
    verify_package, write_new)
from full_client_trial import publish_attempt, sync_directory


def refresh(package, expected, output_root, *, ui_root=None):
    package=directory(Path(package));output_root=directory(Path(output_root))
    require(not output_root.is_relative_to(package) and not package.is_relative_to(output_root),
            'presentation_paths_overlap')
    manifest=verify_package(package,expected);original=manifest['content']
    ui=directory(Path(ui_root) if ui_root else Path(__file__).resolve().parents[1]/'ui/full-client-dashboard')
    maximum=MAX_ADAPTIVE_VIDEO if original.get('protocol') in (ADAPTIVE_PROTOCOL,XP_PROTOCOL) else MAX_VIDEO
    staging=Path(tempfile.mkdtemp(prefix='.presentation-',dir=output_root))
    try:
        site=staging/'site';site.mkdir(mode=0o755);(site/'recordings').mkdir(mode=0o755)
        for name,ref in original['files'].items():
            if name in ASSETS:
                write_new(site/name,stable_bytes(ui/name,1024**2),0o644)
            elif name.endswith('.webm'):
                copy_recording(package/'site',{'path':name,'sha256':ref['sha256']},site/name,{},maximum=maximum)
            else:
                write_new(site/name,stable_bytes(package/'site'/name,4*1024**2),0o644)
        files=file_inventory(site,maximum_video=maximum)
        require(all(files[name]==ref for name,ref in original['files'].items() if name not in ASSETS),
                'presentation_changed_evidence')
        verify_package(package,expected)
        content={**original,'files':files,'presentation_parent_sha256':expected}
        identity=digest(encoded(content));destination=output_root/identity
        write_new(staging/'package-manifest.json',encoded({'schema_version':1,'content_sha256':identity,'content':content}))
        sync_directory(site/'recordings');sync_directory(site);sync_directory(staging)
        if not os.path.lexists(destination):publish_attempt(staging,destination)
        verify_package(destination,identity)
        return {'package':str(destination),'content_sha256':identity,
                'parent_content_sha256':expected,'results_and_recordings_unchanged':True,
                'api_requests':0,'deployment_performed':False}
    finally:
        if staging.exists():shutil.rmtree(staging)
