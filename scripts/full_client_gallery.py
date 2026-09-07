#!/usr/bin/env python3
"""Publish explicitly selected completed-run recordings to an existing gallery.

This opt-in exporter copies only hashed gameplay video and public-safe results.
It never starts trials, changes private evidence, or grants review/ranking status.
The finite watcher exposes each success without waiting for the rest of a group.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time

from full_client_dashboard import (Reader, ProjectionError, RUN, build_snapshot,
    read_admin_status, recording_prefix, verified_score, write_snapshot)
from full_client_score import open_verified_artifact

MAX_VIDEO=1024**3


def directory(path):
    path=Path(path)
    if not path.is_absolute() or path.resolve()!=path or not path.is_dir():
        raise ProjectionError('invalid_gallery_directory')
    return path


def identity(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
        raise ProjectionError('invalid_gallery_recording')
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def copy_recording(source,reference,target,cache):
    """Publish only complete verified bytes; never overwrite a conflicting clip."""
    expected=reference['sha256']
    cached=cache.get(str(target))
    if target.exists() or target.is_symlink():
        current=identity(target)
        if cached==(expected,current):
            return
        with open_verified_artifact(target.parent,{'path':target.name,'sha256':expected},
                                    'gallery_video',maximum=MAX_VIDEO):
            pass
        cache[str(target)]=(expected,identity(target))
        return
    fd,name=tempfile.mkstemp(prefix='.recording-',dir=target.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,'wb') as output:
            with open_verified_artifact(source,reference,'video',maximum=MAX_VIDEO) as stream:
                digest=hashlib.sha256()
                for block in iter(lambda:stream.read(1024*1024),b''):
                    digest.update(block); output.write(block)
                if digest.hexdigest()!=expected:
                    raise ProjectionError('recording_changed_during_copy')
            output.flush(); os.fchmod(output.fileno(),0o644); os.fsync(output.fileno())
        os.link(temporary,target)  # Exclusive publication; no replacement.
        temporary.unlink()
        descriptor=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
        cache[str(target)]=(expected,identity(target))
    finally:
        temporary.unlink(missing_ok=True)


def export_once(attempt_root,relay_root,output_directory,run_ids,*,recording_map=None,
                prefix='/recordings/',live_status=None,cache=None):
    attempt_root=directory(attempt_root); output_directory=directory(output_directory)
    prefix=recording_prefix(prefix)
    if (not run_ids or len(run_ids)>32 or len(set(run_ids))!=len(run_ids)
            or any(not isinstance(value,str) or not RUN.fullmatch(value) for value in run_ids)):
        raise ProjectionError('invalid_selected_runs')
    if (output_directory==attempt_root or output_directory.is_relative_to(attempt_root)
            or attempt_root.is_relative_to(output_directory)):
        raise ProjectionError('private_evidence_must_be_outside_gallery')
    if relay_root is not None:
        relay_root=directory(relay_root)
        if (output_directory==relay_root or output_directory.is_relative_to(relay_root)
                or relay_root.is_relative_to(output_directory)):
            raise ProjectionError('private_evidence_must_be_outside_gallery')
    recordings=output_directory/'recordings'
    recordings.mkdir(exist_ok=True,mode=0o755); directory(recordings)
    approved=dict(recording_map or {}); published=[]; unavailable=[]
    cache={} if cache is None else cache
    for run_id in run_ids:
        try:
            reader=Reader(); folder=attempt_root/run_id
            if not folder.exists(): continue
            directory(folder)
            journal=reader.json(folder,'journal.json')
            if journal.get('attempt_id')!=run_id:
                raise ProjectionError('attempt_identity_mismatch')
            if journal.get('status')!='completed': continue
            _,result,_,refs=verified_score(reader,folder,journal)
            recording=reader.artifact(folder,refs,'recording')
            video=refs['video']
            if (recording.get('status')!='completed' or recording.get('interrupted') is not False
                    or recording.get('post_render_capture') is not True
                    or recording.get('sha256')!=video.get('sha256')
                    or recording.get('overlay')!={'controller_id':run_id,'mode':'api',
                                                'model':result['controller']['model']}
                    or Path(video['path']).suffix!='.webm'):
                raise ProjectionError('recording_receipt_inconsistent')
            target=recordings/(run_id+'.webm')
            copy_recording(folder,video,target,cache)
            approved[run_id]={'url':prefix+target.name,'sha256':video['sha256']}
            published.append(run_id)
        except (ValueError,OSError,TypeError,KeyError,RecursionError):
            # A bad clip must not conceal the score or delay unrelated successes.
            approved.pop(run_id,None); unavailable.append(run_id)
    snapshot=build_snapshot(attempt_root,relay_root,recording_map=approved,
                            recording_path_prefix=prefix,live_status=live_status)
    snapshot['recording_uploads']={'available':published,'unavailable':unavailable}
    write_snapshot(output_directory/'results.json',snapshot,public=True)
    return snapshot


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt-root',type=Path,required=True)
    parser.add_argument('--relay-root',type=Path)
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--run-id',action='append',required=True)
    parser.add_argument('--recording-map',type=Path)
    parser.add_argument('--recording-prefix',default='/recordings/')
    parser.add_argument('--admin-socket',type=Path)
    parser.add_argument('--watch-seconds',type=int,default=0)
    args=parser.parse_args(argv)
    try:
        if not 0<=args.watch_seconds<=3600: raise ProjectionError('invalid_watch_window')
        approved=None
        if args.recording_map:
            directory(args.recording_map.parent)
            approved=Reader().json(args.recording_map.parent,args.recording_map.name)
        deadline=time.monotonic()+args.watch_seconds; cache={}; previous=None
        while True:
            live=None
            if args.admin_socket:
                try: live=read_admin_status(args.admin_socket,timeout=1)
                except (ValueError,OSError,TypeError,RecursionError): pass
            snapshot=export_once(args.attempt_root,args.relay_root,args.output_directory,args.run_id,
                recording_map=approved,prefix=args.recording_prefix,live_status=live,cache=cache)
            outcome=snapshot['recording_uploads']
            if outcome!=previous:
                print(json.dumps(outcome),flush=True); previous=outcome
            remaining=deadline-time.monotonic()
            if not args.watch_seconds or remaining<=0: break
            time.sleep(min(2,remaining))
            if time.monotonic()>=deadline: break
        return 0
    except (ValueError,OSError,TypeError,KeyError,RecursionError):
        print('{"error":"gallery_export_unavailable"}')
        return 1


if __name__=='__main__': raise SystemExit(main())
