"""Validate the bounded Hero-180 v1 control-qualification plan.

This is an offline plan validator. It does not run inputs, inspect private
evidence, or turn historical summaries into new release acceptance.
"""
import json
import os
import re
import sys

import full_client_hero_toolkit as hero_toolkit

PROTOCOL = 'hero-180-v1-control-qualification'
PACK_ID = 'hero-180-map-240040511-v1'
CONTROLS = ('LEFT','RIGHT','UP','DOWN','JUMP','ATTACK','HP_POTION','MP_POTION',
            'PRIMARY_SKILL','SECONDARY_SKILL','BUFF_1','BUFF_2','SKILL_5',
            'SKILL_6','SKILL_7','SKILL_8','SKILL_9','SKILL_10','SKILL_11',
            'SKILL_12','SKILL_13','SKILL_14','SKILL_15','SKILL_16','SKILL_17')
HISTORICALLY_ACCEPTED = frozenset(('JUMP','PRIMARY_SKILL'))
TOP_FIELDS = {'schema_version','id','fixture','status_meanings','release_status',
              'toolkit','controls','historical_sources','native_release_result'}
CONTROL_FIELDS = {'name','mapping','historical_status','release_status','check'}
FIXTURE = {'profile_id':'hero-180-expanded-v1','class_name':'Hero','level':180,
           'expected_map_id':240040511,'protocol':'full-client-adaptive-pilot-v1'}


class QualificationError(ValueError):
    pass


def require(value, code):
    if not value:
        raise QualificationError(code)


def _parse(raw):
    def pairs(items):
        value={}
        for key,item in items:
            require(key not in value,'duplicate_qualification_key')
            value[key]=item
        return value
    def constant(_):
        raise QualificationError('nonfinite_qualification_value')
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
    except QualificationError:raise
    except (ValueError,TypeError,UnicodeError,RecursionError) as error:
        raise QualificationError('invalid_skill_qualification_json') from error


def load(path):
    with open(path,'rb') as handle:
        raw=handle.read(1024*1024+1)
    require(0<len(raw)<=1024*1024,'invalid_skill_qualification_json')
    return validate(_parse(raw))


def validate(value):
    """Return the unchanged plan after strict schema and claim checks."""
    require(isinstance(value,dict) and set(value)==TOP_FIELDS,
            'invalid_skill_qualification')
    require(type(value['schema_version']) is int and value['schema_version']==1
            and value['id']==PROTOCOL and value['fixture']==FIXTURE
            and value['release_status']=='planned'
            and value['native_release_result'] is None,
            'invalid_skill_qualification')
    kit=hero_toolkit.toolkit()
    require(value['toolkit']=={'policy_id':kit['id'],'invocable_skill_count':len(kit['skills']),
            'passive_count':len(kit['passives']),'unsupported_count':len(kit['unsupported'])},
            'invalid_skill_toolkit_summary')
    meanings=value['status_meanings']
    require(isinstance(meanings,dict)
            and set(meanings)=={'native_accepted','not_established','planned'}
            and all(isinstance(item,str) and item for item in meanings.values()),
            'invalid_skill_status_meanings')
    controls=value['controls']
    require(isinstance(controls,list) and len(controls)==len(CONTROLS),
            'invalid_skill_controls')
    for expected,row in zip(CONTROLS,controls):
        require(isinstance(row,dict) and set(row)==CONTROL_FIELDS
                and row['name']==expected and isinstance(row['mapping'],str) and row['mapping']
                and isinstance(row['check'],str) and row['check']
                and row['release_status']=='planned'
                and row['historical_status']==('native_accepted'
                    if expected in HISTORICALLY_ACCEPTED else 'not_established'),
                'invalid_skill_control_claim')
    sources=value['historical_sources']
    require(isinstance(sources,list) and len(sources)==2,'invalid_skill_sources')
    for source in sources:
        require(isinstance(source,dict) and set(source)=={'path','supports'}
                and isinstance(source['path'],str)
                and re.fullmatch(r'docs/[A-Z0-9_]+\.md',source['path'])
                and isinstance(source['supports'],str) and source['supports'],
                'invalid_skill_sources')
    return value


def main(argv=None):
    argv=sys.argv[1:] if argv is None else argv
    path=(argv[0] if len(argv)==1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'knowledge',
        PACK_ID,'skill-qualification.json'))
    if len(argv)>1:
        sys.stderr.write('usage: full_client_skill_qualification.py [plan.json]\n')
        return 2
    try:
        load(path)
    except QualificationError as error:
        sys.stderr.write('invalid: %s\n' % error)
        return 1
    except (OSError,json.JSONDecodeError):
        sys.stderr.write('unreadable qualification plan\n')
        return 2
    sys.stdout.write('ok: planned; native release evidence pending\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
