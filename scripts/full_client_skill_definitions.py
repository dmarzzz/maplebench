"""Read bounded skill/item scalars from local NX and matching Cosmic XML.

No bitmap/audio data is exported. No database, game, network or model is used.
PKG4 layout follows NoLifeNx file_impl/node_impl (Copyright 2013 Peter Atashian,
AGPL-3.0-or-later). This report is source parity, never native qualification.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import time
import xml.etree.ElementTree as ET

from full_client_skill_toolkit import toolkit, fingerprint


def need(value, code='invalid_native_definition'):
    if not value:raise ValueError(code)


class NX:
    def __init__(self, path, deadline):
        path=Path(path);need(path.resolve(strict=True)==path,'definition_symlink_refused')
        self.path=path;self.fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW);self.deadline=deadline;self.reads=0
        try:
            self.info=os.fstat(self.fd);need(stat.S_ISREG(self.info.st_mode))
            self.size=self.info.st_size
            magic,self.nodes,self.node_at,self.strings,self.string_at=struct.unpack('<IIQIQ',self.read(0,28))
            need(magic==0x34474b50 and self.node_at+self.nodes*20<=self.size
                 and self.string_at+self.strings*8<=self.size)
        except BaseException:
            os.close(self.fd);raise
    def close(self):os.close(self.fd)
    def read(self,offset,count):
        self.reads+=1
        need(self.reads<=250000 and 0<=offset<=self.size and 0<=count<=4096
             and offset+count<=self.size and time.monotonic()<self.deadline,'definition_read_limit')
        raw=os.pread(self.fd,count,offset);need(len(raw)==count);return raw
    def string(self,index):
        need(index<self.strings)
        pos=struct.unpack('<Q',self.read(self.string_at+index*8,8))[0]
        length=struct.unpack('<H',self.read(pos,2))[0];need(length<=4096)
        return self.read(pos+2,length).decode('utf8')
    def node(self,index):
        need(0<=index<self.nodes)
        return struct.unpack('<IIHH8s',self.read(self.node_at+index*20,20))
    def children(self,index):
        _,start,count,_,_=self.node(index);need(start+count<=self.nodes and count<=10000)
        return {self.string(self.node(i)[0]):i for i in range(start,start+count)}
    def resolve(self,path):
        i=0
        for part in path.split('/'):i=self.children(i)[part]
        return i
    def scalar(self,index):
        _,_,_,kind,raw=self.node(index)
        if kind==1:return struct.unpack('<q',raw)[0]
        if kind==2:
            value=struct.unpack('<d',raw)[0];need(math.isfinite(value));return value
        if kind==3:return self.string(struct.unpack('<I',raw[:4])[0])
        if kind==4:return list(struct.unpack('<ii',raw))
        return None
    def values(self,path):
        return {name:value for name,i in self.children(self.resolve(path)).items()
                if (value:=self.scalar(i)) is not None}
    def identity(self):
        after=os.fstat(self.fd);current=self.path.stat()
        need(all(getattr(self.info,k)==getattr(after,k)==getattr(current,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')),
             'definition_changed_during_read')
    def digest(self):
        need(self.size<=1024*1024*1024,'definition_asset_limit')
        hasher=hashlib.sha256();offset=0
        while offset<self.size:
            need(time.monotonic()<self.deadline,'definition_read_limit')
            raw=os.pread(self.fd,min(1024*1024,self.size-offset),offset)
            need(raw,'definition_changed_during_read');hasher.update(raw);offset+=len(raw)
        self.identity()
        return {'sha256':hasher.hexdigest(),'bytes':self.size}


def file_bytes(path,limit):
    path=Path(path);need(path.resolve(strict=True)==path,'definition_symlink_refused')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as source:
        before=os.fstat(source.fileno());need(stat.S_ISREG(before.st_mode) and before.st_size<=limit)
        raw=source.read(limit+1);after=os.fstat(source.fileno())
        need(len(raw)<=limit and all(getattr(before,k)==getattr(after,k)
            for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')),'definition_changed_during_read')
        return raw


def xml_node(raw,path):
    node=ET.fromstring(raw)
    for part in path.split('/'):
        node=node.find('./imgdir[@name="'+part+'"]');need(node is not None)
    return node


def xml_values(node):
    out={}
    for child in node:
        name=child.get('name');need(name not in out)
        if child.tag in ('int','short','long'):out[name]=int(child.get('value'))
        elif child.tag=='double':out[name]=float(child.get('value'))
        elif child.tag=='string':out[name]=child.get('value')
        elif child.tag=='vector':out[name]=[int(child.get('x')),int(child.get('y'))]
    return out


def inspect(class_id,assets,wz,*,seconds=90):
    need(type(seconds) is int and 1<=seconds<=120,'definition_deadline_invalid')
    deadline=time.monotonic()+seconds;policy=toolkit(class_id);assets=Path(assets);wz=Path(wz)
    nx=NX(assets/'Skill.nx',deadline);items=None
    result={'schema_version':1,'status':'nx_xml_scalars_verified_not_live_qualified',
        'toolkit_sha256':fingerprint(policy),'skills':{},'items':{},'source_files':{},
        'api_calls':0,'runtime_mutations':0}
    cache={}
    def xml(path):
        need(time.monotonic()<deadline,'definition_read_limit')
        if path not in cache:
            raw=file_bytes(wz/path,16*1024**2);cache[path]=raw
            result['source_files'][path]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
        return cache[path]
    requested={s['skill_id']:s['level'] for s in policy['skills']+policy['passives']}
    pending=list(requested)
    try:
        while pending:
            sid=pending.pop();level=requested[sid];need(len(requested)<=100,'definition_skill_limit')
            path=f'{sid//10000}.img/skill/{sid}';raw=xml(f'Skill.wz/{sid//10000}.img.xml')
            root=xml_node(raw,f'skill/{sid}');levels=root.find('./imgdir[@name="level"]');need(levels is not None)
            values=nx.values(path+f'/level/{level}');other=xml_values(xml_node(raw,f'skill/{sid}/level/{level}'))
            # NX may carry additional string labels; all numeric source effects
            # and requirements must agree in both directions.
            numeric=lambda v:{k:x for k,x in v.items() if type(x) in (int,float,list)}
            need(numeric(values)==numeric(other),'skill_nx_xml_mismatch')
            reqnode=root.find('./imgdir[@name="req"]');requirements=xml_values(reqnode) if reqnode is not None else {}
            nxreq=nx.values(path+'/req') if 'req' in nx.children(nx.resolve(path)) else {}
            need(requirements==nxreq,'skill_requirement_nx_xml_mismatch')
            result['skills'][str(sid)]={'level':level,'max_level':max(int(x.get('name')) for x in levels),
                'level_values':values,'requirements':requirements,'nx_xml_scalar_match':True}
            for key,minimum in requirements.items():
                need(key.isdecimal() and type(minimum) is int and 0<minimum<=255,'invalid_skill_requirement')
                required=int(key)
                if requested.get(required,0)<minimum:requested[required]=minimum;pending.append(required)
        result['source_files']['Skill.nx']=nx.digest();nx.close();nx=None
        items=NX(assets/'Item.nx',deadline)
        ids=[policy['resources']['potion']['item_id']]
        if policy['resources']['ammunition']:ids.append(policy['resources']['ammunition']['item_id'])
        for iid in ids:
            stem=f'{iid//10000:04d}';path=f'Consume/{stem}.img/0{iid}'
            raw=xml(f'Item.wz/Consume/{stem}.img.xml')
            values=items.values(path+'/info');other=xml_values(xml_node(raw,f'0{iid}/info'))
            need({k:v for k,v in values.items() if type(v) in (int,float,list)}==
                 {k:v for k,v in other.items() if type(v) in (int,float,list)},'item_nx_xml_mismatch')
            entry={'info':values,'nx_xml_scalar_match':True}
            # Consumable restoration is in spec, not the item icon/info node.
            if iid==policy['resources']['potion']['item_id']:
                spec=items.values(path+'/spec');other_spec=xml_values(xml_node(raw,f'0{iid}/spec'))
                need(spec==other_spec,'potion_effect_nx_xml_mismatch');entry['spec']=spec
            result['items'][str(iid)]=entry
        result['source_files']['Item.nx']=items.digest()
    finally:
        if nx is not None:nx.close()
        if items is not None:items.close()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--class-id',required=True);parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--wz',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        report=inspect(args.class_id,args.assets,args.wz)
        raw=(json.dumps(report,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
    except (ValueError,OSError,KeyError,TypeError,ET.ParseError,struct.error):
        print(json.dumps({'status':'skill_definition_inspection_failed'}));return 1
    print(json.dumps({'status':report['status'],'sha256':hashlib.sha256(raw).hexdigest()}));return 0


if __name__=='__main__':raise SystemExit(main())
