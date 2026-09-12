"""Public protocol-separated research summaries of already projected evidence.

This is a reporting layer, not a scorer. Adaptive and peak-rate scores remain
unknown until their own aggregate evidence adapter is accepted.
"""
import math
from full_client_dashboard import model

PROTOCOLS = {
    'legacy-full-client-v1': {'label':'Legacy single-response runs','clock':'Program time; horizon varies by fixture',
        'metric':'Persisted net XP','score_key':'persisted_xp','verifier':'runner_verified_receipts_rechecked',
        'status':'Existing evidence'},
    'full-client-adaptive-pilot-v1': {'label':'Five-minute adaptive pilot','clock':'300 seconds of wall time, including inference',
        'metric':'Persisted net XP across all cycles','score_key':'persisted_xp','verifier':'adaptive_runner_verified_receipts_rechecked',
        'status':'Adaptive pilot; peak-rate score unavailable'},
    'full-client-xp-windows-v1': {'label':'Training v2 qualification',
        'clock':'300 seconds of wall time, including inference',
        'metric':'Highest normalized XP/min in a complete native 15-second window',
        'score_key':'authoritative_peak_xp_per_minute','verifier':'native_window_runner_receipts_rechecked',
        'status':'Native XP evidence and separate recording reviews required; unranked'},
    'unknown': {'label':'Protocol undeclared','clock':'Unknown','metric':'No comparable score',
        'score_key':None,'verifier':None,'status':'Metadata incomplete'},
}
CLASSES = {'hero':'Hero','bowmaster':'Bowmaster','ice_lightning_arch_mage':'Ice/Lightning Arch Mage',
           'night_lord':'Night Lord','shadower':'Shadower','bishop':'Bishop','undeclared':'Class undeclared'}
TASKS = {'basic_combat':'Basic combat','sustained_hunting':'Sustained hunting',
         'navigation':'Navigation','party_objective':'Party objective','undeclared':'Task undeclared'}


def finite(value):return type(value) in (int,float) and math.isfinite(value) and abs(value)<2**53


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
                       and (column['protocol_id'] not in ('full-client-adaptive-pilot-v1','full-client-xp-windows-v1')
                            or (isinstance(row.get('adaptive'),dict)
                                and row['adaptive'].get('verification')=='all_cycle_receipts_rechecked'))
                       and (column['protocol_id']!='full-client-xp-windows-v1'
                            or (row.get('publication_eligible') is True and isinstance(row.get('native_xp'),dict)
                                and row['native_xp'].get('publication_eligible') is True))
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
        table.append({'model':selected,'cells':values})
    used={column['protocol_id'] for column in columns.values()}
    return {'schema_version':1,'protocols':[{'id':key,**value} for key,value in PROTOCOLS.items() if key in used],
            'columns':list(columns.values()),'models':table,'ranked':False,
            'research_target':{'horizon_ms':1800000,'window_ms':15000,'metric':'Highest normalized XP/min in a complete authoritative window',
                               'status':'Intended protocol; no peak score inferred from initial/final XP'}}
