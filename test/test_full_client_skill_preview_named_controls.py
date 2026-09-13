"""Versioned prompt repair; synthetic SDK calls only, no API or game actions."""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).resolve().parent)]
import full_client_skill_preview as preview
from full_client_skill_toolkit import allowed_keys, prompt_reference, sdk_scenario, toolkit
from maple_agent import validate_rpc


# Captured from dfa66fb before the v3 change, using baseline 'b' * 64.
LEGACY_HASHES = {
    'hero': (
        ('e585c8d2ba21a30aa02ed114fae854846df723aad13f4cc5520076ae6718bd5c',
         '52b2137e459f562b331dce86299d57dca27808806848d31d8e1345f15c180b11'),
        ('95c71dec10287105a626797824b59519534b8e8e129f879ce8374e3d81416649',
         'd72bf9e4c26fea176aae7bb899dd6b46cf3afa57b2c8f56b83b45ad0d711cd58'),
        'beb2adf7964cf27c42f5b59b069a317d96730d7e3e67f0ed8b8a7a31d24bf9d4'),
    'bowmaster': (
        ('f0d2716867ff88643b60e693bd553080cfc73dc1d1634bb7efef77e4ed64d2a6',
         '7f91dafcb2f2424a2c9acdfeb6dde9c5b2853fa444a1371bfff2bea6f4400acc'),
        ('d57011827a36ee587c3fcbe7ee8ec6dbdef118a3fcb8863131e80e4ecd36629d',
         '383ac0b2713257353a7070b73b306f2ffde06979e1d62038b17bcd48cd3fcaa4'),
        '96c165d43b8fe53a9564da79f008b8e66ea3831bef6341a0a1253d90f5a4cb76'),
    'ice_lightning_arch_mage': (
        ('1826d375e4e970163fd7155b3db2934c423ae22cd6d0189e9aff8e1a2f416c56',
         'acd078ece25c3fed2821a17dc52b6cf65c6bb0cf35646184bc418a60f2e67c2a'),
        ('aa278ed37b78a088bc1dff85afe5c86212e0fb63ac33d9a635434502299526b6',
         '661135fe6b18bd67aad84e3b9049d06204c28642d3d4cd482c26803c6b72f0ec'),
        '46c8c613fc9224134ef70d284b94b2b0b130d571edcffc191a5f1334a61c1456'),
    'night_lord': (
        ('400283e413761beb30849ec8109b66553fcbaf7eb5f68accfc746e989f941a42',
         '8e36f0142e7a64ff810f31d77fed11bbfc677452f3086877bb15dd3b06857286'),
        ('6d02ad72a9e386472f5c97eab527465cceea03087d78caf5b041f6b3cf60095b',
         '55230396765a78095c3a3e5f079714410931f21661ce65c399691eab4e73ebee'),
        'ab078e14f4366209f39bf67cf5ed609351fca04695e3b426329ed4305a11bda5'),
}


class NamedControlPreviewTests(unittest.TestCase):
    def test_v1_v2_contracts_prompts_and_default_toolkit_references_keep_exact_bytes(self):
        for cls, (v1, v2, reference_sha) in LEGACY_HASHES.items():
            for version, (contract_sha, prompt_sha) in zip(
                    (preview.LEGACY_PROTOCOL, preview.ENCODED_PROTOCOL), (v1, v2)):
                with self.subTest(cls=cls, version=version):
                    protocol = preview.contract(cls, 'b' * 64, protocol=version)
                    self.assertEqual(preview.fingerprint(protocol), contract_sha)
                    self.assertEqual(hashlib.sha256(preview.prompt(protocol).encode()).hexdigest(), prompt_sha)
            self.assertEqual(hashlib.sha256(prompt_reference(toolkit(cls)).encode()).hexdigest(), reference_sha)

    def test_v3_changes_only_protocol_identity_and_prompt_not_existing_caps_or_toolkit(self):
        self.assertEqual(preview.PROTOCOL, 'full-client-skill-preview-v3')
        for cls in LEGACY_HASHES:
            old = preview.contract(cls, 'b' * 64, protocol=preview.ENCODED_PROTOCOL)
            new = preview.contract(cls, 'b' * 64)
            self.assertEqual(new, old | {'id': preview.PROTOCOL})
            self.assertEqual(preview.validate_protocol(new), new)
            self.assertNotEqual(preview.fingerprint(old), preview.fingerprint(new))
            self.assertNotEqual(preview.prompt(old), preview.prompt(new))

    def test_v3_vocabulary_exactly_matches_class_authority_without_physical_letter_hints(self):
        for cls in LEGACY_HASHES:
            protocol = preview.contract(cls, 'b' * 64)
            text = preview.prompt(protocol)
            listed = json.loads(re.search(r'Allowed sdk\.pressKeys strings \(complete list\): (\[.*\])\.\n', text)[1])
            self.assertEqual(len(listed), len(set(listed)))
            self.assertEqual(set(listed), allowed_keys(protocol['skill_toolkit']))
            self.assertIn('Invalid keys stop the program.', text)
            self.assertIn('not a successful cast', text)
            for skill in protocol['skill_toolkit']['skills']:
                self.assertIn(f"{skill['slot']}: {skill['name']}", text)
                self.assertNotIn(f"({skill['code'][3:]})", text)
                self.assertNotIn(skill['code'], text)
            if cls == 'night_lord':
                self.assertNotIn('SKILL_9', listed)
                self.assertNotIn('SKILL_10', listed)

    @unittest.skipUnless(shutil.which('node'), 'Node required for actual JavaScript examples')
    def test_prompt_examples_execute_and_every_emitted_call_passes_real_sdk_validation(self):
        for cls in LEGACY_HASHES:
            protocol = preview.contract(cls, 'b' * 64)
            examples = '\n'.join(re.findall(r'^  ((?:await |const )[^\n]+)', preview.prompt(protocol), re.MULTILINE))
            script = """const calls=[];
const sdk=Object.fromEntries(['observe','wait','pressKeys'].map(method=>[method,async(...args)=>{
  calls.push({type:'rpc',id:calls.length+1,method,args}); return {character:{x:0,y:0}};
}]));
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('sdk',process.argv[1])(sdk).then(()=>process.stdout.write(JSON.stringify(calls)))
  .catch(error=>{process.stderr.write(String(error));process.exitCode=1;});
"""
            completed = subprocess.run([shutil.which('node'), '--max-old-space-size=64', '-e', script, examples],
                                       capture_output=True, text=True, timeout=5)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            calls = json.loads(completed.stdout)
            scenario = {'adapter': 'full-client', **sdk_scenario(protocol)}
            for call in calls: validate_rpc(call, scenario)
            actions = [call['args'][0] for call in calls if call['method'] == 'pressKeys']
            self.assertEqual(actions[:2], [['BUFF_1'], ['PRIMARY_SKILL']])
            self.assertEqual(len(actions), 3 if cls == 'ice_lightning_arch_mage' else 2)
            if cls == 'ice_lightning_arch_mage':
                self.assertEqual(actions[-1], ['RIGHT', 'SECONDARY_SKILL'])

    def test_physical_letters_skill_names_and_unmapped_keys_stay_rejected_in_every_preview(self):
        for version in preview.PROTOCOLS:
            for cls in LEGACY_HASHES:
                protocol = preview.contract(cls, 'b' * 64, protocol=version)
                scenario = {'adapter': 'full-client', **sdk_scenario(protocol)}
                skills = protocol['skill_toolkit']['skills']
                invalid = ['D', 'KeyD', 'Magic Guard', '2001002', 'UNMAPPED_SKILL']
                invalid += [skill['code'][3:] for skill in skills]
                for key in invalid:
                    with self.subTest(version=version, cls=cls, key=key), self.assertRaisesRegex(ValueError, 'Invalid keyboard input'):
                        validate_rpc({'type': 'rpc', 'id': 1, 'method': 'pressKeys', 'args': [[key], 500]}, scenario)
                self.assertEqual(validate_rpc({'type': 'rpc', 'id': 1, 'method': 'pressKeys',
                    'args': [['BUFF_1'], 500]}, scenario)[1]['keys'], ['BUFF_1'])

    def test_v3_upload_uses_existing_encoded_bundle_and_rejects_missing_contract(self):
        from test_full_client_skill_preview_encoded import PreviewEncodedTests
        from full_client_capture import capture_receipt
        from full_client_publish import verify_capture_bundle
        harness = PreviewEncodedTests(); harness.setUp()
        try:
            harness.protocol = preview.contract('ice_lightning_arch_mage', 'b' * 64)
            harness.owner.update(protocol=preview.PROTOCOL, previewProtocol=harness.protocol)
            harness.bridge.run = copy.deepcopy(harness.owner)
            (harness.folder / 'request.json').write_text(json.dumps(harness.owner))
            recording = harness.attach()
            measured = verify_capture_bundle(harness.manifest(recording), harness.folder)
            self.assertEqual(measured['encoder_receipt'], harness.fixture.value['encoder_receipt'])
            with self.assertRaisesRegex(ValueError, 'invalid_skill_preview_protocol'):
                capture_receipt(harness.fixture.value, harness.owner | {'previewProtocol': None},
                                harness.fixture.anchor, harness.fixture.clock, harness.fixture.terminal)
        finally:
            harness.doCleanups()

    def test_v2_publication_rechecks_original_prompt_and_rejects_v3_substitution(self):
        from test_full_client_skill_preview_publication import SkillPreviewPublicationTests
        harness = SkillPreviewPublicationTests(); harness.setUp()
        try:
            protocol = preview.contract('ice_lightning_arch_mage', 'b' * 64, protocol=preview.ENCODED_PROTOCOL)
            result = harness.values['result']
            result.update(protocol=protocol['id'], previewProtocol=protocol)
            result['controller'].update(protocol=protocol['id'], previewProtocol=protocol)
            request = harness.values['api_request']; request['instructions'] = preview.prompt(protocol)
            request_bound = (len(request['instructions'].encode()) + len(request['input'].encode())
                             + len(json.dumps(request['text']['format']['schema']).encode()) + 1024 + 3000)
            result['controller']['apiTokenUpperBound'] = request_bound
            harness.save('result', result); harness.save('api_request', request)
            row = harness.row()
            self.assertEqual(row['protocol_id'], preview.ENCODED_PROTOCOL)
            self.assertIsNone(row['score'])
            request['instructions'] = preview.prompt(preview.contract('ice_lightning_arch_mage', 'b' * 64))
            harness.save('api_request', request)
            with self.assertRaisesRegex(ValueError, 'preview_prompt_mismatch'): harness.row()
        finally:
            harness.tearDown()


if __name__ == '__main__': unittest.main()
