#!/usr/bin/env python3
"""Prepare immutable public cohort snapshots; never run models or deploy a site.

The exact private plan selects a bounded four-model repeated cohort. Public data is rebuilt with the
existing receipt projector, never copied from raw journals. A separate explicit
claim precedes a root-owned deployment; uncertain claims cannot be replayed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
from urllib.parse import urlsplit

from full_client_dashboard import (Reader, ProjectionError, RUN, SHA, model,
    project_attempt, verified_score)
from full_client_gallery import copy_recording, directory
from full_client_score import same_json
from full_client_trial import publish_attempt, sync_directory, validate_spec
from full_client_research import summarize, operational_reliability, CLASSES, TASKS

CORE_ASSETS = ('index.html', 'dashboard.js', 'style.css')
THEME_ASSETS = ('henesys-world.png', 'maple-leaf.png', 'maple-companions.png',
                'skill-book.png', 'manrope.ttf', 'OFL-Manrope.txt', 'ARTWORK.md',
                # Section emblems and the font stylesheet the polished dashboard needs.
                'blue-snail.png', 'little-stump.png', 'meso-pouch.png', 'potions.png',
                'return-scroll.png', 'ribbon-pig.png', 'fonts.css',
                'SECTION-ART.md', 'WORLD-BACKGROUND.md')
ASSETS = CORE_ASSETS + THEME_ASSETS
MAX_VIDEO = 32 * 1024**2
MAX_ADAPTIVE_VIDEO = 96 * 1024**2
ADAPTIVE_PROTOCOL = 'full-client-adaptive-pilot-v1'
VERIFIED = 'runner_verified_receipts_rechecked'


def require(value, code):
    if not value: raise ProjectionError(code)


def encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def digest(value): return hashlib.sha256(value).hexdigest()


def stable_bytes(path, maximum):
    require(path.resolve()==path and not path.is_symlink(),'publication_symlink')
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as stream:
        before=os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink==1
                and 0<before.st_size<=maximum,'publication_file_limit')
        raw=stream.read(maximum+1);after=os.fstat(stream.fileno());current=path.lstat()
    fields=('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')
    require(len(raw)==before.st_size and all(getattr(before,k)==getattr(after,k)==getattr(current,k)
                                          for k in fields),'publication_file_changed')
    return raw


def stable_fingerprint(path,maximum):
    """Hash large videos in bounded chunks and reject replacement or growth."""
    require(path.resolve()==path and not path.is_symlink(),'publication_symlink')
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as stream:
        before=os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink==1
                and 0<before.st_size<=maximum,'publication_file_limit')
        hashed=hashlib.sha256();size=0
        for block in iter(lambda:stream.read(min(1024**2,maximum+1-size)),b''):
            size+=len(block);require(size<=maximum,'publication_file_limit');hashed.update(block)
        after=os.fstat(stream.fileno());current=path.lstat()
    fields=('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')
    require(size==before.st_size and all(getattr(before,k)==getattr(after,k)==getattr(current,k)
                                       for k in fields),'publication_file_changed')
    return {'sha256':hashed.hexdigest(),'bytes':size}


def write_new(path, raw, mode=0o600):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw);stream.flush();os.fchmod(stream.fileno(),mode);os.fsync(stream.fileno())
    sync_directory(path.parent)


def selected_plan(path, expected):
    require(isinstance(expected,str) and SHA.fullmatch(expected),'plan_hash_required')
    plan=Reader().json(directory(path.parent),path.name,expected)
    repetitions=plan.get('repetitions')
    require(plan.get('schema_version')==1 and type(repetitions) is int and 1<=repetitions<=20
            and isinstance(plan.get('models'),list) and len(plan['models'])==4
            and len(set(plan['models']))==4 and all(model(x)==x for x in plan['models'])
            and isinstance(plan.get('fixtures'),list) and len(plan['fixtures'])==1
            and isinstance(plan.get('entries'),list) and len(plan['entries'])==4*repetitions,'four_model_plan_required')
    seen=set();fixture=plan['fixtures'][0]
    require(isinstance(fixture,dict) and isinstance(fixture.get('adapter_fingerprint'),str)
            and SHA.fullmatch(fixture['adapter_fingerprint']),'fixture_binding_required')
    for key in ('runtime_manifest','scenario','baseline'):
        value=fixture.get(key)
        require(isinstance(value,dict) and isinstance(value.get('sha256'),str)
                and SHA.fullmatch(value['sha256']),'fixture_binding_required')
    for ordinal,entry in enumerate(plan['entries']):
        repetition,position=divmod(ordinal,4)
        expected_model=plan['models'][(position+repetition)%4]
        require(isinstance(entry,dict) and entry.get('ordinal')==ordinal
                and isinstance(entry.get('attempt_id'),str) and RUN.fullmatch(entry['attempt_id'])
                and entry['attempt_id'] not in seen and entry.get('model')==expected_model
                and type(entry.get('repetition')) is int and entry['repetition']==repetition+1
                and entry.get('fixture_id')==fixture.get('id'), 'cohort_entry_invalid')
        validate_spec(entry.get('spec'))
        require(entry['spec']['model']==entry['model'] and digest(encoded(entry['spec']))==entry.get('spec_sha256')
                and entry['spec']['scenario_fingerprint']==fixture['scenario']['sha256']
                and entry['spec']['baseline_sha256']==fixture['baseline']['sha256']
                and same_json(entry['spec']['budgets'],fixture.get('budgets')),'cohort_spec_mismatch')
        seen.add(entry['attempt_id'])
    return plan


def missing_row(entry):
    row=project_attempt(Reader(),entry['attempt_id'],None,None,{},None,0,'/recordings/')
    row.update(kind='trial',status='not_started',mode='api',requested_model=entry['model'],
               api_outcome='not_started',score_verification='pending')
    return row


def project_member(entry, fixture, attempt_root, recordings):
    ident=entry['attempt_id'];folder=attempt_root/ident
    if not os.path.lexists(folder): return missing_row(entry)
    try:
        directory(folder);reader=Reader();journal=reader.json(folder,'journal.json')
        require(journal.get('attempt_id')==ident and same_json(journal.get('request'),entry['spec'])
                and journal.get('adapter_fingerprint')==fixture['adapter_fingerprint'],'cohort_request_mismatch')
        stamps=[event.get('at_ms') for event in journal.get('events',[]) if isinstance(event,dict)]
        stamp=max([value for value in stamps if type(value) is int and 0<=value<2**53],default=0)
        def projection(reader, approved=None):
            # Review receipts can be newer than the last trial event. Use the
            # real clock to validate them, but freeze elapsed display time at
            # the last receipt so unchanged inputs keep the same content hash.
            value=project_attempt(reader,ident,folder,None,{},approved,round(time.time()*1000),'/recordings/')
            if 'attempt_elapsed_ms' in value['timing']:
                value['timing']['attempt_elapsed_ms']=max(0,stamp-(value['created_at_ms'] or 0))
            return value
        row=projection(reader)
        row['recording_publication']='not_ready'
        if row['score_verification']!=VERIFIED: return row
        _,result,_,refs=verified_score(reader,folder,journal)
        require(refs['runtime_manifest']['sha256']==fixture['runtime_manifest']['sha256'],'cohort_runtime_mismatch')
        try:
            recording=reader.artifact(folder,refs,'recording');video=refs['video']
            require(recording.get('status')=='completed' and recording.get('interrupted') is False
                    and recording.get('post_render_capture') is True and recording.get('sha256')==video.get('sha256')
                    and recording.get('overlay')=={'controller_id':ident,'mode':'api','model':entry['model']}
                    and Path(video['path']).suffix=='.webm','recording_receipt_inconsistent')
            # The verified artifact reader used by copy_recording rejects escapes,
            # symlinks and changed bytes. This smaller cap bounds public packages.
            require(0<(folder/video['path']).stat().st_size<=MAX_VIDEO,'public_recording_size_limit')
            copy_recording(folder,video,recordings/(ident+'.webm'),{},maximum=MAX_VIDEO)
            approved={ident:{'url':'/recordings/'+ident+'.webm','sha256':video['sha256']}}
            row=projection(Reader(),approved)
            require(row['score_verification']==VERIFIED and row['attribution']=='exact'
                    and row.get('recording') is not None,'publication_evidence_changed')
            row['recording']['url']='./recordings/'+ident+'.webm'
            row['recording_publication']='verified_bytes'
        except (ValueError,OSError,TypeError,KeyError,RecursionError):
            (recordings/(ident+'.webm')).unlink(missing_ok=True)
            row['recording']=None;row['recording_publication']='unavailable'
        require(same_json(Reader().json(folder,'journal.json'),journal),'publication_evidence_changed')
        return row
    except (ValueError,OSError,TypeError,KeyError,RecursionError):
        (recordings/(ident+'.webm')).unlink(missing_ok=True)
        row=missing_row(entry)
        row.update(status='unavailable',api_outcome=None,failure_code='cohort_evidence_unavailable',
                   score_verification='unverified',recording_publication='unavailable')
        return row


def file_inventory(site,*,maximum_video=MAX_VIDEO):
    require(maximum_video in (MAX_VIDEO,MAX_ADAPTIVE_VIDEO),'invalid_public_video_limit')
    required=set(CORE_ASSETS)|{'results.json','recording-manifest.json','vercel.json','recordings'}
    found=set()
    for count,p in enumerate(site.iterdir(),1):
        require(count<=len(required)+len(THEME_ASSETS)+1,'unexpected_public_file');found.add(p.name)
    # Historical packages retain their exact three-file UI. A themed package
    # must carry the entire fixed artwork/font closure, including provenance.
    require(found-{'native-qualification.json'} in (required,required|set(THEME_ASSETS)),'unexpected_public_file')
    names=found-{'recordings'}
    for count,p in enumerate(directory(site/'recordings').iterdir(),1):
        require(count<=(80 if maximum_video==MAX_ADAPTIVE_VIDEO else 4),'public_recording_count_limit');names.add('recordings/'+p.name)
    result={}
    for name in sorted(names):
        require(name in ASSETS or name in ('results.json','recording-manifest.json','vercel.json','native-qualification.json')
                or re.fullmatch(r'recordings/[a-f0-9]{32}\.webm',name),'unexpected_public_file')
        result[name]=stable_fingerprint(site/name,maximum_video if name.endswith('.webm') else 4*1024**2)
    return result


def verify_package(package, expected):
    package=directory(package)
    manifest=Reader().json(package,'package-manifest.json')
    require(manifest.get('schema_version')==1 and manifest.get('content_sha256')==expected
            and isinstance(manifest.get('content'),dict) and digest(encoded(manifest['content']))==expected,
            'package_manifest_mismatch')
    content=manifest['content'];site=directory(package/'site')
    require(content.get('protocol') in (None,'legacy-full-client-v1',ADAPTIVE_PROTOCOL),'invalid_package_protocol')
    maximum=MAX_ADAPTIVE_VIDEO if content.get('protocol')==ADAPTIVE_PROTOCOL else MAX_VIDEO
    require(content.get('files')==file_inventory(site,maximum_video=maximum),'package_content_changed')
    verify_qualification_binding(site,content)
    return manifest


def verify_qualification_binding(site,content):
    """Bind a reviewed native projection to the exact scored fixture.

    Receipt re-execution happens during preparation. Catalogs accept only this
    immutable projection, never raw native ledgers or private host paths.
    """
    snapshot=Reader().json(site,'results.json')
    binding=content.get('native_qualification');value=snapshot.get('native_qualification')
    require(('native-qualification.json' in content['files'])==(binding is not None)==(value is not None),
        'native_qualification_binding_missing')
    if binding is None:return None
    from full_client_hero_qualification_public import validate_public_qualification
    from full_client_hero_native_runtime import qualification_scenario
    from full_client_native import contract, HERO_TOOLKIT_PROTOCOL
    require(isinstance(binding,dict) and set(binding)=={'path','sha256','baseline_sha256',
        'runtime_manifest_sha256','scenario_sha256','budgets'}
        and binding['path']=='native-qualification.json'
        and all(SHA.fullmatch(str(binding[key])) for key in
            ('sha256','baseline_sha256','runtime_manifest_sha256','scenario_sha256')),
        'native_qualification_binding_invalid')
    require(isinstance(value,dict)
        and binding['sha256']==content['files']['native-qualification.json']['sha256']
        and same_json(value,Reader().json(site,'native-qualification.json',binding['sha256'])),
        'native_qualification_file_mismatch')
    pins={key:binding[key] for key in ('baseline_sha256','runtime_manifest_sha256')}
    pins['qualification_scenario_sha256']=digest(encoded(qualification_scenario(pins['baseline_sha256'])))
    pins.update({key:value.get(key) for key in ('server_jar_sha256','client_js_sha256','client_wasm_sha256')})
    validate_public_qualification(value,native_contract=contract('hero',pins['baseline_sha256'],
        protocol=HERO_TOOLKIT_PROTOCOL),expected_pins=pins)
    fingerprint=digest(encoded({'scenario':binding['scenario_sha256'],
        'baseline':binding['baseline_sha256'],'runtime_manifest':binding['runtime_manifest_sha256'],
        'budgets':binding['budgets']}))
    require(content.get('protocol')==ADAPTIVE_PROTOCOL and snapshot.get('attempts')
        and all(row.get('research',{}).get('class_id')=='hero'
            and row['research'].get('fixture_fingerprint')==fingerprint for row in snapshot['attempts']),
        'native_qualification_fixture_mismatch')
    return value


def publication_state(package, expected):
    complete=package/'publication-complete.json';intent=package/'publication-intent.json'
    require(not intent.is_symlink() and not complete.is_symlink(),'publication_symlink')
    if complete.exists():
        value=Reader().json(package,complete.name)
        started=Reader().json(package,intent.name)
        require(value.get('content_sha256')==started.get('content_sha256')==expected
                and value.get('status')=='published' and started.get('status')=='pending_external_deployment',
                'publication_receipt_mismatch')
        return 'published'
    if intent.exists():
        value=Reader().json(package,intent.name)
        require(value.get('content_sha256')==expected and value.get('status')=='pending_external_deployment',
                'publication_receipt_mismatch')
        return 'pending_reconciliation'
    return 'unclaimed'


def prepare_package(plan_path, plan_sha256, attempt_root, output_root, *, replace_archive=False,
                    research_profile=None, adaptive_scenario=None, native_qualification=None):
    plan_path=Path(plan_path);attempt_root=directory(attempt_root);output_root=directory(output_root)
    for private in (attempt_root,directory(plan_path.parent)):
        require(not (output_root==private or output_root.is_relative_to(private) or private.is_relative_to(output_root)),
                'private_inputs_must_be_outside_publication')
    plan=selected_plan(plan_path,plan_sha256)
    qualification=None;qualification_binding=None
    if adaptive_scenario is not None:
        from full_client_adaptive_publication import checked_profile, project_member as adaptive_member, VERIFIED as verified
        profile,scenario=checked_profile(plan,adaptive_scenario,research_profile)
        project=lambda entry,fixture,root,videos:adaptive_member(entry,fixture,root,videos,scenario)
        maximum_video=MAX_ADAPTIVE_VIDEO
        if scenario['adaptive_protocol'].get('skill_toolkit') is not None:
            require(native_qualification is not None,'native_skill_qualification_required')
    else:
        profile=research_profile or {'protocol_id':'legacy-full-client-v1','class_id':'undeclared','task_id':'undeclared'}
        require(isinstance(profile,dict) and set(profile)=={'protocol_id','class_id','task_id'}
                and profile['protocol_id']=='legacy-full-client-v1' and profile['class_id'] in CLASSES
                and profile['task_id'] in TASKS,'legacy_research_profile_required')
        require(all(entry['spec'].get('schema_version')==1 for entry in plan['entries']),'legacy_specs_required')
        project=project_member;verified=VERIFIED;maximum_video=MAX_VIDEO
    if native_qualification is not None:
        from full_client_hero_qualification_public import project_qualification
        from full_client_hero_native_runtime import qualification_scenario
        from full_client_native import contract, HERO_TOOLKIT_PROTOCOL
        from full_client_score import JSON_LIMIT, parse_json
        require(adaptive_scenario is not None and profile['class_id']=='hero'
            and isinstance(native_qualification,dict)
            and set(native_qualification)=={'artifact_root','receipt_ref'},'invalid_native_qualification_input')
        fixture=plan['fixtures'][0];ref=fixture['runtime_manifest'];path=Path(ref['path'])
        raw=stable_bytes(path,JSON_LIMIT)
        require(digest(raw)==ref['sha256'],'runtime_manifest_hash_mismatch')
        manifest=parse_json(raw)
        expected_pins={'baseline_sha256':fixture['baseline']['sha256'],
            'runtime_manifest_sha256':ref['sha256'],
            **{key+'_sha256':manifest[key]['sha256'] for key in ('server_jar','client_js','client_wasm')}}
        expected_pins['qualification_scenario_sha256']=digest(encoded(qualification_scenario(expected_pins['baseline_sha256'])))
        private=directory(Path(native_qualification['artifact_root']))
        require(not(output_root.is_relative_to(private) or private.is_relative_to(output_root)),
            'private_inputs_must_be_outside_publication')
        qualification=project_qualification(private,native_qualification['receipt_ref'],
            native_contract=contract('hero',expected_pins['baseline_sha256'],protocol=HERO_TOOLKIT_PROTOCOL),
            expected_pins=expected_pins)
        qualification_binding={'path':'native-qualification.json','sha256':digest(encoded(qualification)),
            'baseline_sha256':fixture['baseline']['sha256'],'runtime_manifest_sha256':ref['sha256'],
            'scenario_sha256':fixture['scenario']['sha256'],'budgets':fixture['budgets']}
    staging=Path(tempfile.mkdtemp(prefix='.cohort-',dir=output_root));site=staging/'site';site.mkdir(mode=0o755)
    recordings=site/'recordings';recordings.mkdir(mode=0o755)
    try:
        rows=[project(entry,plan['fixtures'][0],attempt_root,recordings) for entry in plan['entries']]
        fixture=plan['fixtures'][0]
        fingerprint=digest(encoded({**{key:fixture[key]['sha256'] for key in ('scenario','baseline','runtime_manifest')},
                                    'budgets':fixture['budgets']}))
        for row in rows:row['research']={**profile,'fixture_fingerprint':fingerprint,'planned':True}
        groups={}
        for row in rows:
            if row.get('comparison_group') and row['score_verification']==verified:
                groups.setdefault(row['comparison_group'],[]).append(row)
        complete=(all(row['status']=='completed' and row['score_verification']==verified
                      and row.get('recording_publication')=='verified_bytes' for row in rows) and len(groups)==1)
        require(not replace_archive or complete,'four_verified_recordings_required_for_archive_replacement')
        comparisons=[{'id':key,'models':list(dict.fromkeys(r['requested_model'] for r in members)),
                      'ready':len({r['requested_model'] for r in members})>=2,'ranked':False,
                      'attempt_ids':[r['id'] for r in members],'scope':'selected_cohort',
                      'reason':'same_frozen_inputs' if len({r['requested_model'] for r in members})>=2 else 'another_model_required'} for key,members in groups.items()]
        completed=[r for r in rows if r['status']=='completed' and r['score_verification']==verified]
        snapshot={'schema_version':1,'generated_at_ms':max([r['updated_at_ms'] or 0 for r in rows]),
            'source':'full_client_private_receipt_projection','verification':verified,'live_status_available':False,
            'ranked':False,'recording_prefix':'./recordings/','truncated':False,'attempts':rows,'comparisons':comparisons,
            'featured_run_id':max(completed,key=lambda r:r['updated_at_ms'] or 0)['id'] if completed else None,
            'cohort':{'id':plan_sha256,'planned':len(rows),'verified':len(completed),'complete':complete,
                      'archive_replacement':replace_archive,'attempt_ids':[r['id'] for r in rows]}}
        snapshot['research_matrix']=summarize(snapshot)
        if adaptive_scenario is not None and len(rows)>4:
            snapshot['cohort']['reliability']=operational_reliability(rows)
        if qualification is not None:
            snapshot['native_qualification']=qualification
            write_new(site/'native-qualification.json',encoded(qualification),0o644)
        ui=Path(__file__).resolve().parents[1]/'ui/full-client-dashboard'
        for name in ASSETS:write_new(site/name,stable_bytes(ui/name,4*1024**2),0o644)
        videos=[{'path':p.name,**stable_fingerprint(p,maximum_video)}
                for p in sorted(recordings.iterdir())]
        write_new(site/'results.json',encoded(snapshot),0o644)
        write_new(site/'recording-manifest.json',encoded({'schema_version':1,'entries':videos}),0o644)
        write_new(site/'vercel.json',encoded({'framework':None,'buildCommand':None,'outputDirectory':'.'}),0o644)
        content={'schema_version':1,'plan_sha256':plan_sha256,'archive_replacement':replace_archive,
                 'target_path':'/' if replace_archive else '/cohorts/'+plan_sha256[:16]+'/',
                 'protocol':profile['protocol_id'],'files':file_inventory(site,maximum_video=maximum_video)}
        if qualification_binding is not None:content['native_qualification']=qualification_binding
        content_sha=digest(encoded(content));package=output_root/content_sha
        write_new(staging/'package-manifest.json',encoded({'schema_version':1,'content_sha256':content_sha,'content':content}))
        sync_directory(recordings);sync_directory(site);sync_directory(staging)
        if os.path.lexists(package): verify_package(package,content_sha)
        else:
            try: publish_attempt(staging,package)
            except ValueError:
                if not os.path.lexists(package): raise
                verify_package(package,content_sha)
        return {'content_sha256':content_sha,'package':str(package),'site':str(package/'site'),
                'target_path':content['target_path'],'archive_replacement':replace_archive,'cohort_complete':complete,
                'publication_state':publication_state(package,content_sha),'api_requests':0,'deployment_performed':False}
    finally:
        if staging.exists(): shutil.rmtree(staging)


def claim_publication(package, expected):
    """Exclusive intent only. A lost deploy reply must be reconciled, not retried."""
    package=directory(package)
    verify_package(package,expected)
    state=publication_state(package,expected)
    if state!='unclaimed': return {'deployment_allowed':False,'publication_state':state,'content_sha256':expected}
    value={'schema_version':1,'content_sha256':expected,'created_at_ms':round(time.time()*1000),
           'status':'pending_external_deployment','api_requests':0}
    try: write_new(package/'publication-intent.json',encoded(value))
    except FileExistsError: return {'deployment_allowed':False,'publication_state':publication_state(package,expected),'content_sha256':expected}
    return {'deployment_allowed':True,'publication_state':'claimed','content_sha256':expected}


def record_deployment(package, expected, deployment_id, url, verified_content_sha256):
    """Record a root-supplied successful deployment and explicit public-byte check."""
    package=directory(package)
    manifest=verify_package(package,expected)
    require(verified_content_sha256==expected,'public_content_verification_required')
    require(isinstance(deployment_id,str) and re.fullmatch(r'dpl_[A-Za-z0-9]{8,80}',deployment_id),'invalid_deployment_id')
    parts=urlsplit(url)
    require(parts.scheme=='https' and parts.hostname and parts.hostname.endswith('.vercel.app')
            and parts.username is None and parts.password is None and parts.port is None
            and not parts.query and not parts.fragment and (parts.path or '/')==manifest['content']['target_path'],
            'invalid_publication_url')
    require(publication_state(package,expected)!='unclaimed','publication_intent_required')
    value={'schema_version':1,'content_sha256':expected,'deployment_id':deployment_id,'url':url,
           'verification':'operator_supplied_public_content_check','status':'published'}
    path=package/'publication-complete.json'
    if path.exists(): require(same_json(Reader().json(package,path.name),value),'publication_receipt_conflict')
    else:
        try: write_new(path,encoded(value))
        except FileExistsError: require(same_json(Reader().json(package,path.name),value),'publication_receipt_conflict')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('prepare')
    for name in ('plan','attempt-root','output-root'):prepare.add_argument('--'+name,type=Path,required=True)
    prepare.add_argument('--plan-sha256',required=True);prepare.add_argument('--replace-archive',action='store_true')
    prepare.add_argument('--research-profile',type=Path);prepare.add_argument('--research-profile-sha256')
    prepare.add_argument('--adaptive-scenario',type=Path,
                         help='Frozen adaptive scenario; its exact SHA256 must match the pinned plan')
    prepare.add_argument('--native-qualification-config',type=Path)
    prepare.add_argument('--native-qualification-config-sha256')
    for name in ('claim','record-deployment'):
        command=commands.add_parser(name);command.add_argument('--package',type=Path,required=True)
        command.add_argument('--content-sha256',required=True)
        if name=='record-deployment':
            for field in ('deployment-id','url','verified-content-sha256'):command.add_argument('--'+field,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':
            require((args.research_profile is None)==(args.research_profile_sha256 is None),'research_profile_hash_required')
            profile=None if args.research_profile is None else Reader().json(directory(args.research_profile.parent),
                args.research_profile.name,args.research_profile_sha256)
            require((args.native_qualification_config is None)==(args.native_qualification_config_sha256 is None),
                'native_qualification_config_hash_required')
            qualification=None if args.native_qualification_config is None else Reader().json(
                directory(args.native_qualification_config.parent),args.native_qualification_config.name,
                args.native_qualification_config_sha256)
            result=prepare_package(args.plan,args.plan_sha256,args.attempt_root,args.output_root,
                                   replace_archive=args.replace_archive,research_profile=profile,
                                   adaptive_scenario=args.adaptive_scenario,native_qualification=qualification)
        elif args.command=='claim':result=claim_publication(args.package,args.content_sha256)
        else:result=record_deployment(args.package,args.content_sha256,args.deployment_id,args.url,args.verified_content_sha256)
        print(json.dumps(result,sort_keys=True));return 0
    except (ValueError,OSError,TypeError,KeyError,RecursionError):
        print('{"error":"public_cohort_publication_unavailable","deployment_performed":false,"api_requests":0}');return 1


if __name__=='__main__':raise SystemExit(main())
