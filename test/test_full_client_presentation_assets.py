"""Original art admission and actual package paths; fixture videos are synthetic."""
from html.parser import HTMLParser
import copy
import json
from pathlib import Path
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'test'))
import test_full_client_presentation as legacy
import test_full_client_catalog as catalog_fixture
import full_client_publication as publication
from full_client_presentation import refresh
from full_client_presentation_assets import FILES, POLICY
from full_client_vercel import checked_payload, PUBLIC_NAME, MAX_PAYLOAD


class PresentationArtTests(unittest.TestCase):
    def setUp(self):
        self.f = legacy.PresentationTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.ui = ROOT / 'ui/full-client-dashboard'

    def refreshed(self):
        value = refresh(self.f.package, self.f.sha, self.f.output, ui_root=self.ui)
        path = Path(value['package'])
        return path, publication.verify_package(path, value['content_sha256'])

    def test_refresh_adds_only_pinned_art_and_preserves_all_original_evidence_bytes(self):
        old = publication.verify_package(self.f.package, self.f.sha)
        path, manifest = self.refreshed()
        self.assertEqual(manifest['content']['presentation_assets'], POLICY)
        self.assertEqual(manifest['content']['presentation_parent_sha256'], self.f.sha)
        self.assertEqual({name: manifest['content']['files'][name] for name in FILES}, FILES)
        for name, ref in old['content']['files'].items():
            if name not in publication.ASSETS:
                self.assertEqual(manifest['content']['files'][name], ref)
        self.assertEqual(publication.verify_package(self.f.package, self.f.sha), old)
        self.assertEqual(set(manifest['content']['files']) - set(old['content']['files']), set(FILES))
        self.assertEqual(MAX_PAYLOAD, 512 * 1024**2)
        self.assertFalse((path / 'publication-intent.json').exists())

    def test_old_packages_remain_valid_and_cannot_silently_admit_an_art_directory(self):
        self.assertNotIn('presentation_assets', publication.verify_package(self.f.package, self.f.sha)['content'])
        (self.f.package / 'site/illustrations').mkdir()
        with self.assertRaisesRegex(ValueError, 'unexpected_public_file'):
            publication.verify_package(self.f.package, self.f.sha)

    def test_rehashed_replacement_png_still_fails_the_exact_original_art_registry(self):
        path, manifest = self.refreshed(); name = next(iter(FILES))
        forged = b'\x89PNG\r\n\x1a\nprivate replacement'
        (path / 'site' / name).write_bytes(forged)
        manifest['content']['files'][name] = {'bytes': len(forged), 'sha256': publication.digest(forged)}
        manifest['content_sha256'] = publication.digest(publication.encoded(manifest['content']))
        (path / 'package-manifest.json').write_bytes(publication.encoded(manifest))
        with self.assertRaisesRegex(ValueError, 'presentation_art_binding'):
            publication.verify_package(path, manifest['content_sha256'])

    def test_missing_unknown_policy_and_symlink_are_not_presentation_assets(self):
        path, original = self.refreshed()
        for policy in ('any-images', None, True, {'accepted': True}):
            manifest = copy.deepcopy(original); manifest['content']['presentation_assets'] = policy
            manifest['content_sha256'] = publication.digest(publication.encoded(manifest['content']))
            (path / 'package-manifest.json').write_bytes(publication.encoded(manifest))
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, 'presentation_art_policy'):
                publication.verify_package(path, manifest['content_sha256'])
        (path / 'package-manifest.json').write_bytes(publication.encoded(original))
        name = next(iter(FILES)); (path / 'site' / name).unlink()
        with self.assertRaisesRegex(ValueError, 'unexpected_public_file'):
            publication.verify_package(path, original['content_sha256'])
        (path / 'site' / name).symlink_to(self.ui / name)
        with self.assertRaises(ValueError):
            publication.verify_package(path, original['content_sha256'])

    def test_only_the_named_art_paths_are_in_the_public_allowlist(self):
        for name in FILES:
            for prefix in ('', 'latest/', 'cohorts/' + 'a'*16 + '/'):
                self.assertTrue(PUBLIC_NAME.fullmatch(prefix + name))
        for name in ('illustrations/private.png', 'illustrations/README.md', 'fonts/private.ttf',
                     '../illustrations/maple-leaf.png', 'previews/'+'a'*32+'/illustrations/maple-leaf.png'):
            self.assertFalse(PUBLIC_NAME.fullmatch(name))

    def test_real_projector_catalog_resolves_art_at_root_and_nested_cohorts(self):
        c = catalog_fixture.CatalogTests(); c.setUp(); self.addCleanup(c.tearDown)
        packages = [c.package(c.fixture(name, seed), count=4)
                    for name, seed in [('hero', 4000), ('bowmaster', 5000)]]
        value, snapshot = c.compose(packages)
        site = Path(value['site']); inventory = json.loads(Path(value['inventory']).read_bytes())
        primary = publication.verify_package(Path(packages[-1]['package']), packages[-1]['content_sha256'])
        checked_payload(site, Path(value['inventory']), value['inventory_sha256'], primary)
        self.assertEqual(len(snapshot['attempts']), 8)
        class Resources(HTMLParser):
            def __init__(self): super().__init__(); self.paths = []
            def handle_starttag(self, tag, attrs):
                a = dict(attrs); candidate = a.get('src') if tag in ('img', 'script') else a.get('href') if tag == 'link' else None
                if candidate and candidate.startswith('./'): self.paths.append(candidate[2:])
        for base in [site] + [site / publication.verify_package(Path(p['package']), p['content_sha256'])['content']['target_path'].strip('/') for p in packages]:
            parser = Resources(); parser.feed((base / 'index.html').read_text())
            self.assertTrue(parser.paths)
            for name in parser.paths:
                self.assertTrue((base / name).is_file(), (base, name))
                self.assertIn((base / name).relative_to(site).as_posix(), inventory['files'])
        # Even an operator-rehashed supplemental root asset must match the
        # reviewed original bytes; the primary nested package is unchanged.
        name = next(iter(FILES)); (site / name).write_bytes(b'other png')
        inventory['files'][name] = {'bytes': 9, 'sha256': publication.digest(b'other png')}
        changed = c.root / 'forged-inventory.json'; changed.write_bytes(publication.encoded(inventory))
        with self.assertRaisesRegex(ValueError, 'presentation_art_binding'):
            checked_payload(site, changed, publication.digest(changed.read_bytes()), primary)


if __name__ == '__main__': unittest.main()
