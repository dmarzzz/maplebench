"""Optional, exact-byte original presentation art; no runtime game assets.

The v1 registry pins only reviewed generated illustrations. Historical packages
omit the policy and retain their original three-file UI contract and limits.
"""
import re
from full_client_dashboard import ProjectionError

POLICY = 'maplebench-original-illustrations-v1'
FILES = {
    "illustrations/blue-snail.png": {
        "bytes": 1192824,
        "sha256": "25ec3e160638c39cf31d897ee6e6ff33bac21e76a2ab886a54b54e5962940c3a"
    },
    "illustrations/henesys-world.png": {
        "bytes": 2324284,
        "sha256": "f5fd688227a4d51bbcced67b8d5481cad5652b83d55a4a336fd344288595d405"
    },
    "illustrations/little-stump.png": {
        "bytes": 966916,
        "sha256": "ea2ce432e38744bf972b72a226b4d490dce001e56e52fad8186eae24424f79e2"
    },
    "illustrations/maple-companions.png": {
        "bytes": 1211023,
        "sha256": "539e44bb27c873a8c79ec2a71199c11f0d7387530d6f6fe0402b240d4cd231ec"
    },
    "illustrations/maple-leaf.png": {
        "bytes": 949135,
        "sha256": "5409009b676c78d2ae21be0dc0882f892a1efc1561e5164b73daef54a4a7bdee"
    },
    "illustrations/meso-pouch.png": {
        "bytes": 1039692,
        "sha256": "20fcfdd0055f3fbb397c7f3afdb5c4056ee6a1ffb38fd0d6443e4b349f506104"
    },
    "illustrations/potions.png": {
        "bytes": 981189,
        "sha256": "3cb1fd4c36c7375dd3eee5f541cf58e8796db7ba34544e7bb089e6d13f775296"
    },
    "illustrations/return-scroll.png": {
        "bytes": 757249,
        "sha256": "6a33f2c617f6c3b05462ac2f7cbfa112f11eb669ecfea5c5b2171bd04a629326"
    },
    "illustrations/ribbon-pig.png": {
        "bytes": 1009928,
        "sha256": "e8a716957d2b4bbb3b98e6044f5727d5caae7905bcd51148e9f8c99854059f47"
    },
    "illustrations/skill-book.png": {
        "bytes": 1039384,
        "sha256": "6cc59c123e878edbabac3361f1885e9010b45929cb255951589f14c5d3609fa0"
    }
}
PUBLIC_ART = r'illustrations/(?:blue-snail|henesys-world|little-stump|maple-companions|maple-leaf|meso-pouch|potions|return-scroll|ribbon-pig|skill-book)\.png'


def require(value, code):
    if not value: raise ProjectionError(code)


def illustration_files(policy=None):
    if policy is None: return {}
    require(type(policy) is str and policy == POLICY, 'presentation_art_policy')
    return {name: dict(ref) for name, ref in FILES.items()}


def policy_for_ui(ui):
    # Merely adding a directory cannot admit arbitrary files: each writer
    # verifies every original byte against the registry before packaging it.
    return POLICY if (ui / 'illustrations').exists() or (ui / 'illustrations').is_symlink() else None


def validate_package_art(files, policy=None):
    expected = illustration_files(policy)
    actual = {name: ref for name, ref in files.items() if name.startswith('illustrations/')}
    require(actual == expected, 'presentation_art_binding')


def validate_payload_art(files):
    mounted = {}
    for name, ref in files.items():
        match = re.fullmatch(r'((?:latest/|cohorts/[a-f0-9]{16}/)?)(illustrations/[^/]+)', name)
        if match: mounted.setdefault(match[1], {})[match[2]] = ref
    for group in mounted.values():
        require(group == FILES, 'presentation_art_binding')
