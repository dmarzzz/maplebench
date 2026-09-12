#!/usr/bin/env python3
"""One bounded Vercel publication of an explicit, verified public payload.

Uses local Vercel CLI authentication. A durable submission marker precedes the
only deploy call; later invocations reconcile metadata or remain uncertain.
No model, trial, database, game service or credential-management operations.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from threading import Event
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

from full_client_dashboard import Reader, ProjectionError, SHA, write_snapshot
from full_client_gallery import directory, copy_recording
from full_client_publication import (claim_publication, encoded, digest, publication_state,
    record_deployment, require, stable_bytes, stable_fingerprint, verify_package, write_new,
    XP_PROTOCOL, MAX_ADAPTIVE_VIDEO, MAX_LONG_VIDEO)

META_CONTENT='maplebenchContentSha256'
META_PAYLOAD='maplebenchPayloadSha256'
META_NONCE='maplebenchPublicationId'
MAX_PAYLOAD=512*1024**2
MAX_OUTPUT=2*1024**2
PUBLIC_NAME=re.compile(r'(?:(?:latest/)|(?:cohorts/[a-f0-9]{16}/))?(?:index\.html|dashboard\.js|style\.css|results\.json|recording-manifest\.json|vercel\.json|README\.md|recordings/[a-f0-9]{32}\.webm)\Z')
DEPLOYMENT=re.compile(r'dpl_[A-Za-z0-9]{8,80}\Z')


def origin(value):
    require(isinstance(value,str),'invalid_public_origin')
    parts=urlsplit(value)
    require(parts.scheme=='https' and parts.hostname and re.fullmatch(r'[a-z0-9-]+\.vercel\.app',parts.hostname)
            and not parts.username and not parts.password and parts.port is None
            and not parts.query and not parts.fragment and parts.path in ('','/'),'invalid_public_origin')
    return 'https://'+parts.hostname


def checked_payload(payload,inventory_path,inventory_sha,package_manifest):
    payload=directory(payload);inventory_path=Path(inventory_path)
    supplied=Reader().json(directory(inventory_path.parent),inventory_path.name,inventory_sha)
    raw=supplied.get('files');require(isinstance(raw,(dict,list)),'payload_inventory_required')
    if isinstance(raw,list):
        require(all(isinstance(row,dict) and set(row)=={'path','sha256','bytes'} for row in raw), 'invalid_payload_inventory')
        files={row['path']:{k:row[k] for k in ('sha256','bytes')} for row in raw}
        require(len(files)==len(raw),'duplicate_payload_path')
    else:files=raw
    require(1<=len(files)<=100,'payload_file_count_limit')
    content=package_manifest['content']
    video_limits=cohort_video_limits(supplied,files,package_manifest)
    total=0
    for name,expected in files.items():
        require(isinstance(name,str) and PUBLIC_NAME.fullmatch(name) and isinstance(expected,dict)
                and set(expected)=={'sha256','bytes'} and isinstance(expected['sha256'],str)
                and SHA.fullmatch(expected['sha256']) and type(expected['bytes']) is int and expected['bytes']>0,
                'invalid_public_payload_file')
        maximum=video_limits.get(name,MAX_ADAPTIVE_VIDEO) if name.endswith('.webm') else 4*1024**2
        total+=expected['bytes'];require(total<=MAX_PAYLOAD,'public_payload_size_limit')
        require(expected['bytes']<=maximum,'public_payload_file_limit')
        require(stable_fingerprint(payload/name,maximum)==expected,'public_payload_changed')
    actual=set()
    for count,path in enumerate(payload.rglob('*'),1):
        require(count<=150 and not path.is_symlink(),'unexpected_public_payload_file')
        if path.is_file():actual.add(path.relative_to(payload).as_posix())
    require(actual==set(files),'unexpected_public_payload_file')
    if 'cohort_manifests' in supplied:
        # Every byte has been checked against the pinned inventory before public
        # row semantics can authorize a supplemental long recording.
        from full_client_catalog import cohort_content
        for manifest in supplied['cohort_manifests']:
            cohort_content(manifest,payload/manifest['content']['target_path'].strip('/'))
    require(content.get('target_path')=='/' or (isinstance(content.get('target_path'),str)
            and re.fullmatch(r'/cohorts/[a-f0-9]{16}/',content['target_path'])),'invalid_cohort_target')
    prefix=content['target_path'].lstrip('/')
    require(all(files.get(prefix+name)==expected for name,expected in content['files'].items()),
            'cohort_payload_binding_mismatch')
    require('index.html' in files and 'results.json' in files,'public_root_required')
    return files,digest(encoded(files))


def cohort_video_limits(inventory,files,primary):
    """Only exact mounted package files inherit that package's video policy."""
    require(all(isinstance(name,str) for name in files),'invalid_public_payload_file')
    def limit(content):
        if 'horizon_seconds' in content:
            require(content.get('protocol')==XP_PROTOCOL and type(content['horizon_seconds']) is int
                    and content['horizon_seconds']==1800,'invalid_package_horizon')
            return MAX_LONG_VIDEO
        return MAX_ADAPTIVE_VIDEO
    content=primary['content'];prefix=content.get('target_path','').lstrip('/')
    limits={prefix+name:limit(content) for name in content['files'] if name.endswith('.webm')}
    if 'cohort_manifests' not in inventory:return limits
    manifests=inventory['cohort_manifests']
    require(isinstance(manifests,list) and 1<=len(manifests)<=7,'payload_cohort_manifests_required')
    mounts=set();primary_found=False
    for manifest in manifests:
        require(isinstance(manifest,dict) and set(manifest)=={'schema_version','content_sha256','content'}
                and type(manifest['schema_version']) is int and manifest['schema_version']==1
                and isinstance(manifest['content_sha256'],str) and SHA.fullmatch(manifest['content_sha256'])
                and isinstance(manifest['content'],dict)
                and digest(encoded(manifest['content']))==manifest['content_sha256'],'payload_cohort_manifest_mismatch')
        item=manifest['content'];target=item.get('target_path')
        require(isinstance(target,str) and re.fullmatch(r'/cohorts/[a-f0-9]{16}/',target)
                and target not in mounts and isinstance(item.get('files'),dict),'payload_cohort_mount_mismatch')
        mounts.add(target);prefix=target.lstrip('/')
        require({name[len(prefix):]:ref for name,ref in files.items() if name.startswith(prefix)}==item['files'],
                'payload_cohort_file_binding_mismatch')
        if target==content.get('target_path'):
            require(manifest==primary,'payload_primary_manifest_mismatch');primary_found=True
        maximum=limit(item)
        limits.update({prefix+name:maximum for name in item['files'] if name.endswith('.webm')})
    require(primary_found,'payload_primary_manifest_required')
    return limits


def project_link(path,expected):
    path=Path(path);value=Reader().json(directory(path.parent),path.name,expected)
    require(set(value)>={'projectId','orgId','projectName'} and isinstance(value['projectId'],str)
            and re.fullmatch(r'prj_[A-Za-z0-9]{8,100}',value['projectId'])
            and isinstance(value['orgId'],str) and re.fullmatch(r'(?:team_|user_)[A-Za-z0-9]{8,100}',value['orgId'])
            and isinstance(value['projectName'],str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}',value['projectName']),
            'invalid_existing_project_link')
    return {k:value[k] for k in ('projectId','orgId','projectName')}


def stage_payload(payload,files,package,link):
    stage=Path(tempfile.mkdtemp(prefix='.vercel-payload-',dir=package))
    try:
        for name,expected in files.items():
            target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
            if name.endswith('.webm'):
                copy_recording(payload,{'path':name,'sha256':expected['sha256']},target,{},maximum=MAX_PAYLOAD)
            else:write_new(target,stable_bytes(payload/name,4*1024**2),0o644)
            require(stable_fingerprint(target,MAX_PAYLOAD if name.endswith('.webm') else 4*1024**2)==expected,
                    'staged_payload_changed')
        (stage/'.vercel').mkdir(mode=0o700)
        write_new(stage/'.vercel/project.json',encoded(link))
        return stage
    except BaseException:
        shutil.rmtree(stage)
        raise


def checked_stage(stage,package,files,link):
    stage=directory(stage)
    require(stage.parent==package and stage.name.startswith('.vercel-payload-'),'invalid_publication_stage')
    for name,expected in files.items():
        require(stable_fingerprint(stage/name,MAX_PAYLOAD if name.endswith('.webm') else 4*1024**2)==expected,
                'staged_payload_changed')
    linked=Reader().json(stage,'.vercel/project.json')
    require(all(linked.get(k)==v for k,v in link.items()),'staged_project_link_changed')
    for count,path in enumerate(stage.rglob('*'),1):
        require(count<=170 and not path.is_symlink(),'unexpected_staged_file')
        if path.is_file():
            name=path.relative_to(stage).as_posix()
            require(name in files or name in ('.vercel/project.json','.vercel/README.txt'), 'unexpected_staged_file')
    return stage


def cli(executable,args,cwd,deadline):
    """Capture bounded CLI output privately; never echo provider diagnostics."""
    remaining=deadline-time.monotonic();require(remaining>0,'publication_deadline')
    environment=os.environ.copy()
    # The CLI otherwise prefers ambient project IDs over .vercel/project.json.
    for prefix in ('VERCEL_','NOW_'):
        for key in ('ORG_ID','PROJECT_ID'):environment.pop(prefix+key,None)
    with tempfile.TemporaryFile() as out,tempfile.TemporaryFile() as errors:
        process=subprocess.Popen([str(executable),*args],cwd=cwd,stdin=subprocess.DEVNULL,
            stdout=out,stderr=errors,start_new_session=True,env=environment)
        try:
            while process.poll() is None:
                require(time.monotonic()<deadline,'publication_deadline')
                require(os.fstat(out.fileno()).st_size<=MAX_OUTPUT and os.fstat(errors.fileno()).st_size<=MAX_OUTPUT,
                        'vercel_output_limit')
                time.sleep(min(.1,max(0,deadline-time.monotonic())))
            require(process.returncode==0,'vercel_reply_unavailable')
            require(os.fstat(out.fileno()).st_size<=MAX_OUTPUT and os.fstat(errors.fileno()).st_size<=MAX_OUTPUT,
                    'vercel_output_limit')
            out.seek(0);value=json.loads(out.read(MAX_OUTPUT+1))
            require(isinstance(value,dict),'vercel_reply_unavailable');return value
        finally:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=5)


class SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        target=urljoin(request.full_url,newurl)
        require(urlsplit(target).scheme=='https' and urlsplit(target).netloc==urlsplit(request.full_url).netloc,
                'public_redirect_refused')
        return super().redirect_request(request,fp,code,msg,headers,target)


def read_public(url,maximum,headers,deadline,*,cancelled=None):
    remaining=deadline-time.monotonic();require(remaining>0,'publication_deadline')
    request=Request(url,headers={'Accept-Encoding':'identity','Cache-Control':'no-cache',**headers})
    try:
        with build_opener(SameOriginRedirect()).open(request,timeout=min(15,remaining)) as response:
            result={'status':response.status,'headers':{k.lower():v for k,v in response.headers.items()}}
            hashed=hashlib.sha256();size=0
            while True:
                require(cancelled is None or not cancelled.is_set(),'public_verification_cancelled')
                require(time.monotonic()<deadline,'publication_deadline')
                block=response.read(min(1024**2,maximum+1-size))
                if not block:break
                size+=len(block);require(size<=maximum,'public_file_size_mismatch');hashed.update(block)
            return result|{'sha256':hashed.hexdigest(),'bytes':size}
    except (HTTPError,URLError,TimeoutError,OSError) as error:
        raise ProjectionError('public_file_unavailable') from error


def verify_public(base,stage,files,deadline,fetch=read_public):
    # A job owns one full-file stream followed by its range check. At most four
    # jobs exist at once; large videos are never collected in memory here.
    entries=[(name,expected) for name,expected in files.items()
             if Path(name).name not in ('vercel.json','README.md')]
    results=[None]*len(entries);cancelled=Event()
    def request(url,maximum,headers):
        require(not cancelled.is_set(),'public_verification_cancelled')
        require(time.monotonic()<deadline,'publication_deadline')
        if fetch is read_public:
            value=fetch(url,maximum,headers,deadline,cancelled=cancelled)
        else:
            value=fetch(url,maximum,headers,deadline)
        require(time.monotonic()<deadline,'publication_deadline')
        require(not cancelled.is_set(),'public_verification_cancelled')
        return value
    def verify(entry):
        name,expected=entry
        result=request(base+'/'+name,expected['bytes'],{})
        require(result['status']==200 and result['bytes']==expected['bytes'] and result['sha256']==expected['sha256'],
                'public_content_mismatch')
        video_range=None
        if name.endswith('.webm'):
            count=min(16,expected['bytes']);response=request(base+'/'+name,count,{'Range':f'bytes=0-{count-1}'})
            with (stage/name).open('rb') as stream:first=stream.read(count)
            require(response['status']==206 and response['bytes']==count
                    and response['headers'].get('content-range')==f'bytes 0-{count-1}/{expected["bytes"]}'
                    and response['sha256']==digest(first),'public_video_range_mismatch')
            video_range={'path':name,'status':206,'bytes':count,'total_bytes':expected['bytes']}
        return {'path':name,**expected},video_range
    pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='public-verify')
    pending={};next_index=0
    try:
        while next_index<len(entries) and len(pending)<4:
            pending[pool.submit(verify,entries[next_index])]=next_index;next_index+=1
        while pending:
            remaining=deadline-time.monotonic();require(remaining>0,'publication_deadline')
            done,_=wait(pending,timeout=remaining,return_when=FIRST_COMPLETED)
            require(done,'publication_deadline')
            # Inspect every completed job before scheduling more work, so a
            # concurrently completed failure cannot enqueue another file.
            for future in done:
                results[pending.pop(future)]=future.result()
            while next_index<len(entries) and len(pending)<4:
                pending[pool.submit(verify,entries[next_index])]=next_index;next_index+=1
    finally:
        cancelled.set()
        for future in pending:future.cancel()
        pool.shutdown(wait=True,cancel_futures=True)
    return {'files':[row[0] for row in results],
            'video_ranges':[row[1] for row in results if row[1] is not None],'anonymous_access':True}


def find_deployment(executable,stage,link,marker,deadline,run_cli):
    args=['list','--format=json','--scope',link['orgId']]
    metadata={META_CONTENT:marker['content_sha256'],META_PAYLOAD:marker['payload_sha256'],META_NONCE:marker['nonce']}
    for key,value in metadata.items():args+=['--meta',key+'='+value]
    value=run_cli(executable,args,stage,deadline);rows=value.get('deployments');pagination=value.get('pagination') or {}
    require(isinstance(rows,list) and len(rows)<=20 and isinstance(pagination,dict) and not pagination.get('next'),
            'deployment_reconciliation_incomplete')
    matches=[row for row in rows if isinstance(row,dict) and row.get('name')==link['projectName']
             and row.get('target')=='production' and isinstance(row.get('meta'),dict)
             and all(row['meta'].get(k)==v for k,v in metadata.items())]
    require(len(matches)==1,'deployment_outcome_uncertain' if not matches else 'deployment_identity_ambiguous')
    row=matches[0];ident=row.get('id')
    if ident is None:
        # Current CLI list output omits the ID. Resolve only the unique URL
        # whose three immutable publication metadata values already matched.
        url=row.get('url')
        require(isinstance(url,str) and re.fullmatch(r'[a-z0-9-]+\.vercel\.app',url),
                'invalid_deployment_identity')
        inspected=run_cli(executable,['inspect',url,'--format=json','--scope',link['orgId']],stage,deadline)
        require(inspected.get('url')==url and inspected.get('name')==link['projectName']
                and inspected.get('target')=='production','deployment_url_identity_mismatch')
        ident=inspected.get('id')
    require(isinstance(ident,str) and DEPLOYMENT.fullmatch(ident),'invalid_deployment_identity')
    return ident


def status(package,state,**fields):
    value={'schema_version':1,'status':state,'at_ms':round(time.time()*1000),'model_api_requests':0,**fields}
    write_snapshot(package/'vercel-publication-status.json',value)
    return value


def publish(package,content_sha256,payload,inventory_path,inventory_sha,link_path,link_sha,public_origin,
            *,executable,timeout_seconds=300,run_cli=cli,fetch=read_public):
    require(type(timeout_seconds) is int and 1<=timeout_seconds<=600,'invalid_publication_timeout')
    started=time.monotonic();deadline=started+timeout_seconds
    package=directory(package);manifest=verify_package(package,content_sha256);base=origin(public_origin)
    validated_at=round(time.time()*1000)
    payload=directory(payload);files,payload_sha=checked_payload(payload,inventory_path,inventory_sha,manifest)
    link=project_link(link_path,link_sha);executable=Path(executable)
    require(executable.is_absolute() and executable.is_file() and os.access(executable,os.X_OK),'vercel_executable_required')
    binding={'content_sha256':content_sha256,'payload_sha256':payload_sha,'project':link,'public_origin':base}
    lock=os.open(package/'vercel-publication.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'publishing','deployment_allowed':False,'model_api_requests':0}
        require(stat.S_ISREG(os.fstat(lock).st_mode) and os.fstat(lock).st_nlink==1,'invalid_publication_lock')
        current=publication_state(package,content_sha256)
        marker=Reader().optional(package,'vercel-submission.json')
        if marker:
            require(all(marker.get(k)==v for k,v in binding.items()),'publication_binding_changed')
            require(marker.get('schema_version')==1 and marker.get('submission_started') is True
                    and isinstance(marker.get('nonce'),str) and re.fullmatch('[a-f0-9]{32}',marker['nonce'])
                    and type(marker.get('validated_at_ms')) is int and marker['validated_at_ms']>0,
                    'invalid_submission_receipt')
            if current=='published':
                receipt=Reader().json(package,'publication-complete.json')
                proof=Reader().json(package,'vercel-public-verification.json')
                require(receipt.get('url')==base+manifest['content']['target_path']
                        and all(proof.get(k)==v for k,v in binding.items())
                        and proof.get('deployment_id')==receipt.get('deployment_id'),'publication_receipt_mismatch')
                return {'status':'published','deployment_allowed':False,'model_api_requests':0,'receipt':receipt,
                        'latency_ms':proof['latency_ms'],'within_target':proof['within_target']}
            stage=checked_stage(Path(marker['stage']),package,files,link)
        elif current!='unclaimed':return status(package,'uncertain',reason='existing_intent_requires_reconciliation')
        else:
            require(time.monotonic()<deadline,'publication_deadline')
            stage=stage_payload(payload,files,package,link)
            try:
                checked_stage(stage,package,files,link)
                require(time.monotonic()<deadline,'publication_deadline')
                claimed=claim_publication(package,content_sha256)
            except BaseException:
                # This directory has never been submitted. Preserve claimed stages.
                if publication_state(package,content_sha256)=='unclaimed':shutil.rmtree(stage)
                raise
            if not claimed['deployment_allowed']:
                shutil.rmtree(stage)
                return status(package,'uncertain',reason='publication_already_claimed')
            marker={'schema_version':1,**binding,'nonce':uuid.uuid4().hex,'stage':str(stage),
                    'validated_at_ms':validated_at,'submission_started':True}
            try:write_new(package/'vercel-submission.json',encoded(marker))
            except (ValueError,OSError):
                return status(package,'uncertain',reason='submission_receipt_unavailable')
            status(package,'publishing',content_sha256=content_sha256)
            args=['deploy','--prod','--yes','--format=json','--scope',link['orgId']]
            for key,value in ((META_CONTENT,content_sha256),(META_PAYLOAD,payload_sha),(META_NONCE,marker['nonce'])):
                args+=['--meta',key+'='+value]
            try:run_cli(executable,args,stage,deadline)
            except (ValueError,OSError,TypeError,KeyError,RecursionError,subprocess.SubprocessError):
                # The server may have accepted a request even when no reply was saved.
                status(package,'reconciling',reason='deployment_reply_unavailable')
        try:
            require(time.monotonic()<deadline,'publication_deadline')
            ident=find_deployment(executable,stage,link,marker,deadline,run_cli)
            remaining=max(1,min(120,int(deadline-time.monotonic())))
            inspected=run_cli(executable,['inspect',ident,'--format=json','--wait','--timeout',str(remaining)+'s',
                                         '--scope',link['orgId']],stage,deadline)
            require(inspected.get('id')==ident and inspected.get('name')==link['projectName']
                    and inspected.get('target')=='production' and inspected.get('readyState')=='READY'
                    and urlsplit(base).hostname in inspected.get('aliases',[]),'deployment_not_public_ready')
            status(package,'verifying',content_sha256=content_sha256,deployment_id=ident)
            checked=verify_public(base,stage,files,deadline,fetch)
            verify_package(package,content_sha256)
            checked_stage(stage,package,files,link)
            completed_at=round(time.time()*1000);latency=completed_at-marker['validated_at_ms']
            proof={'schema_version':1,**binding,'deployment_id':ident,'public_verification':checked,
                   'validated_at_ms':marker['validated_at_ms'],'published_at_ms':completed_at,'latency_ms':latency,
                   'target_latency_ms':60000,'within_target':0<=latency<=60000,'model_api_requests':0}
            proof_path=package/'vercel-public-verification.json'
            if proof_path.exists():
                previous=Reader().json(package,proof_path.name)
                require(all(previous.get(k)==v for k,v in binding.items()) and previous.get('deployment_id')==ident
                        and previous.get('public_verification')==checked,'public_verification_receipt_conflict')
                proof=previous;latency=proof['latency_ms']
            else:write_new(proof_path,encoded(proof))
            record_deployment(package,content_sha256,ident,base+manifest['content']['target_path'],content_sha256)
            return status(package,'published',content_sha256=content_sha256,deployment_id=ident,
                          url=base+manifest['content']['target_path'],latency_ms=latency,within_target=proof['within_target'])
        except (ValueError,OSError,TypeError,KeyError,RecursionError,subprocess.SubprocessError) as error:
            code=str(error) if isinstance(error,ProjectionError) and re.fullmatch('[a-z_]{1,100}',str(error)) else 'verification_unavailable'
            return status(package,'uncertain',reason=code,content_sha256=content_sha256)
    finally:os.close(lock)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','payload','payload-inventory','project-link','vercel-executable'):
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ('content-sha256','payload-inventory-sha256','project-link-sha256','public-origin'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--timeout-seconds',type=int,default=300)
    args=parser.parse_args(argv)
    try:
        result=publish(args.package,args.content_sha256,args.payload,args.payload_inventory,args.payload_inventory_sha256,
            args.project_link,args.project_link_sha256,args.public_origin,executable=args.vercel_executable,
            timeout_seconds=args.timeout_seconds)
        print(json.dumps(result,sort_keys=True));return 0 if result['status']=='published' else 2
    except (ValueError,OSError,TypeError,KeyError,RecursionError,subprocess.SubprocessError):
        # A write failure after the claim must not be described as a fresh retry.
        try:claimed=publication_state(directory(args.package),args.content_sha256)!='unclaimed'
        except (ValueError,OSError,TypeError,KeyError,RecursionError):claimed=True
        value={'status':'uncertain' if claimed else 'refused',
               'reason':'publication_requires_reconciliation' if claimed else 'publication_inputs_unavailable',
               'model_api_requests':0}
        print(json.dumps(value,sort_keys=True));return 2 if claimed else 1


if __name__=='__main__':raise SystemExit(main())
