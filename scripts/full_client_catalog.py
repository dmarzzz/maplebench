#!/usr/bin/env python3
"""Compose at most three pinned public cohorts; no private receipts or deployment.

Expected content hashes are an operator trust input from prepare_package. This
checks those public bytes and their shape; it never re-scores native evidence.
"""
import argparse
import copy
from html import escape
import unicodedata
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from full_client_dashboard import Reader, RUN, SHA, model, number, project_attempt
from full_client_gallery import copy_recording, directory
from full_client_publication import (ADAPTIVE_PROTOCOL, XP_PROTOCOL, ASSETS, MAX_ADAPTIVE_VIDEO,
    digest, encoded, require, stable_bytes, stable_fingerprint, verify_package, write_new)
from full_client_adaptive_publication import VERIFIED
from full_client_xp_cohort import VERIFIED as XP_VERIFIED, checked_public as checked_native_public
from full_client_research import summarize, TASKS
from full_client_score import same_json
from full_client_trial import publish_attempt
from full_client_vercel import checked_payload, MAX_PAYLOAD, PUBLIC_NAME
from maple_agent import MODELS

CLASSES={'hero':'Hero','bowmaster':'Bowmaster','ice_lightning_arch_mage':'Ice/Lightning Arch Mage','night_lord':'Night Lord'}
ROW_FIELDS=set(project_attempt(Reader(),'0'*32,None,None,{},None,0,'/recordings/'))|{
    'controller_status','live','renderer_fresh','protocol_id','adaptive','sdk_calls','research','recording_publication',
    'authoritative_peak_xp_per_minute','native_xp'}
SNAPSHOT_FIELDS={'schema_version','generated_at_ms','source','verification','live_status_available','ranked',
    'recording_prefix','truncated','attempts','comparisons','featured_run_id','cohort','research_matrix'}


def safe_public(value,depth=0,parent=None):
    """Reject private/code-shaped extensions instead of copying arbitrary JSON."""
    require(depth<=12,'catalog_public_depth')
    if isinstance(value,dict):
        require(len(value)<=100,'catalog_public_shape')
        if parent=='artifact_sha256':
            require(set(value)<={'request','response','program','choice','execution_receipt'}
                and all(isinstance(v,str) and SHA.fullmatch(v) for v in value.values()),'catalog_artifact_hash')
            return
        for key,item in value.items():
            require(isinstance(key,str) and re.fullmatch('[A-Za-z0-9_]+',key)
                and key not in {'code','instructions','prompt','request','response','recent_programs','steps',
                    'logs','environment','credentials','password','api_key','account_id','character_id'},'catalog_private_field')
            safe_public(item,depth+1,key)
    elif isinstance(value,list):
        require(len(value)<=100,'catalog_public_shape')
        for item in value:safe_public(item,depth+1,parent)
    elif isinstance(value,str):
        require(len(value)<=512 and not re.search(r'[\x00-\x1f<>\\]',value),'catalog_public_text')
    else:require(value is None or type(value) is bool or number(value,-2**53+1),'catalog_public_value')


def public_snapshot(snapshot,*,adaptive):
    require(isinstance(snapshot,dict) and set(snapshot)<=SNAPSHOT_FIELDS
        and type(snapshot.get('schema_version')) is int and snapshot['schema_version']==1
        and snapshot.get('ranked') is False and snapshot.get('live_status_available') is False
        and snapshot.get('truncated') is False and number(snapshot.get('generated_at_ms'))
        and isinstance(snapshot.get('attempts'),list) and len(snapshot['attempts'])<90
        and isinstance(snapshot.get('comparisons'),list),'catalog_snapshot_schema')
    rows=snapshot['attempts'];ids=[]
    for row in rows:
        require(isinstance(row,dict) and set(row)<=ROW_FIELDS and RUN.fullmatch(str(row.get('id','')))
            and row.get('ranked') is False and (row.get('publication_eligible') is False
                or (row.get('protocol_id')==XP_PROTOCOL and row.get('publication_eligible') is True)), 'catalog_public_row')
        safe_public(row);ids.append(row['id'])
        if adaptive:
            require(row.get('kind')=='trial' and row.get('mode')=='api'
                and model(row.get('requested_model')) is not None
                and row.get('status') in ('not_started','running','requesting','recovering','recovered',
                    'failed','interrupted','completed','unavailable'),'catalog_adaptive_row')
    require(len(set(ids))==len(ids),'catalog_duplicate_attempt')
    for group in snapshot['comparisons']:
        require(isinstance(group,dict) and set(group)<= {'id','models','ready','ranked','attempt_ids','scope','reason'}
            and SHA.fullmatch(str(group.get('id'))) and group.get('ranked') is False
            and isinstance(group.get('attempt_ids'),list) and set(group['attempt_ids'])<=set(ids)
            and len(set(group['attempt_ids']))==len(group['attempt_ids']),'catalog_comparison_shape')
        safe_public(group)
    return rows


def verified(row):
    if row.get('protocol_id')==XP_PROTOCOL:
        return checked_native_public(row)
    return (row.get('status')=='completed' and row.get('score_verification')==VERIFIED
        and row.get('attribution')=='exact' and row.get('returned_model')==row.get('requested_model')
        and number(row.get('persisted_xp'),-2**53+1)
        and isinstance(row.get('adaptive'),dict)
        and row['adaptive'].get('verification')=='all_cycle_receipts_rechecked')


def cohort(package,expected):
    require(isinstance(expected,str) and SHA.fullmatch(expected),'catalog_content_hash_required')
    manifest=verify_package(package,expected)
    require(type(manifest['schema_version']) is int,'catalog_package_schema')
    content=manifest['content'];site=directory(Path(package)/'site')
    require(set(content)-{'presentation_parent_sha256'}=={'schema_version','plan_sha256','archive_replacement','target_path','protocol','files'}
        and ('presentation_parent_sha256' not in content or (isinstance(content['presentation_parent_sha256'],str)
            and SHA.fullmatch(content['presentation_parent_sha256'])))
        and type(content['schema_version']) is int and content['schema_version']==1
        and content['protocol'] in (ADAPTIVE_PROTOCOL,XP_PROTOCOL) and content['archive_replacement'] is False
        and SHA.fullmatch(str(content['plan_sha256']))
        and content['target_path']=='/cohorts/'+content['plan_sha256'][:16]+'/','catalog_nested_adaptive_package_required')
    protocol=content['protocol'];verifier=XP_VERIFIED if protocol==XP_PROTOCOL else VERIFIED
    snapshot=Reader().json(site,'results.json');rows=public_snapshot(snapshot,adaptive=True)
    require(snapshot.get('source')=='full_client_private_receipt_projection' and snapshot.get('verification')==verifier
        and len(rows)==4 and {r['requested_model'] for r in rows}==set(MODELS),'catalog_all_four_models_required')
    metadata=[r.get('research') for r in rows]
    require(all(isinstance(m,dict) and set(m)=={'protocol_id','class_id','task_id','fixture_fingerprint','planned'}
        and m['protocol_id']==protocol and m['class_id'] in CLASSES and m['task_id'] in TASKS
        and SHA.fullmatch(str(m['fixture_fingerprint'])) and m['planned'] is True for m in metadata)
        and all(same_json(metadata[0],m) for m in metadata),'catalog_fixture_separation_required')
    for row in rows:
        if row.get('score_verification')==verifier:
            require(verified(row) and row.get('protocol_id')==protocol
                and row['adaptive'].get('class_profile',{}).get('class_name')==CLASSES[metadata[0]['class_id']]
                and SHA.fullmatch(str(row.get('comparison_group'))),'catalog_verified_row_inconsistent')
        else:require(row.get('persisted_xp') is None and row.get('comparison_group') is None
            and row.get('authoritative_peak_xp_per_minute') is None
            and row.get('publication_eligible') is False,'catalog_unverified_score')
    videos=Reader().json(site,'recording-manifest.json')
    require(set(videos)=={'schema_version','entries'} and type(videos['schema_version']) is int and videos['schema_version']==1
        and isinstance(videos['entries'],list),'catalog_recording_manifest')
    declared={}
    for entry in videos['entries']:
        require(isinstance(entry,dict) and set(entry)=={'path','sha256','bytes'}
            and re.fullmatch(r'[a-f0-9]{32}\.webm',str(entry['path']))
            and entry['path'] not in declared,'catalog_recording_manifest')
        declared[entry['path']]={k:entry[k] for k in ('sha256','bytes')}
    actual={name.removeprefix('recordings/'):value for name,value in content['files'].items() if name.startswith('recordings/')}
    require(same_json(declared,actual),'catalog_recording_manifest')
    linked=set();groups={}
    for row in rows:
        if verified(row):groups.setdefault(row['comparison_group'],[]).append(row)
        recording=row.get('recording')
        if recording is not None:
            filename=row['id']+'.webm'
            require(isinstance(recording,dict) and set(recording)<={'url','sha256','reviewed','playback'}
                and recording.get('url')=='./recordings/'+filename and filename in declared
                and recording.get('sha256')==declared[filename]['sha256']
                and verified(row) and row.get('recording_publication')=='verified_bytes','catalog_recording_binding')
            linked.add(filename)
        else:require(row.get('recording_publication')!='verified_bytes','catalog_recording_binding')
    require(linked==set(declared),'catalog_unlinked_recording')
    comparisons=[{'id':key,'models':[r['requested_model'] for r in members],'ready':len(members)>=2,'ranked':False,
        'attempt_ids':[r['id'] for r in members],'scope':'selected_cohort',
        'reason':'same_frozen_inputs' if len(members)>=2 else 'another_model_required'} for key,members in groups.items()]
    require(same_json(snapshot['comparisons'],comparisons) and same_json(snapshot.get('research_matrix'),summarize(snapshot)),
            'catalog_forged_public_summary')
    complete=len(linked)==4 and len(groups)==1 and all(verified(r) for r in rows)
    expected_cohort={'id':content['plan_sha256'],'planned':4,'verified':sum(verified(r) for r in rows),
        'complete':complete,'archive_replacement':False,'attempt_ids':[r['id'] for r in rows]}
    require(same_json(snapshot.get('cohort'),expected_cohort),'catalog_cohort_metadata')
    featured=max([r for r in rows if verified(r)],key=lambda r:r['updated_at_ms'] or 0,default=None)
    require(snapshot.get('featured_run_id')==(featured['id'] if featured else None),'catalog_featured_binding')
    return {'package':Path(package),'site':site,'manifest':manifest,'snapshot':snapshot,'complete':complete,
        'class_id':metadata[0]['class_id'],'fixture_fingerprint':metadata[0]['fixture_fingerprint']}


def copy_file(source,name,target,expected):
    target.parent.mkdir(parents=True,exist_ok=True)
    if name.endswith('.webm'):
        copy_recording(source,{'path':name,'sha256':expected['sha256']},target,{},maximum=MAX_ADAPTIVE_VIDEO)
    else:write_new(target,stable_bytes(source/name,4*1024**2),0o644)
    require(stable_fingerprint(target,MAX_ADAPTIVE_VIDEO if name.endswith('.webm') else 4*1024**2)==expected,
            'catalog_source_changed')


def cohort_annotations(value,included):
    require(isinstance(value,list) and len(value)<=6,'catalog_annotations_limit')
    known={row['id']:row for row in included};seen=set();seen_text=set();notes=[]
    for item in value:
        require(isinstance(item,dict) and set(item)=={'plan_sha256','text'},'catalog_annotation_schema')
        plan=item['plan_sha256'];text=item['text']
        require(isinstance(plan,str) and SHA.fullmatch(plan) and plan in known,'catalog_annotation_unknown_cohort')
        require(plan not in seen,'catalog_annotation_duplicate');seen.add(plan)
        require(isinstance(text,str) and 1<=len(text)<=400 and text==text.strip()
                and not any(unicodedata.category(c).startswith('C') for c in text)
                and not re.search(r'[<>\[\]{}\\`*#]|://|(?:^|\s)/|[\w.+-]+@[\w.-]+|(?:\d{1,3}\.){3}\d{1,3}|(?:token|password|secret|api_key)\s*[:=]',text,re.IGNORECASE),
                'catalog_annotation_text')
        require(text not in seen_text,'catalog_annotation_duplicate');seen_text.add(text)
        notes.append({'plan_sha256':plan,'text':text,'url':known[plan]['url'],
                      'class_id':known[plan]['class_id']})
    return sorted(notes,key=lambda row:row['plan_sha256'])


def annotated_index(raw,notes):
    text=raw.decode('utf-8');require(text.count('</header>')==1,'catalog_annotation_html_anchor')
    body=''.join('<article><h3><a href="'+escape(note['url'],quote=True)+'">'
                 +escape(CLASSES[note['class_id']])+' cohort</a></h3><p>'
                 +escape(note['text'],quote=True)+'</p></article>' for note in notes)
    section='<section class="research-intro" aria-label="Operator cohort limitations"><h2>Cohort limitations</h2>'+body+'</section>'
    return text.replace('</header>','</header>'+section,1).encode('utf-8')


def compose(request,output_root):
    require(isinstance(request,dict) and type(request.get('schema_version')) is int
        and ((request['schema_version']==1 and set(request)-{'annotations'}=={'schema_version','cohorts','primary_content_sha256','archive'})
             or (request['schema_version']==2 and set(request)-{'annotations'}=={'schema_version','cohorts','primary_content_sha256','archive','previous_cohorts'}))
        and isinstance(request['cohorts'],list)
        and 1<=len(request['cohorts'])<=4,'catalog_request_schema')
    packages=[]
    for item in request['cohorts']:
        require(isinstance(item,dict) and set(item)=={'package','content_sha256'},'catalog_package_selection')
        packages.append(cohort(item['package'],item['content_sha256']))
    previous=[]
    selections=request.get('previous_cohorts',[])
    require(isinstance(selections,list) and len(selections)<=3,'catalog_previous_cohorts_limit')
    for item in selections:
        require(isinstance(item,dict) and set(item)=={'package','content_sha256'},'catalog_package_selection')
        previous.append(cohort(item['package'],item['content_sha256']))
    all_packages=packages+previous
    primary=request['primary_content_sha256']
    require(primary in [p['manifest']['content_sha256'] for p in packages],'catalog_primary_required')
    for key,values in (
        ('class',[p['class_id'] for p in packages]),('fixture',[p['fixture_fingerprint'] for p in packages]),
        ('cohort',[p['manifest']['content']['plan_sha256'][:16] for p in packages])):
        require(len(set(values))==len(values),'catalog_duplicate_'+key)
    require(len({p['manifest']['content']['target_path'] for p in all_packages})==len(all_packages),'catalog_duplicate_mount')
    require(len({r['id'] for p in all_packages for r in p['snapshot']['attempts']})==4*len(all_packages),'catalog_duplicate_attempt')
    packages.sort(key=lambda p:list(CLASSES).index(p['class_id']))
    assets=[{name:p['manifest']['content']['files'][name] for name in ASSETS} for p in packages]
    require(all(same_json(assets[0],value) for value in assets),'catalog_mixed_assets')
    primary_complete=next(p['complete'] for p in packages if p['manifest']['content_sha256']==primary)
    replaced_previous=all(any(p['complete'] and p['class_id']==prior['class_id'] for p in packages) for prior in previous)
    archive=request['archive'];old=None;old_files={};retired=bool((archive or previous) and primary_complete and replaced_previous)
    retained_previous=[] if retired else previous
    if archive is not None:
        require(isinstance(archive,dict) and set(archive)=={'site','inventory','inventory_sha256'},'catalog_archive_inventory_required')
        old_site=directory(Path(archive['site']))
        old_files,_=checked_payload(old_site,Path(archive['inventory']),archive['inventory_sha256'],{'content':{'target_path':'/','files':{}}})
        require(not any(name.startswith('cohorts/') for name in old_files),'catalog_archive_must_be_legacy')
        old=Reader().json(old_site,'results.json');public_snapshot(old,adaptive=False)
        require(all(r.get('protocol_id','legacy-full-client-v1')=='legacy-full-client-v1' for r in old['attempts']),
                'catalog_archive_must_be_legacy')
        for row in old['attempts']:
            if row.get('recording'):
                path='recordings/'+row['id']+'.webm'
                require(row['recording'].get('url') in ('./'+path,'/'+path)
                    and path in old_files and row['recording'].get('sha256')==old_files[path]['sha256'],
                    'catalog_archive_recording_binding')
    rows=[];comparisons=[];cohorts=[]
    for p in packages:
        content=p['manifest']['content'];snapshot=p['snapshot'];prefix=content['target_path'];members=copy.deepcopy(snapshot['attempts'])
        for row in members:
            if row.get('recording'):row['recording']['url']='.'+prefix+'recordings/'+row['id']+'.webm'
        rows.extend(members);comparisons.extend(copy.deepcopy(snapshot['comparisons']))
        cohorts.append({'id':content['plan_sha256'],'content_sha256':p['manifest']['content_sha256'],
            'url':'.'+prefix,'class_id':p['class_id'],'fixture_fingerprint':p['fixture_fingerprint'],
            'planned':4,'verified':snapshot['cohort']['verified'],'complete':p['complete'],
            'attempt_ids':[r['id'] for r in members]})
    new_rows=list(rows)
    previous_metadata=[]
    for p in retained_previous:
        content=p['manifest']['content'];members=copy.deepcopy(p['snapshot']['attempts'])
        group_ids={g['id']:digest(encoded({'previous_cohort':content['plan_sha256'],'comparison':g['id']}))
                   for g in p['snapshot']['comparisons']}
        for row in members:
            if row.get('recording'):row['recording']['url']='.'+content['target_path']+'recordings/'+row['id']+'.webm'
            if row.get('comparison_group'):row['comparison_group']=group_ids[row['comparison_group']]
        rows.extend(members)
        prior_comparisons=copy.deepcopy(p['snapshot']['comparisons'])
        for group in prior_comparisons:
            group['id']=group_ids[group['id']];group['scope']='previous_cohort'
        comparisons.extend(prior_comparisons)
        previous_metadata.append({'id':content['plan_sha256'],'content_sha256':p['manifest']['content_sha256'],
            'url':'.'+content['target_path'],'class_id':p['class_id'],'fixture_fingerprint':p['fixture_fingerprint'],
            'scope':'previous_cohort','label':'Previous pilot cohort','planned':4,
            'verified':p['snapshot']['cohort']['verified'],'complete':p['complete'],
            'attempt_ids':[r['id'] for r in members]})
    if old:require({r['id'] for r in rows}.isdisjoint(r['id'] for r in old['attempts']),'catalog_duplicate_attempt')
    if old and not retired:rows.extend(copy.deepcopy(old['attempts']));comparisons.extend(copy.deepcopy(old['comparisons']))
    require(len({r['id'] for r in rows})==len(rows),'catalog_duplicate_attempt')
    require(len({g['id'] for g in comparisons})==len(comparisons),'catalog_duplicate_comparison')
    featured=max([r for r in new_rows if verified(r) and r.get('recording')],
                 key=lambda r:(r['updated_at_ms'] or 0,r['id']),default=None)
    if featured is None:
        previous_ids={i for p in previous_metadata for i in p['attempt_ids']}
        featured=max([r for r in rows if r['id'] in previous_ids and verified(r) and r.get('recording')],
                     key=lambda r:(r['updated_at_ms'] or 0,r['id']),default=None)
    snapshot={'schema_version':1,'generated_at_ms':max([r['updated_at_ms'] or 0 for r in rows],default=0),
        'source':'full_client_public_catalog','verification':'pinned_public_cohort_packages','live_status_available':False,
        'ranked':False,'recording_prefix':'./recordings/','truncated':False,'attempts':rows,'comparisons':comparisons,
        'featured_run_id':featured['id'] if featured else (old.get('featured_run_id') if old and not retired else None),
        'catalog':{'schema_version':request['schema_version'],'planned':len(new_rows),'verified':sum(verified(r) for r in new_rows),
            'complete_cohorts':sum(p['complete'] for p in packages),'cohorts':cohorts,'poll_interval_ms':10000,
            'archive_state':'retired' if retired else 'retained' if old or previous else 'not_supplied'}}
    notes=cohort_annotations(request.get('annotations',[]),cohorts+previous_metadata)
    if notes:snapshot['catalog']['annotations']=notes
    if request['schema_version']==2:snapshot['catalog']['previous_cohorts']=previous_metadata
    snapshot['research_matrix']=summarize(snapshot) if request['schema_version']==1 else summarize(snapshot|{'attempts':new_rows,'comparisons':[g for g in comparisons if g.get('scope')!='previous_cohort']})
    root_names=set(ASSETS)|{'results.json','recording-manifest.json','vercel.json'}
    planned_files={name:value for name,value in old_files.items() if name not in root_names} if old and not retired else {}
    for p in packages+retained_previous:
        content=p['manifest']['content'];prefix=content['target_path'].lstrip('/')
        planned_files.update({prefix+name:value for name,value in content['files'].items()})
    ui=Path(__file__).resolve().parents[1]/'ui/full-client-dashboard'
    root_data={name:stable_bytes(ui/name,1024**2) for name in ASSETS}
    if notes:root_data['index.html']=annotated_index(root_data['index.html'],notes)
    root_data.update({'results.json':encoded(snapshot),
        'vercel.json':encoded({'framework':None,'buildCommand':None,'outputDirectory':'.'}),
        'recording-manifest.json':encoded({'schema_version':1,'entries':[
            {'path':name,**value} for name,value in sorted(planned_files.items()) if name.endswith('.webm')]})})
    planned_files.update({name:{'bytes':len(raw),'sha256':digest(raw)} for name,raw in root_data.items()})
    require(len(planned_files)<=100 and all(PUBLIC_NAME.fullmatch(name) for name in planned_files)
        and sum(v['bytes'] for v in planned_files.values())<=MAX_PAYLOAD,'catalog_payload_limit')
    output_root=directory(Path(output_root))
    for source in [p['package'] for p in all_packages]+([old_site] if old else []):
        require(not output_root.is_relative_to(source) and not source.is_relative_to(output_root),'catalog_inputs_overlap_output')
    stage=Path(tempfile.mkdtemp(prefix='.catalog-',dir=output_root));site=stage/'site';site.mkdir(mode=0o755)
    try:
        if old and not retired:
            for name,value in old_files.items():
                if name not in set(ASSETS)|{'results.json','recording-manifest.json','vercel.json'}:
                    copy_file(old_site,name,site/name,value)
        for p in packages+retained_previous:
            content=p['manifest']['content'];prefix=content['target_path'].lstrip('/')
            (site/prefix/'recordings').mkdir(parents=True,mode=0o755)
            for name,value in content['files'].items():copy_file(p['site'],name,site/prefix/name,value)
        for name,raw in root_data.items():write_new(site/name,raw,0o644)
        files={p.relative_to(site).as_posix():stable_fingerprint(p,MAX_ADAPTIVE_VIDEO if p.suffix=='.webm' else 4*1024**2)
               for p in sorted(site.rglob('*')) if p.is_file()}
        require(same_json(files,planned_files),'catalog_source_changed')
        inventory=encoded({'schema_version':1,'files':files});write_new(stage/'payload-inventory.json',inventory)
        primary_package=next(p for p in packages if p['manifest']['content_sha256']==primary)
        checked_payload(site,stage/'payload-inventory.json',digest(inventory),primary_package['manifest'])
        content={'schema_version':1,'source_content_sha256':[p['manifest']['content_sha256'] for p in packages],
            'archive_inventory_sha256':archive['inventory_sha256'] if archive else None,'archive_retired':retired,'files':files}
        if request['schema_version']==2:
            content.update(schema_version=2,previous_content_sha256=[p['manifest']['content_sha256'] for p in previous])
        if notes:content['annotations']=notes
        ident=digest(encoded(content));write_new(stage/'catalog-manifest.json',encoded({'schema_version':1,'content_sha256':ident,'content':content}))
        destination=output_root/ident
        if os.path.lexists(destination):
            existing=Reader().json(directory(destination),'catalog-manifest.json')
            require(same_json(existing['content'],content) and existing['content_sha256']==ident,'catalog_existing_changed')
            checked_payload(destination/'site',destination/'payload-inventory.json',digest(inventory),primary_package['manifest'])
        else:publish_attempt(stage,destination)
        return {'catalog_sha256':ident,'directory':str(destination),'site':str(destination/'site'),
            'inventory':str(destination/'payload-inventory.json'),'inventory_sha256':digest(inventory),
            'primary_package':str(primary_package['package']),'primary_content_sha256':primary,
            'archive_retired':retired,'cohort_count':len(packages),'api_requests':0,'deployment_performed':False}
    finally:
        if stage.exists():shutil.rmtree(stage)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True);parser.add_argument('--request-sha256',required=True)
    parser.add_argument('--output-root',type=Path,required=True);args=parser.parse_args(argv)
    try:
        request=Reader().json(directory(args.request.parent),args.request.name,args.request_sha256)
        print(json.dumps(compose(request,args.output_root),sort_keys=True));return 0
    except (ValueError,OSError,TypeError,KeyError,RecursionError):
        print(json.dumps({'status':'refused','reason':'catalog_inputs_or_bytes_invalid'}));return 1


if __name__=='__main__':raise SystemExit(main())
