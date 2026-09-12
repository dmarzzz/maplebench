"""Apply a declared skill toolkit to an offline SQL baseline, without a DB.

Input must already be the correct class with ordinary compatible equipment.
Credentials/account data remain byte-identical in private SQL. Output is a new
private fixture candidate; this transform cannot issue a live acceptance receipt.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from full_client_skill_toolkit import toolkit, validate_toolkit, fingerprint, SLOTS, profile

TOKEN=re.compile(r"NULL|-?[0-9]+|'(?:\\.|[^'\\])*'")
MAX_SQL=64*1024*1024


def need(value,code):
    if not value:raise ValueError(code)


def table(text,name):
    ddl=re.findall(r'^CREATE TABLE `'+name+r'` \(\n(.*?)^\) ENGINE=',text,re.M|re.S)
    inserts=list(re.finditer(r'^INSERT INTO `'+name+r'` VALUES (.*);$',text,re.M))
    need(len(ddl)==len(inserts)==1,'one_table_insert_required')
    cols=re.findall(r'^  `([A-Za-z0-9_]+)` ',ddl[0],re.M)
    need(cols and len(cols)==len(set(cols)),'unique_table_columns_required')
    value=inserts[0][1];rows=[];at=0
    while at<len(value):
        need(value[at]=='(','row_open_required');at+=1;tokens=[]
        while True:
            match=TOKEN.match(value,at);need(match is not None,'unsupported_sql_literal')
            tokens.append(match[0]);at=match.end()
            need(at<len(value) and value[at] in ',)','literal_delimiter_required')
            delimiter=value[at];at+=1
            if delimiter==')':break
        need(len(tokens)==len(cols),'table_columns_changed');rows.append(dict(zip(cols,tokens)))
        need(len(rows)<=10000,'fixture_row_limit')
        if at<len(value):need(value[at]==',','row_delimiter_required');at+=1
    need(rows,'nonempty_fixture_table_required')
    return cols,rows,inserts[0].span(1)


def replace(text,name,rows):
    cols,_,(start,end)=table(text,name)
    need(rows and all(set(row)==set(cols) for row in rows),'fixture_columns_changed')
    values=','.join('('+','.join(str(row[key]) for key in cols)+')' for row in rows)
    return text[:start]+values+text[end:]


def learned_skills(policy,definitions):
    policy=validate_toolkit(policy)
    need(definitions.get('status')=='nx_xml_scalars_verified_not_live_qualified'
         and definitions.get('toolkit_sha256')==fingerprint(policy),'verified_toolkit_definitions_required')
    selected={s['skill_id']:s['level'] for s in policy['skills']+policy['passives']}
    pending=list(selected)
    while pending:
        sid=pending.pop();level=selected[sid]
        need(len(selected)<=100,'fixture_skill_limit')
        definition=definitions.get('skills',{}).get(str(sid),{})
        need(definition.get('nx_xml_scalar_match') is True and definition.get('level')==level
             and type(definition.get('max_level')) is int and level<=definition['max_level'],
             'skill_definition_not_verified')
        for key,minimum in definition.get('requirements',{}).items():
            need(key.isdecimal() and type(minimum) is int and 0<minimum<=255,'invalid_skill_requirement')
            required=int(key)
            if selected.get(required,0)<minimum:selected[required]=minimum;pending.append(required)
    return selected


def resource_stacks(policy,definitions):
    """Finite physical inventory; no inflated stacks or runtime refill."""
    resources=policy['resources'];item=resources['potion'];items=definitions.get('items',{})
    info=items.get(str(item['item_id']),{})
    need(info.get('nx_xml_scalar_match') is True,'potion_definition_not_verified')
    stats=info.get('info',{});effect=info.get('spec',{})
    need(effect.get('hpR')==100 and effect.get('mpR')==100,'power_elixir_effect_not_verified')
    maximum=stats.get('slotMax',100)
    need(type(maximum) is int and 1<=maximum<=32767,'invalid_item_stack_limit')
    stacks=[];remaining=item['quantity']
    while remaining:
        count=min(remaining,maximum);stacks.append((item['item_id'],count));remaining-=count
    ammo=resources['ammunition']
    if ammo:
        entry=items.get(str(ammo['item_id']),{})
        need(entry.get('nx_xml_scalar_match') is True,'ammunition_definition_not_verified')
        maximum=entry.get('info',{}).get('slotMax',100)
        need(type(maximum) is int and ammo['quantity_per_stack']<=maximum,'ammunition_stack_too_large')
        stacks += [(ammo['item_id'],ammo['quantity_per_stack'])]*ammo['stacks']
    need(len(stacks)<=24,'fixture_use_inventory_capacity_exceeded')
    return stacks


def transform(raw,policy,definitions):
    policy=validate_toolkit(policy);need(len(raw)<=MAX_SQL,'fixture_sql_limit')
    learned=learned_skills(policy,definitions);stacks=resource_stacks(policy,definitions)
    text=raw.decode('utf8');names=('accounts','characters','skills','keymap','inventoryitems')
    tables={name:table(text,name) for name in names}
    accounts=tables['accounts'][1];characters=copy.deepcopy(tables['characters'][1])
    need(len(accounts)==len(characters)==1 and accounts[0]['loggedin']=='0','single_offline_fixture_required')
    character=characters[0];cid=character['id'];aid=accounts[0]['id']
    need(cid.isdecimal() and aid.isdecimal() and character['accountid']==aid
         and int(character['job'])==policy['job'] and int(character['level'])==policy['level'],
         'correct_class_baseline_required')
    for name in ('skills','keymap','inventoryitems'):
        need(all(row['characterid']==cid for row in tables[name][1]),'other_character_rows_refused')
    # The supplied class baseline must contain one equipped ordinary weapon of
    # its class. Its detailed item/stats/requirements stay a separate baseline
    # qualification gate; this transform does not substitute invented equipment.
    weapons=[r for r in tables['inventoryitems'][1] if r['inventorytype']=='-1' and r['position']=='-11']
    weapon_prefix={'hero':140,'bowmaster':145,'ice_lightning_arch_mage':138,'night_lord':147}[policy['class_id']]
    need(len(weapons)==1 and int(weapons[0]['itemid'])//10000==weapon_prefix,'class_weapon_required')
    resources=policy['resources']
    character.update(hp=str(resources['hp']),maxhp=str(resources['max_hp']),mp=str(resources['mp']),maxmp=str(resources['max_mp']))
    multiplier=1
    if policy['class_id']=='ice_lightning_arch_mage':
        amplification=definitions['skills']['2210001']['level_values'].get('x')
        need(type(amplification) is int and 100<=amplification<=500,'amplification_cost_not_verified')
        multiplier=amplification/100
    for skill in policy['skills']:
        cost=definitions['skills'][str(skill['skill_id'])]['level_values'].get('mpCon',0)
        need(type(cost) is int and 0<=cost*multiplier<=resources['max_mp'],'skill_exceeds_fixture_mp_capacity')
    skillcols=tables['skills'][0];oldskills=tables['skills'][1]
    need(set(skillcols)=={'id','skillid','characterid','skilllevel','masterlevel','expiration'},'skill_schema_changed')
    start=max(int(row['id']) for row in oldskills)+1
    skills=[dict(zip(skillcols,[str({'id':start+i,'skillid':sid,'characterid':int(cid),
        'skilllevel':level,'masterlevel':level if sid//10000 in (112,312,222,412) else 0,
        'expiration':-1}[column]) for column in skillcols])) for i,(sid,level) in enumerate(sorted(learned.items()))]
    oldkeys=tables['keymap'][1];keycols=tables['keymap'][0]
    need(set(keycols)=={'id','characterid','key','type','action'},'keymap_schema_changed')
    replace_keys={29,57,85,16,17}|{v[1] for v in SLOTS.values()}
    keys=[copy.deepcopy(row) for row in oldkeys if int(row['key']) not in replace_keys]
    start=max(int(row['id']) for row in oldkeys)+1
    bindings=[(29,5,52),(57,5,53),(85,5,52),(16,2,resources['potion']['item_id']),(17,2,resources['potion']['item_id'])]
    bindings += [(s['key'],1,s['skill_id']) for s in policy['skills']]
    for i,(key,kind,action) in enumerate(bindings):
        keys.append({'id':str(start+i),'characterid':cid,'key':str(key),'type':str(kind),'action':str(action)})
    need(len({row['key'] for row in keys})==len(keys),'duplicate_fixture_key')
    olditems=tables['inventoryitems'][1]
    use=[row for row in olditems if row['inventorytype']=='2']
    need(use,'consumable_template_required')
    items=[copy.deepcopy(row) for row in olditems if row['inventorytype']!='2']
    start=max(int(row['inventoryitemid']) for row in olditems)+1
    for i,(item_id,quantity) in enumerate(stacks):
        row=copy.deepcopy(use[0]);row.update(inventoryitemid=str(start+i),itemid=str(item_id),
            position=str(i+1),quantity=str(quantity))
        # New ordinary consumables must not inherit expiry, ownership or flags.
        for key,value in {'owner':"''",'flag':'0','expiration':'-1','petid':'-1','giftFrom':"''"}.items():
            if key in row:row[key]=value
        items.append(row)
    updates={'characters':characters,'skills':skills,'keymap':keys,'inventoryitems':items}
    for name,rows in updates.items():text=replace(text,name,rows)
    # Compare every byte outside the four explicitly rewritten INSERT spans.
    before=raw.decode('utf8');after=text
    for name in updates:
        for which in ('before','after'):
            value=before if which=='before' else after
            _,_,(a,b)=table(value,name);value=value[:a]+'(0)'+value[b:]
            if which=='before':before=value
            else:after=value
    need(before==after,'unrelated_fixture_sql_changed')
    expected={'schema_version':1,'status':'offline_candidate_not_live_qualified',
        'toolkit_sha256':fingerprint(policy),'character_id':int(cid),'account_id':int(aid),
        'job':policy['job'],'level':policy['level'],'hp':resources['hp'],'mp':resources['mp'],
        'max_hp':resources['max_hp'],'max_mp':resources['max_mp'],
        'skills':[[sid,level] for sid,level in sorted(learned.items())],
        'keymap':sorted([[int(row[k]) for k in ('key','type','action')] for row in keys]),
        'use_inventory':[[i+1,item_id,quantity] for i,(item_id,quantity) in enumerate(stacks)],
        'equipment_replaced':False,'api_calls':0,'database_connections':0,'runtime_mutations':0}
    return text.encode(),expected


def read(path,digest,limit):
    need(re.fullmatch('[a-f0-9]{64}',digest) is not None,'input_hash_required')
    path=Path(path);need(path.is_absolute() and path.resolve(strict=True)==path,'canonical_input_required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as source:
        info=os.fstat(source.fileno());need(stat.S_ISREG(info.st_mode) and not info.st_mode&0o077,'private_input_required')
        raw=source.read(limit+1);need(len(raw)<=limit and hashlib.sha256(raw).hexdigest()==digest,'input_hash_changed')
        return raw


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','source-sha256','definitions','definitions-sha256','class-id','output-directory'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    try:
        source=read(args.source,args.source_sha256,MAX_SQL)
        definitions=read(args.definitions,args.definitions_sha256,1024*1024)
        policy=toolkit(args.class_id);sql,expected=transform(source,policy,json.loads(definitions))
        out=Path(args.output_directory)
        need(out.is_absolute() and out.parent.resolve(strict=True)==out.parent and not os.path.lexists(out),'new_private_output_required')
        out.mkdir(mode=0o700);refs={}
        artifacts={'database.sql':sql,'expected-fixture.json':expected,'skill-toolkit.json':policy,'profile.json':profile(policy)}
        for name,value in artifacts.items():
            raw=value if type(value) is bytes else (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
            fd=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as file:file.write(raw);file.flush();os.fsync(file.fileno())
            refs[name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
        directory=os.open(out,os.O_RDONLY);os.fsync(directory);os.close(directory)
    except (ValueError,OSError,KeyError,TypeError,UnicodeError):
        print(json.dumps({'status':'offline_toolkit_preparation_failed'}));return 1
    print(json.dumps({'status':expected['status'],'artifacts':refs,'runtime_mutations':0}));return 0


if __name__=='__main__':raise SystemExit(main())
