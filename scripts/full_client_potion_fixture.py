"""Create a separate, restricted S3 offline candidate; never import or run it.

The caller supplies frozen input hashes from its private execution authority.
The canonical full-toolkit fixture validator is deliberately unchanged.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from full_client_toolkit_fixture import MAX_SQL, table, replace, read, need

ID='full-client-potion-fixture-v1'
KEYS=['LEFT','RIGHT','UP','DOWN','JUMP','HP_POTION','MP_POTION']
PERCENT={1:10,2:15,3:20}


def digest(raw):return hashlib.sha256(raw).hexdigest()


def geometry(raw,map_id):
    need(type(map_id) is int and map_id>=0 and len(raw)<=8*1024*1024,'bounded_map_required')
    need(b'<!DOCTYPE' not in raw and b'<!ENTITY' not in raw,'map_entities_refused')
    root=ET.fromstring(raw)
    need(root.tag=='imgdir' and root.get('name')==f'{map_id:09}.img','map_identity_changed')
    def fields(node):return {} if node is None else {x.get('name'):x.get('value') for x in node if x.tag!='imgdir'}
    info=fields(root.find("imgdir[@name='info']"))
    need(all(info.get(k) in (None,'','0') for k in ('onUserEnter','onFirstUserEnter','link','timeLimit')),'map_script_or_timer_refused')
    need(info.get('forcedReturn') in (None,'999999999') and int(info.get('fieldType','0'))==0
         and not int(info.get('fieldLimit','0'))&0x1000 and int(info.get('swim','0'))==0,'unsafe_map_type')
    life=root.find("imgdir[@name='life']")
    need(life is None or all(fields(n).get('type')!='m' for n in life),'monster_map_refused')
    footholds=[];fh=root.find("imgdir[@name='foothold']")
    need(fh is not None,'foothold_geometry_required')
    for n in fh.iter('imgdir'):
        f=fields(n)
        if all(k in f for k in ('x1','y1','x2','y2')):
            footholds.append({'id':int(n.get('name')),**{k:int(f[k]) for k in ('x1','y1','x2','y2')}})
    portals=[];portal=root.find("imgdir[@name='portal']")
    if portal is not None:
        for n in portal:
            p=fields(n)
            if p.get('pt')=='0':portals.append({'id':int(n.get('name')),'x':int(p['x']),'y':int(p['y'])})
    # Portal order is frozen before gameplay; do not move the start after failure.
    for p in sorted(portals,key=lambda p:p['id']):
        # Check the actual nearest intersecting nonvertical foothold below spawn.
        below=[]
        for f in footholds:
            x1,x2,y1,y2=(f[k] for k in ('x1','x2','y1','y2'))
            if x1==x2 or not min(x1,x2)<=p['x']<=max(x1,x2):continue
            numerator=y1*(x2-x1)+(y2-y1)*(p['x']-x1);denominator=x2-x1
            from fractions import Fraction
            y=Fraction(numerator,denominator)
            if y>=p['y']:below.append((y,f['id'],f))
        if not below:continue
        y,_,f=min(below,key=lambda x:(x[0],x[1]))
        if f['y1']!=f['y2'] or not min(f['x1'],f['x2'])+16<=p['x']<=max(f['x1'],f['x2'])-16:continue
        return {'map_id':map_id,'spawn_portal':p,'ground_foothold':f,'expected_landing':{'x':p['x'],'y':int(y)},
                'qualification':'offline_geometry_only_not_native_landing'}
    raise ValueError('safe_spawn_ground_required')


def transform(raw,definitions_raw,map_raw,binding,variant,empty=False):
    need(type(variant) is int and variant in PERCENT and type(empty) is bool,'variant_required')
    need(binding.get('id')==ID and binding.get('task_id')=='potion-use-v1','potion_binding_required')
    for field,value in [('parent_sha256',raw),('definitions_sha256',definitions_raw),('map_xml_sha256',map_raw)]:
        need(re.fullmatch('[a-f0-9]{64}',binding.get(field,'')) is not None and digest(value)==binding[field],'pinned_input_changed')
    need(len(raw)<=MAX_SQL and len(definitions_raw)<=1024*1024,'fixture_input_limit')
    terrain=geometry(map_raw,binding['map_id'])
    need(terrain==binding.get('geometry'),'frozen_geometry_changed')
    definitions=json.loads(definitions_raw);potion=definitions.get('items',{}).get('2000005',{})
    need(definitions.get('status')=='nx_xml_scalars_verified_not_live_qualified'
         and potion.get('nx_xml_scalar_match') is True and potion.get('spec',{}).get('hpR')==100
         and potion.get('spec',{}).get('mpR')==100,'power_elixir_native_parity_required')
    text=raw.decode('utf8');names=('accounts','characters','keymap','inventoryitems')
    tables={name:table(text,name) for name in names};accounts=tables['accounts'][1]
    chars=copy.deepcopy(tables['characters'][1])
    need(len(accounts)==len(chars)==1 and accounts[0]['loggedin']=='0','single_offline_actor_required')
    c=chars[0];cid=c['id'];aid=accounts[0]['id']
    need(cid.isdecimal() and aid.isdecimal() and c['accountid']==aid and c['job']=='222' and c['level']=='180','mage_180_required')
    need(all(r['characterid']==cid for name in ('keymap','inventoryitems') for r in tables[name][1]),'other_actor_rows_refused')
    need(not re.search(r'^INSERT INTO `(?:cooldowns|playerbuffs|buffs)` ',text,re.M),'persisted_effects_refused')
    maxhp,maxmp=int(c['maxhp']),int(c['maxmp'])
    need(1<=maxhp<=30000 and 1<=maxmp<=30000 and maxmp*PERCENT[variant]%100==0,'exact_native_base_resource_fraction_required')
    c.update(hp=str(maxhp),mp=str(maxmp*PERCENT[variant]//100),map=str(binding['map_id']),spawnpoint=str(terrain['spawn_portal']['id']))
    olditems=tables['inventoryitems'][1]
    weapons=[r for r in olditems if r['inventorytype']=='-1' and r['position']=='-11']
    need(len(weapons)==1 and int(weapons[0]['itemid'])//10000==138,'ordinary_mage_weapon_required')
    templates=[r for r in olditems if r['inventorytype']=='2' and r['itemid']=='2000005']
    need(templates,'native_potion_template_required')
    items=[copy.deepcopy(r) for r in olditems if r['inventorytype'] not in ('2','4')]
    if not empty:
        item=copy.deepcopy(templates[0]);item.update(inventoryitemid=str(max(int(r['inventoryitemid']) for r in olditems)+1),position='1',quantity='1')
        for k,v in {'owner':"''",'flag':'0','expiration':'-1','petid':'-1','giftFrom':"''"}.items():
            if k in item:item[k]=v
        items.append(item)
    need(set(tables['keymap'][0])=={'id','characterid','key','type','action'},'keymap_schema_changed')
    start=max(int(r['id']) for r in tables['keymap'][1])+1
    keys=[{'id':str(start+i),'characterid':cid,'key':str(key),'type':str(kind),'action':str(action)}
          for i,(key,kind,action) in enumerate([(57,5,53),(16,2,2000005),(17,2,2000005)])]
    updates={'characters':chars,'keymap':keys,'inventoryitems':items}
    for name,rows in updates.items():text=replace(text,name,rows)
    before,after=raw.decode('utf8'),text
    for name in updates:
        _,_,(a,b)=table(before,name);before=before[:a]+'(0)'+before[b:]
        _,_,(a,b)=table(after,name);after=after[:a]+'(0)'+after[b:]
    need(before==after,'unrelated_sql_changed')
    expected={'id':ID,'task_id':'potion-use-v1','variant':variant,'empty_inventory_negative':empty,
        'status':'offline_candidate_not_live_qualified','binding':binding,'character_id':int(cid),'account_id':int(aid),
        'job':222,'level':180,'stored_hp':maxhp,'stored_max_hp':maxhp,'stored_mp':int(c['mp']),'stored_max_mp':maxmp,
        'mp_percent':PERCENT[variant],'use_inventory':[] if empty else [[1,2000005,1]],'etc_inventory':[],
        'allowed_keys':KEYS,'keymap':[[57,5,53],[16,2,2000005],[17,2,2000005]],
        'movement_binding':'native_fixed_arrow_keys_plus_keymap_jump','automatic_potion_bindings':[],
        'active_buffs_claim':False,'required_live_checks':['fresh_process_no_inherited_buffs','actual_no_active_buffs',
            'actual_maxima_match_stored','actual_initial_resource_fraction','actual_spawn_ground_and_safe_scene'],
        'api_calls':0,'database_connections':0,'runtime_mutations':0}
    return text.encode(),expected


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('source','source-sha256','definitions','definitions-sha256','map-xml','map-xml-sha256','binding','binding-sha256','output-directory'):ap.add_argument('--'+n,required=True)
    ap.add_argument('--variant',type=int,choices=(1,2,3),required=True);ap.add_argument('--empty-inventory-negative',action='store_true');a=ap.parse_args()
    try:
        raw=read(a.source,a.source_sha256,MAX_SQL);definitions=read(a.definitions,a.definitions_sha256,1024*1024)
        terrain=read(a.map_xml,a.map_xml_sha256,8*1024*1024);binding=json.loads(read(a.binding,a.binding_sha256,1024*1024))
        sql,expected=transform(raw,definitions,terrain,binding,a.variant,a.empty_inventory_negative)
        out=Path(a.output_directory);need(out.is_absolute() and out.parent.resolve(strict=True)==out.parent and not os.path.lexists(out),'new_private_output_required')
        out.mkdir(mode=0o700)
        refs={}
        for name,value in {'database.sql':sql,'expected-fixture.json':(json.dumps(expected,sort_keys=True,separators=(',',':'))+'\n').encode()}.items():
            fd=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as f:f.write(value);f.flush();os.fsync(f.fileno())
            refs[name]={'sha256':digest(value),'bytes':len(value)}
        fd=os.open(out,os.O_RDONLY);os.fsync(fd);os.close(fd)
        print(json.dumps({'status':'offline_candidate_not_live_qualified','artifacts':refs}));return 0
    except (ValueError,OSError,KeyError,TypeError,UnicodeError,ET.ParseError):
        print(json.dumps({'status':'offline_potion_fixture_failed'}));return 1

if __name__=='__main__':raise SystemExit(main())
