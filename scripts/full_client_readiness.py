"""Frozen pre-API observation requirements; these are not authoritative scoring."""
import hashlib
import json
import math


class ReadinessError(ValueError):
    pass


def validate_policy(value, expected_map_id=None):
    fixed = {'schema_version': 1, 'min_monsters': 1, 'min_samples': 3,
             'min_span_ms': 1000, 'timeout_ms': 10000}
    if (not isinstance(value, dict) or set(value) != set(fixed) | {'expected_map_id'}
            or any(type(value.get(key)) is not int or value[key] != expected for key, expected in fixed.items())
            or type(value.get('expected_map_id')) is not int or not 0 <= value['expected_map_id'] <= 2**31-1
            or expected_map_id is not None and (type(expected_map_id) is not int
                                               or value['expected_map_id'] != expected_map_id)):
        raise ReadinessError('invalid_readiness_policy')
    return dict(value)


def observation_matches(value, policy):
    if not isinstance(value, dict) or value.get('ready') is not True:
        return False
    character, monsters = value.get('character'), value.get('monsters')
    if not isinstance(character, dict) or not isinstance(monsters, list):
        return False
    ages = (value.get('ageMs'), value.get('renderAgeMs'))
    return (all(type(age) in (int, float) and 0 <= age < 1500 and math.isfinite(age) for age in ages)
            and type(character.get('mapId')) is int and character['mapId'] == policy['expected_map_id']
            and character.get('alive') is True and type(character.get('hp')) in (int, float)
            and 0 < character['hp'] <= 2**53-1 and math.isfinite(character['hp'])
            and len(monsters) >= policy['min_monsters'])


def observation_sha256(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()
