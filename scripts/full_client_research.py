"""Public protocol-separated research summaries of already projected evidence.

This is a reporting layer, not a scorer. Adaptive and peak-rate scores remain
unknown until their own aggregate evidence adapter is accepted.
"""
import math
import statistics
from full_client_dashboard import model

PROTOCOLS = {
    'legacy-full-client-v1': {'label':'Legacy single-response runs','clock':'Program time; horizon varies by fixture',
        'metric':'Persisted net XP','score_key':'persisted_xp','verifier':'runner_verified_receipts_rechecked',
        'status':'Existing evidence'},
    'full-client-adaptive-pilot-v1': {'label':'Five-minute adaptive pilot','clock':'300 seconds of wall time, including inference',
        'metric':'Persisted net XP across all cycles','score_key':'persisted_xp','verifier':'adaptive_runner_verified_receipts_rechecked',
        'status':'Adaptive pilot; peak-rate score unavailable'},
    'unknown': {'label':'Protocol undeclared','clock':'Unknown','metric':'No comparable score',
        'score_key':None,'verifier':None,'status':'Metadata incomplete'},
}
CLASSES = {'hero':'Hero','bowmaster':'Bowmaster','ice_lightning_arch_mage':'Ice/Lightning Arch Mage',
           'night_lord':'Night Lord','shadower':'Shadower','bishop':'Bishop','undeclared':'Class undeclared'}
TASKS = {'basic_combat':'Basic combat','sustained_hunting':'Sustained hunting',
         'navigation':'Navigation','party_objective':'Party objective','undeclared':'Task undeclared'}


def finite(value):return type(value) in (int,float) and math.isfinite(value) and abs(value)<2**53


def operational_reliability(rows):
    """Evidence completion across four-attempt groups; no causal fault attribution.

    Poor verified scores are valid. A failed attempt can be a model-program or
    infrastructure failure, so the public disposition deliberately says neither.
    """
    if not isinstance(rows,list) or not 4<=len(rows)<=80 or len(rows)%4:
        raise ValueError('reliability_group_shape')
    groups=[];consecutive=0
    for index in range(0,len(rows),4):
        members=rows[index:index+4];causes={};scored=recorded=attempted=0
        for row in members:
            status=row.get('status')
            if status!='not_started':attempted+=1
            valid=(status=='completed' and row.get('score_verification')=='adaptive_runner_verified_receipts_rechecked'
                and row.get('attribution')=='exact' and finite(row.get('persisted_xp'))
                and row.get('adaptive',{}).get('verification')=='all_cycle_receipts_rechecked')
            if valid:scored+=1
            if valid and row.get('recording_publication')=='verified_bytes' and row.get('recording'):
                recorded+=1;continue
            cause=('recording_unavailable' if valid else
                {'not_started':'not_started','running':'in_progress','requesting':'in_progress',
                 'recovering':'in_progress','failed':'attempt_failed','interrupted':'interrupted',
                 'recovered':'recovery_invalidated'}.get(status,'evidence_unavailable'))
            causes[cause]=causes.get(cause,0)+1
        clean=recorded==4
        consecutive=consecutive+1 if clean else 0
        groups.append({'group':index//4+1,'planned':4,'attempted':attempted,'verified_scores':scored,
            'verified_recordings':recorded,'clean':clean,'causes':causes})
    return {'schema_version':1,'groups':groups,'required_consecutive_clean_groups':3,
        'consecutive_clean_groups':consecutive,'gate_passed':consecutive>=3,
        'scope':'observed_release_operations_not_an_sla'}


def summarize(snapshot):
    """Keep versions/fixtures separate and retain attempted-set denominators."""
    rows=snapshot.get('attempts',[])
    if not isinstance(rows,list) or len(rows)>100:raise ValueError('research_row_limit')
    columns={};cells={};models=[]
    for row in rows:
        if not isinstance(row,dict):raise ValueError('invalid_research_row')
        selected=model(row.get('requested_model'))
        if selected is None:continue
        if selected not in models:models.append(selected)
        metadata=row.get('research') if isinstance(row.get('research'),dict) else {}
        protocol=metadata.get('protocol_id',row.get('protocol_id','legacy-full-client-v1'))
        if protocol not in PROTOCOLS:protocol='unknown'
        class_id=metadata.get('class_id','undeclared');task_id=metadata.get('task_id','undeclared')
        if class_id not in CLASSES:class_id='undeclared'
        if task_id not in TASKS:task_id='undeclared'
        frozen=metadata.get('fixture_fingerprint') or row.get('comparison_group')
        if not isinstance(frozen,str) or len(frozen)!=64 or any(c not in 'abcdef0123456789' for c in frozen):frozen='undeclared'
        key=':'.join((protocol,class_id,task_id,frozen))
        columns.setdefault(key,{'id':key,'protocol_id':protocol,'class_id':class_id,'class_label':CLASSES[class_id],
                                'task_id':task_id,'task_label':TASKS[task_id],'fixture_fingerprint':frozen,
                                'metric':PROTOCOLS[protocol]['metric']})
        cells.setdefault((selected,key),[]).append((row,metadata))
    table=[]
    for selected in models:
        values=[]
        for key,column in columns.items():
            members=cells.get((selected,key),[]);protocol=PROTOCOLS[column['protocol_id']]
            planned=sum(metadata.get('planned') is True for _,metadata in members)
            declared=bool(members) and all(metadata.get('planned') is True for _,metadata in members)
            attempted=failed=unknown=running=no_ops=0;samples=[];attempt_ids=[]
            for row,_ in members:
                status=row.get('status');attempt_ids.append(row['id'])
                if status=='not_started':continue
                attempted+=1
                value=row.get(protocol['score_key']) if protocol['score_key'] else None
                valid=(status=='completed' and row.get('kind')=='trial' and row.get('mode')=='api'
                       and protocol['verifier'] is not None
                       and row.get('score_verification')==protocol['verifier'] and row.get('attribution')=='exact'
                       and (column['protocol_id']!='full-client-adaptive-pilot-v1'
                            or (isinstance(row.get('adaptive'),dict)
                                and row['adaptive'].get('verification')=='all_cycle_receipts_rechecked'))
                       and column['fixture_fingerprint']!='undeclared' and finite(value))
                if valid:
                    samples.append(value)
                    if row.get('no_op') is True and row.get('action_verification')=='receipts_rechecked':no_ops+=1
                elif status in ('failed','interrupted','recovered'):failed+=1
                elif status in ('running','recovering','requesting'):running+=1
                else:unknown+=1
            values.append({'column_id':key,'planned':planned if declared else None,'attempted':attempted,
                           'valid':len(samples),'failed':failed,'unknown':unknown,'in_progress':running,
                           'not_started':len(members)-attempted,'no_ops':no_ops,'attempt_ids':attempt_ids,
                           'mean':sum(samples)/len(samples) if samples else None,
                           'minimum':min(samples) if samples else None,'maximum':max(samples) if samples else None,
                           'uncertainty':'not_estimated','ranked':False})
            if len(members)>1:
                values[-1].update(samples=samples,median=statistics.median(samples) if samples else None,
                    sample_standard_deviation=statistics.stdev(samples) if len(samples)>1 else None,
                    eligible_fraction=len(samples)/attempted if attempted else None)
        table.append({'model':selected,'cells':values})
    used={column['protocol_id'] for column in columns.values()}
    return {'schema_version':1,'protocols':[{'id':key,**value} for key,value in PROTOCOLS.items() if key in used],
            'columns':list(columns.values()),'models':table,'ranked':False,
            'research_target':{'horizon_ms':1800000,'window_ms':15000,'metric':'Highest normalized XP/min in a complete authoritative window',
                               'status':'Intended protocol; no peak score inferred from initial/final XP'}}
