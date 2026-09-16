"""Pure, fail-closed verification of the native skill-task JSONL event stream.

A valid hash chain binds bytes, not their provenance. The runtime must separately
pin the collector/binaries, readiness, native arm receipt and completed lifecycle.
Only S3's native item transaction is supported by the present producer. S1/S2 do
not become qualified by relabelling accepted client movement as physics evidence.
"""
import hashlib
import re

from full_client_score import parse_json
from full_client_skill_tasks import (PROTOCOL, LEDGER_SOURCE, digest, integer,
                                     fingerprint, validate_contract)

VERIFIER_PROTOCOL = 'native-skill-task-verifier-v1'
MAX_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 100000
ENVELOPE = {'schema_version','source','kind','run_id','server_instance_id','character_id',
            'account_id','task_id','binding_sha256','runtime_sha256','sequence','event_id',
            'elapsed_ns','wall_ms','previous_sha256','data'}
EXPECTED = {'run_id','server_instance_id','character_id','account_id','runtime_sha256',
            'ledger_sha256','start_monotonic_ns','start_wall_ms','duration_ns'}
SNAPSHOT = {'item_id','quantity','hp','mp','max_hp','max_mp','alive','online','snapshot_atomic'}


class InvalidEvidence(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise InvalidEvidence(code)


def fields(value, keys, code='event_schema_mismatch'):
    require(type(value) is dict and set(value) == set(keys), code)


def identity(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{32}', value) is not None


def event_id(value):
    return type(value) is str and re.fullmatch('e[0-9]{8}', value) is not None


def boolean(value):
    return type(value) is bool


def snapshot(value, initial):
    fields(value, SNAPSHOT, 'native_boundary_missing')
    require(type(value['item_id']) is int and value['item_id'] == 2000005
            and integer(value['quantity'],0,1)
            and type(value['max_hp']) is int and value['max_hp'] == initial['max_hp']
            and type(value['max_mp']) is int and value['max_mp'] == initial['max_mp']
            and integer(value['hp'],0,value['max_hp']) and integer(value['mp'],0,value['max_mp'])
            and boolean(value['alive']) and value['alive'] == (value['hp'] > 0)
            and value['online'] is True and value['snapshot_atomic'] is False,
            'native_boundary_invalid')


def _parse(raw, contract, expected):
    fields(expected, EXPECTED, 'trusted_context_missing')
    require(all(identity(expected[k]) for k in ('run_id','server_instance_id'))
            and all(integer(expected[k],1,2**31-1) for k in ('character_id','account_id'))
            and all(digest(expected[k]) for k in ('runtime_sha256','ledger_sha256'))
            and integer(expected['start_monotonic_ns'],0,2**63-1)
            and integer(expected['start_wall_ms'],1,2**53-1)
            and type(expected['duration_ns']) is int and expected['duration_ns'] == 120000000000,
            'trusted_context_invalid')
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES and raw.endswith(b'\n'), 'ledger_bytes_invalid')
    require(hashlib.sha256(raw).hexdigest() == expected['ledger_sha256'], 'ledger_hash_mismatch')
    lines=raw.splitlines(keepends=True)
    require(2 <= len(lines) <= MAX_EVENTS, 'ledger_event_count')
    rows=[];previous='0'*64;elapsed=-1;wall=-1
    for sequence,line in enumerate(lines):
        require(len(line) <= 65536 and line.endswith(b'\n'), 'ledger_line_invalid')
        try:
            row=parse_json(line)
        except (ValueError,UnicodeError):
            raise InvalidEvidence('ledger_json_invalid') from None
        fields(row,ENVELOPE)
        require(type(row['schema_version']) is int and row['schema_version']==1
                and row['source']==LEDGER_SOURCE and row['task_id']==contract['task_id']
                and row['binding_sha256']==contract['binding_sha256'], 'ledger_binding_mismatch')
        require(all(type(row[k]) is type(expected[k]) and row[k]==expected[k]
                    for k in ('run_id','server_instance_id','character_id','account_id','runtime_sha256')),
                'ledger_identity_mismatch')
        require(type(row['sequence']) is int and row['sequence']==sequence
                and row['event_id']==f'e{sequence:08d}' and row['previous_sha256']==previous,
                'ledger_chain_mismatch')
        require(integer(row['elapsed_ns'],0,125000000000) and row['elapsed_ns'] >= elapsed
                and integer(row['wall_ms'],expected['start_wall_ms'],2**53-1)
                and row['wall_ms'] >= wall
                and abs(row['wall_ms']-expected['start_wall_ms']-row['elapsed_ns']/1000000)
                    <= contract['clock']['native_wall_clock_drift_ms'], 'native_clock_invalid')
        require(type(row['kind']) is str and type(row['data']) is dict, 'event_schema_mismatch')
        previous=hashlib.sha256(line).hexdigest();elapsed=row['elapsed_ns'];wall=row['wall_ms'];rows.append(row)
    header=rows[0];terminal=rows[-1]
    require(header['kind']=='header' and header['elapsed_ns']==0
            and terminal['kind']=='terminal', 'closed_native_window_required')
    h=header['data'];t=terminal['data']
    fields(h,{'start_monotonic_ns','deadline_elapsed_ns','movement_physics_validated',
              'teleport_causal_link_supported','coverage_source','initial',
              'resource_coverage','inventory_coverage'},'native_header_invalid')
    require(type(h['start_monotonic_ns']) is int and h['start_monotonic_ns']==expected['start_monotonic_ns']
            and type(h['deadline_elapsed_ns']) is int and h['deadline_elapsed_ns']==expected['duration_ns']
            and h['movement_physics_validated'] is False and h['teleport_causal_link_supported'] is False
            and h['coverage_source']=='accepted_movement_packets_only'
            and h['resource_coverage']=='apply_hp_mp_change_only'
            and h['inventory_coverage']=='remove_item_only', 'unsupported_native_capabilities')
    fields(t,{'complete','event_count_before_terminal','qualification_claim','actor'},'native_terminal_invalid')
    require(t['complete'] is True and t['qualification_claim'] is False
            and type(t['event_count_before_terminal']) is int
            and t['event_count_before_terminal']==len(rows)-1,'native_terminal_invalid')
    initial=contract['binding']['initial']
    snapshot(h['initial'],initial);snapshot(t['actor'],initial)
    require(all(h['initial'][key]==initial[key] for key in ('hp','mp','max_hp','max_mp'))
            and h['initial']['quantity']==initial['power_elixirs'], 'native_initial_mismatch')
    return rows


def _resource(d, initial):
    fields(d,{'transaction_id','hp_before','mp_before','hp_after','mp_after','max_hp','max_mp',
              'route','native_stat_lock_held'})
    require(d['route']=='apply_hp_mp_change' and d['native_stat_lock_held'] is True,
            'native_resource_route_invalid')
    for resource in ('hp','mp'):
        require(type(d['max_'+resource]) is int and d['max_'+resource]==initial['max_'+resource]
                and all(integer(d[resource+'_'+edge],0,d['max_'+resource]) for edge in ('before','after')),
                'native_resource_invalid')


def _movement(d, contract):
    fields(d,{'transaction_id','map_id','accepted_x','accepted_y','alive','absolute_fragments',
              'physics_validated','coverage_source'})
    require(type(d['map_id']) is int and d['map_id']==contract['binding']['geometry']['map_id']
            and integer(d['accepted_x'],-32768,32767) and integer(d['accepted_y'],-32768,32767)
            and boolean(d['alive']) and d['physics_validated'] is False
            and d['coverage_source']=='fresh_packet_receipt'
            and type(d['absolute_fragments']) is list and len(d['absolute_fragments'])<=255,
            'native_movement_invalid')
    for f in d['absolute_fragments']:
        require(type(f) is dict and boolean(f.get('geometry_present')), 'native_fragment_invalid')
        keys={'x','y','foothold','fragment_type','stance','client_duration_ms','geometry_present'}
        fields(f,keys|({'geometry','on_foothold_line'} if f['geometry_present'] else set()))
        require(all(integer(f[k],-32768,32767) for k in ('x','y','foothold','client_duration_ms'))
                and integer(f['fragment_type'],-128,127) and integer(f['stance'],-128,127), 'native_fragment_invalid')
        if f['geometry_present']:
            require(type(f['geometry']) is list and len(f['geometry'])==4
                    and all(integer(x,-32768,32767) for x in f['geometry'])
                    and boolean(f['on_foothold_line']), 'native_fragment_invalid')


def _transactions(rows, contract):
    """Resolve native transaction membership by IDs, never proximity or ACKs."""
    opened={};closed={};initial=contract['binding']['initial'];by_id={r['event_id']:r for r in rows}
    for row in rows[1:-1]:
        kind=row['kind'];d=row['data'];tid=d.get('transaction_id')
        if kind=='transaction_begin':
            fields(d,{'transaction_kind','subject_id','skill_level','parent_transaction_id'})
            require(d['transaction_kind']=='item_use' and type(d['subject_id']) is int and d['subject_id']==2000005
                    and type(d['skill_level']) is int and d['skill_level']==0
                    and d['parent_transaction_id']=='', 'undeclared_native_transaction')
            # Ordinary S3 item packets serialize on the client. Interleaving with
            # unrelated passive resource events remains allowed and unattributed.
            require(not opened,'overlapping_item_transactions')
            opened[row['event_id']]={'begin':row,'resource_transaction':[],
                'inventory_transaction':[],'item_effect_result':[],'item_transaction':[]}
            continue
        require(tid=='' or event_id(tid), 'transaction_id_invalid')
        require(tid=='' or tid in opened, 'transaction_reference_invalid')
        if kind=='resource_transaction':
            _resource(d,initial)
        elif kind=='inventory_transaction':
            fields(d,{'transaction_id','inventory_type','slot','item_id','slot_quantity_before',
                      'slot_quantity_after','route','native_inventory_lock_held'})
            require(d['inventory_type']=='USE' and integer(d['slot'],1,96)
                    and type(d['item_id']) is int and d['item_id']==2000005
                    and all(integer(d[k],0,1) for k in ('slot_quantity_before','slot_quantity_after'))
                    and d['slot_quantity_after']<=d['slot_quantity_before']
                    and d['route']=='inventory_remove_item' and d['native_inventory_lock_held'] is False,
                    'native_inventory_invalid')
            require(tid!='','unattributed_inventory_change')
        elif kind=='item_effect_result':
            fields(d,{'transaction_id','item_id','applied','route'})
            require(tid!='' and type(d['item_id']) is int and d['item_id']==2000005
                    and boolean(d['applied']) and d['route']=='item_stat_effect_apply_to','native_item_effect_invalid')
        elif kind=='item_transaction':
            fields(d,{'transaction_id','item_id','route','committed','quantity_before','quantity_after',
                      'hp_before','hp_after','mp_before','mp_after','max_hp','max_mp','alive',
                      'resource_event_ids','inventory_event_ids','endpoint_snapshots_atomic'})
            require(tid!='' and type(d['item_id']) is int and d['item_id']==2000005
                    and d['route']=='ordinary_item_packet' and boolean(d['committed'])
                    and boolean(d['alive']) and d['alive']==(d['hp_after']>0)
                    and d['endpoint_snapshots_atomic'] is False,'native_item_route_invalid')
            require(all(integer(d[k],0,1) for k in ('quantity_before','quantity_after')),'native_item_quantity_invalid')
            for resource in ('hp','mp'):
                require(type(d['max_'+resource]) is int and d['max_'+resource]==initial['max_'+resource]
                        and all(integer(d[resource+'_'+edge],0,d['max_'+resource]) for edge in ('before','after')),
                        'native_item_resource_invalid')
            for child_kind,key in (('resource_transaction','resource_event_ids'),('inventory_transaction','inventory_event_ids')):
                require(type(d[key]) is list and d[key]==opened[tid][child_kind], 'item_child_ids_mismatch')
        elif kind=='transaction_end':
            fields(d,{'transaction_id','committed'})
            require(tid!='' and boolean(d['committed']), 'native_transaction_end_invalid')
            tx=opened.pop(tid)
            require(len(tx['item_transaction'])==1 and len(tx['item_effect_result'])<=1,
                    'native_item_summary_missing')
            summary=by_id[tx['item_transaction'][0]]
            require(summary['data']['committed']==d['committed']
                    and summary['sequence']==row['sequence']-1, 'native_transaction_close_mismatch')
            tx['end']=row;closed[tid]=tx;continue
        elif kind=='movement_accepted':
            _movement(d,contract)
            require(tid=='','unexpected_item_movement')
        else:
            raise InvalidEvidence('unsupported_native_event')
        if tid!='':
            require(not opened[tid]['item_transaction'], 'event_after_item_summary')
            opened[tid][kind].append(row['event_id'])
    require(not opened,'native_transaction_unclosed')
    return closed,by_id


def _potion(rows, contract):
    txs,by_id=_transactions(rows,contract);deadline=120000000000
    initial=rows[0]['data']['initial'];terminal=rows[-1]['data']['actor']
    quantity=initial['quantity'];consumed=0;goal=None;used=[]
    for tid,tx in txs.items():
        summary=by_id[tx['item_transaction'][0]];d=summary['data']
        require(d['quantity_before']==quantity,'item_quantity_discontinuity')
        delta=d['quantity_before']-d['quantity_after']
        require(delta in (0,1),'item_quantity_increased')
        inv=[by_id[x] for x in tx['inventory_transaction']]
        require(sum(r['data']['slot_quantity_before']-r['data']['slot_quantity_after'] for r in inv)==delta,
                'item_decrement_mismatch')
        quantity=d['quantity_after']
        effects=[by_id[x] for x in tx['item_effect_result']]
        resources=[by_id[x] for x in tx['resource_transaction']]
        applied=len(effects)==1 and effects[0]['data']['applied'] is True
        if delta:
            require(d['committed'] and len(effects)==1 and len(inv)==1
                    and inv[0]['data']['slot_quantity_before']==1 and inv[0]['data']['slot_quantity_after']==0,
                    'consumption_without_native_effect_result')
            require((applied and len(resources)==1) or (not applied and not resources),
                    'item_resource_coverage_missing')
        # Full-window consumption counts alone cannot satisfy the half-open goal.
        if tx['end']['elapsed_ns']<deadline:consumed+=delta
        if delta and applied and d['alive'] and len(resources)==1:
            resource=resources[0];r=resource['data']
            require(inv[0]['sequence']<resource['sequence']<effects[0]['sequence']<summary['sequence'],
                    'item_effect_order_invalid')
            require(r['mp_before']==d['mp_before'] and r['mp_after']==d['mp_after']
                    and r['hp_before']==d['hp_before'] and r['hp_after']==d['hp_after'],
                    'item_resource_endpoints_mismatch')
            if (r['mp_after']>r['mp_before'] and r['mp_after']*5>=r['max_mp']*4
                    and r['hp_before']>0 and r['hp_after']>0 and tx['end']['elapsed_ns']<deadline):
                require(goal is None,'multiple_potion_goals')
                goal=tx['end']['elapsed_ns']/1000000
                used=[tid,*tx['resource_transaction'],*tx['item_effect_result'],
                      *tx['inventory_transaction'],*tx['item_transaction'],tx['end']['event_id']]
    require(quantity==terminal['quantity'],'terminal_inventory_mismatch')
    require(goal is not None or rows[-1]['elapsed_ns']>=deadline or terminal['alive'] is False,
            'incomplete_failed_window')
    # Terminal MP is a native snapshot, not an attribution of restoration. A
    # successful ratio comes from the linked atomic mutation, not later regen.
    ratio=(by_id[used[1]]['data']['mp_after']/initial['max_mp']) if goal is not None else terminal['mp']/initial['max_mp']
    return {'criterion_met':goal is not None,'completion_ms':goal,
            'alive':True if goal is not None else terminal['alive'],
            'items_consumed':consumed,'mp_fraction':ratio},used


def verify_ledger(raw_bytes, task_contract, expected):
    """Return a sanitized-reason private receipt; never launch or qualify a run.

    `expected` must be supplied from trusted runtime artifacts, not extracted
    from the untrusted ledger. The caller owns ordinary save/restore and early
    terminal receipt publication. Synthetic streams are useful tests only.
    """
    receipt={'schema_version':1,'protocol':VERIFIER_PROTOCOL,'task_protocol':PROTOCOL,
             'task_id':None,'variant':None,'status':'invalid','outcome':None,
             'reason_code':'invalid_contract','evidence':{},'publication_eligible':False,
             'runtime_lifecycle_verified':False}
    try:
        try:contract=validate_contract(task_contract)
        except (ValueError,TypeError):raise InvalidEvidence('invalid_contract') from None
        receipt.update(task_id=contract['task_id'],variant=contract['variant'])
        receipt['evidence']={'contract_sha256':fingerprint(contract),
                            'ledger_sha256':hashlib.sha256(raw_bytes).hexdigest() if type(raw_bytes) is bytes else None,
                            'event_ids':[]}
        rows=_parse(raw_bytes,contract,expected)
        if contract['task_id']=='platforming-v1':raise InvalidEvidence('native_grounded_physics_coverage_unavailable')
        if contract['task_id']=='native-teleport-v1':raise InvalidEvidence('native_teleport_causal_link_unavailable')
        outcome,ids=_potion(rows,contract)
        receipt.update(status='success' if outcome['criterion_met'] else 'gameplay_failure',
                       outcome=outcome,reason_code='criterion_met' if outcome['criterion_met'] else 'criterion_not_met')
        receipt['evidence']['event_ids']=ids
    except InvalidEvidence as exc:
        receipt['reason_code']=str(exc)
    except (TypeError,KeyError,OverflowError,RecursionError):
        receipt['reason_code']='event_schema_mismatch'
    return receipt
