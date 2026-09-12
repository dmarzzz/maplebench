"""Real public composition/hashing; synthetic projected records and media only."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import full_client_catalog as catalog
import full_client_publication as publication
import full_client_vercel as driver
import test_full_client_catalog as catalogs
import test_full_client_xp_cohort as native


class MixedHorizonPublicationTests(unittest.TestCase):
    def setUp(self):
        self.c=catalogs.CatalogTests();self.c.setUp();self.addCleanup(self.c.tearDown)
        self.n=native.LongNativeCohortTests();self.n.setUp();self.addCleanup(self.n.doCleanups)
        prepared=self.n.prepare()
        self.long={k:prepared[k] for k in ('package','content_sha256')}
        # Issue a new explicitly synthetic public fixture at the >96 MiB
        # boundary. This tests byte policy, never claims a decoded native run.
        package=Path(self.long['package']);site=package/'site'
        video=next((site/'recordings').iterdir())
        with video.open('r+b') as stream:stream.truncate(97*1024**2)
        fingerprint=publication.stable_fingerprint(video,publication.MAX_LONG_VIDEO)
        results=json.loads((site/'results.json').read_bytes())
        results['attempts'][0]['recording']['sha256']=fingerprint['sha256']
        (site/'results.json').write_bytes(publication.encoded(results))
        (site/'recording-manifest.json').write_bytes(publication.encoded({'schema_version':1,
            'entries':[{'path':video.name,**fingerprint}]}))
        manifest=json.loads((package/'package-manifest.json').read_bytes())
        manifest['content']['files']=publication.file_inventory(site,maximum_video=publication.MAX_LONG_VIDEO)
        manifest['content_sha256']=publication.digest(publication.encoded(manifest['content']))
        (package/'package-manifest.json').write_bytes(publication.encoded(manifest))
        self.long['content_sha256']=manifest['content_sha256'];self.long_manifest=manifest
        self.short=self.c.package(self.c.fixture('bowmaster',20))
        self.short_manifest=publication.verify_package(self.short['package'],self.short['content_sha256'])

    def compose(self,primary):
        request=self.c.request([self.long,self.short]);request['primary_content_sha256']=primary['content_sha256']
        return catalog.compose(request,self.c.out)

    def check(self,result,inventory,primary):
        path=self.c.root/'modified-inventory.json';path.write_bytes(publication.encoded(inventory))
        return driver.checked_payload(Path(result['site']),path,publication.digest(path.read_bytes()),primary)

    def test_real_compose_long_secondary_short_primary_then_reverse(self):
        result=self.compose(self.short)
        inventory=json.loads(Path(result['inventory']).read_bytes())
        self.assertEqual(len(inventory['cohort_manifests']),2)
        self.assertFalse(any('package' in item for item in inventory['cohort_manifests']))
        self.check(result,inventory,self.short_manifest)
        other=self.compose(self.long)
        self.check(other,json.loads(Path(other['inventory']).read_bytes()),self.long_manifest)
        self.assertEqual(result['catalog_sha256'],other['catalog_sha256'])
        prefix=self.long_manifest['content']['target_path'].lstrip('/')
        name=next(n for n in self.long_manifest['content']['files'] if n.endswith('.webm'))
        self.assertEqual(publication.stable_fingerprint(Path(result['site'])/prefix/name,
            publication.MAX_LONG_VIDEO),self.long_manifest['content']['files'][name])
        self.assertEqual(sum(ref['bytes'] for ref in inventory['files'].values())<driver.MAX_PAYLOAD,True)

    def test_missing_supplemental_policy_keeps_old_short_limit(self):
        result=self.compose(self.short);inventory=json.loads(Path(result['inventory']).read_bytes())
        del inventory['cohort_manifests']
        with self.assertRaisesRegex(ValueError,'public_payload_file_limit'):
            self.check(result,inventory,self.short_manifest)

    def test_forged_supplemental_manifest_cannot_grant_a_long_policy(self):
        result=self.compose(self.long);original=json.loads(Path(result['inventory']).read_bytes())
        for rehash in (False,True):
            inventory=copy.deepcopy(original)
            item=next(m for m in inventory['cohort_manifests'] if m['content_sha256']==self.short['content_sha256'])
            item['content'].update(protocol=publication.XP_PROTOCOL,horizon_seconds=1800)
            if rehash:item['content_sha256']=publication.digest(publication.encoded(item['content']))
            with self.subTest(rehash=rehash),self.assertRaises(ValueError):
                self.check(result,inventory,self.long_manifest)

    def test_supplemental_file_mapping_and_mount_are_exact(self):
        result=self.compose(self.short);original=json.loads(Path(result['inventory']).read_bytes())
        for field,value in (('target_path','/cohorts/'+'f'*16+'/'),('files',{})):
            inventory=copy.deepcopy(original);item=inventory['cohort_manifests'][0]
            item['content'][field]=value
            item['content_sha256']=publication.digest(publication.encoded(item['content']))
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.check(result,inventory,self.short_manifest)


if __name__=='__main__':unittest.main()
