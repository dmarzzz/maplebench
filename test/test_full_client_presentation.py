"""Presentation refresh must preserve the immutable scientific evidence bytes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_client_presentation import refresh
from full_client_publication import ASSETS, MAX_ADAPTIVE_VIDEO, XP_PROTOCOL, digest, encoded, file_inventory, verify_package


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.package=self.root/'source';self.package.mkdir()
        site=self.package/'site';site.mkdir();(site/'recordings').mkdir()
        for name in ASSETS:(site/name).write_text('Old UI')
        (site/'results.json').write_text('{"persisted_xp":-10,"unchanged":true}')
        (site/'recording-manifest.json').write_text('{}');(site/'vercel.json').write_text('{}')
        (site/'recordings'/('a'*32+'.webm')).write_bytes(b'synthetic video bytes')
        content={'schema_version':1,'protocol':'legacy-full-client-v1','target_path':'/cohorts/'+'b'*16+'/',
                 'files':file_inventory(site)}
        self.sha=digest(encoded(content))
        (self.package/'package-manifest.json').write_bytes(encoded({'schema_version':1,'content_sha256':self.sha,'content':content}))
        self.output=self.root/'output';self.output.mkdir();self.ui=self.root/'ui';self.ui.mkdir()
        for name in ASSETS:(self.ui/name).write_text('New UI')
    def test_refresh_keeps_every_result_and_video_byte_and_original_package(self):
        result=refresh(self.package,self.sha,self.output,ui_root=self.ui)
        manifest=verify_package(Path(result['package']),result['content_sha256'])
        original=verify_package(self.package,self.sha)
        self.assertEqual(manifest['content']['presentation_parent_sha256'],self.sha)
        for name,ref in original['content']['files'].items():
            if name not in ASSETS:self.assertEqual(manifest['content']['files'][name],ref)
        self.assertNotEqual(result['content_sha256'],self.sha)
        self.assertEqual(refresh(self.package,self.sha,self.output,ui_root=self.ui),result)
        self.assertFalse((Path(result['package'])/'publication-intent.json').exists())
    def test_changed_source_video_is_refused_before_refresh(self):
        (self.package/'site'/'recordings'/('a'*32+'.webm')).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'package_content_changed'):
            refresh(self.package,self.sha,self.output,ui_root=self.ui)
        self.assertEqual(list(self.output.iterdir()),[])
    def test_output_inside_source_is_refused(self):
        with self.assertRaisesRegex(ValueError,'presentation_paths_overlap'):
            refresh(self.package,self.sha,self.package,ui_root=self.ui)
    def test_xp_package_preserves_its_existing_larger_video_limit(self):
        site=self.package/'site';video=site/'recordings'/('a'*32+'.webm')
        with video.open('r+b') as stream:stream.truncate(33*1024**2)
        manifest=json.loads((self.package/'package-manifest.json').read_bytes())
        content=manifest['content'];content['protocol']=XP_PROTOCOL
        content['files']=file_inventory(site,maximum_video=MAX_ADAPTIVE_VIDEO)
        sha=digest(encoded(content));manifest['content_sha256']=sha
        (self.package/'package-manifest.json').write_bytes(encoded(manifest))
        result=refresh(self.package,sha,self.output,ui_root=self.ui)
        actual=verify_package(Path(result['package']),result['content_sha256'])
        self.assertEqual(actual['content']['files']['recordings/'+video.name],content['files']['recordings/'+video.name])


if __name__=='__main__':unittest.main()
