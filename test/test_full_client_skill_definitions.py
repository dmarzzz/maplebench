"""Tiny synthetic PKG4/XML parity fixtures; no copyrighted assets are used."""
import json
import struct
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from full_client_skill_definitions import inspect,NX
from full_client_skill_toolkit import toolkit
from test_full_client_skill_toolkit import definitions


def nx_bytes(tree):
    nodes=[('',tree)];encoded=[];strings=[]
    def string(value):
        if value not in strings:strings.append(value)
        return strings.index(value)
    at=0
    while at<len(nodes):
        name,value=nodes[at];start=count=0;kind=0;raw=b'\0'*8
        if isinstance(value,dict):
            start=len(nodes);count=len(value);nodes.extend(value.items())
        elif type(value) is int:kind=1;raw=struct.pack('<q',value)
        elif type(value) is str:kind=3;raw=struct.pack('<I',string(value))+b'\0'*4
        elif type(value) is list:kind=4;raw=struct.pack('<ii',*value)
        encoded.append(struct.pack('<IIHH8s',string(name),start,count,kind,raw));at+=1
    string_at=28+20*len(nodes);data_at=string_at+8*len(strings);positions=[];data=b''
    for text in strings:
        positions.append(data_at+len(data));raw=text.encode();data+=struct.pack('<H',len(raw))+raw
    return struct.pack('<IIQIQ',0x34474b50,len(nodes),28,len(strings),string_at)+b''.join(encoded)+b''.join(struct.pack('<Q',p) for p in positions)+data


def xml_tree(name,value):
    node=ET.Element('imgdir',name=name)
    for key,item in value.items():
        if isinstance(item,dict):node.append(xml_tree(key,item))
        elif type(item) is int:ET.SubElement(node,'int',name=key,value=str(item))
        elif type(item) is str:ET.SubElement(node,'string',name=key,value=item)
        elif type(item) is list:ET.SubElement(node,'vector',name=key,x=str(item[0]),y=str(item[1]))
    return node


class DefinitionTests(unittest.TestCase):
    def fixture(self,root,cls='night_lord'):
        root=root.resolve()
        p=toolkit(cls);d=definitions(p);skilltree={}
        for sid,definition in d['skills'].items():
            skilltree.setdefault(f'{int(sid)//10000}.img',{'skill':{}})['skill'][sid]={
                'level':{str(definition['level']):definition['level_values']},'req':definition['requirements']}
        items={}
        for iid,definition in d['items'].items():
            items.setdefault(f'{int(iid)//10000:04d}.img',{})['0'+iid]={'info':definition['info']}
            if 'spec' in definition:items[f'{int(iid)//10000:04d}.img']['0'+iid]['spec']=definition['spec']
        assets=root/'assets';assets.mkdir();wz=root/'wz';(wz/'Skill.wz').mkdir(parents=True);(wz/'Item.wz/Consume').mkdir(parents=True)
        (assets/'Skill.nx').write_bytes(nx_bytes(skilltree));(assets/'Item.nx').write_bytes(nx_bytes({'Consume':items}))
        for stem,tree in skilltree.items():(wz/'Skill.wz'/f'{stem}.xml').write_bytes(ET.tostring(xml_tree(stem,tree)))
        for stem,tree in items.items():(wz/'Item.wz/Consume'/f'{stem}.xml').write_bytes(ET.tostring(xml_tree(stem,tree)))
        return assets,wz

    def test_real_decoder_checks_all_declared_skills_items_and_source_hashes(self):
        for cls in ('hero','bowmaster','ice_lightning_arch_mage','night_lord'):
            with tempfile.TemporaryDirectory() as directory:
                assets,wz=self.fixture(Path(directory),cls);report=inspect(cls,assets,wz)
                self.assertEqual(report['status'],'nx_xml_scalars_verified_not_live_qualified')
                for skill in toolkit(cls)['skills']+toolkit(cls)['passives']:
                    self.assertEqual(report['skills'][str(skill['skill_id'])]['level'],skill['level'])
                self.assertIn('Skill.nx',report['source_files']);self.assertIn('Item.nx',report['source_files'])
                self.assertEqual(report['api_calls'],0);self.assertEqual(report['runtime_mutations'],0)

    def test_changed_numeric_effect_or_requirement_is_rejected(self):
        for field in ('effect','requirement'):
            with tempfile.TemporaryDirectory() as directory:
                assets,wz=self.fixture(Path(directory));path=wz/'Skill.wz/412.img.xml';tree=ET.parse(path)
                node=tree.getroot().find('./imgdir[@name="skill"]/imgdir[@name="4121007"]')
                if field=='effect':node.find('./imgdir[@name="level"]/imgdir/int').set('value','999')
                else:ET.SubElement(node.find('./imgdir[@name="req"]'),'int',name='4000000',value='4')
                tree.write(path)
                with self.assertRaisesRegex(ValueError,'nx_xml_mismatch'):inspect('night_lord',assets,wz)

    def test_corrupt_node_extent_and_expired_deadline_refuse_read(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory).resolve()/'broken.nx';raw=bytearray(nx_bytes({'level':{'mpCon':1}}));struct.pack_into('<I',raw,4,10000000);path.write_bytes(raw)
            with self.assertRaises(ValueError):NX(path,time.monotonic()+2)
            path.write_bytes(nx_bytes({'level':{'mpCon':1}}))
            with self.assertRaisesRegex(ValueError,'definition_read_limit'):NX(path,time.monotonic()-1)


if __name__=='__main__':unittest.main()
