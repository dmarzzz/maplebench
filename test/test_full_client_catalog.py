"""Compose real public-projector fixtures; synthetic videos, no deployment/API."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import subprocess
import unittest
from unittest.mock import patch

import test_full_client_adaptive_publication as adaptive_fixture
import test_full_client_publication as legacy_fixture
import full_client_catalog as catalog
import full_client_publication as publication
from full_client_research import summarize
from full_client_vercel import checked_payload


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.out=self.root/'catalogs';self.out.mkdir();self.fixtures=[]
    def tearDown(self):
        for fixture in self.fixtures:fixture.tearDown()
        self.temp.cleanup()
    def fixture(self,class_id='hero',seed=10):
        f=adaptive_fixture.AdaptivePublicationTests();f.setUp();self.fixtures.append(f)
        f.ids=[format(seed+i,'032x') for i in range(4)]
        f.profile['class_id']=class_id
        profile=f.scenario['adaptive_protocol']['profile']
        profile.update(id=class_id.replace('_','-')+'-180',class_name=catalog.CLASSES[class_id])
        f.scenario_path.write_text(json.dumps(f.scenario,sort_keys=True))
        sha=publication.digest(f.scenario_path.read_bytes());f.plan['fixtures'][0]['scenario']['sha256']=sha
        for i,entry in enumerate(f.plan['entries']):
            entry['attempt_id']=f.ids[i];entry['spec']['scenario_fingerprint']=sha
            entry['spec_sha256']=publication.digest(publication.encoded(entry['spec']))
        f.path.write_bytes(publication.encoded(f.plan));f.plan_sha=publication.digest(f.path.read_bytes())
        return f
    def package(self,f,count=1):
        for i in range(count):
            if not (f.attempts/f.ids[i]).exists():f.attempt(i,xp=(-50,0,100,9000)[i])
        value,_=f.prepare()
        return {'package':value['package'],'content_sha256':value['content_sha256']}
    def request(self,packages,archive=None):
        return {'schema_version':1,'cohorts':packages,'primary_content_sha256':packages[-1]['content_sha256'],'archive':archive}
    def compose(self,packages,archive=None):
        value=catalog.compose(self.request(packages,archive),self.out)
        return value,json.loads((Path(value['site'])/'results.json').read_text())
    def mutate(self,package,change):
        source=Path(package['package']);target=self.root/('mutated-'+str(len(list(self.root.iterdir()))))
        shutil.copytree(source,target);site=target/'site';change(site)
        manifest=json.loads((target/'package-manifest.json').read_text())
        manifest['content']['files']=publication.file_inventory(site,maximum_video=publication.MAX_ADAPTIVE_VIDEO)
        manifest['content_sha256']=publication.digest(publication.encoded(manifest['content']))
        (target/'package-manifest.json').write_bytes(publication.encoded(manifest))
        return {'package':str(target),'content_sha256':manifest['content_sha256']}
    def archive(self):
        f=legacy_fixture.PublicationTests();f.setUp();self.fixtures.append(f)
        f.attempt(0,xp=100);p=f.prepare();site=self.root/'legacy-site';shutil.copytree(p['site'],site)
        (site/'README.md').write_text('Explicit synthetic public archive.\n')
        (site/'latest').mkdir()
        for name in ('index.html','dashboard.js','style.css','results.json'):
            shutil.copyfile(site/name,site/'latest'/name)
        files={p.relative_to(site).as_posix():publication.stable_fingerprint(p,publication.MAX_ADAPTIVE_VIDEO)
               for p in site.rglob('*') if p.is_file()}
        inventory=self.root/'archive-inventory.json';inventory.write_bytes(publication.encoded({'files':files}))
        return {'site':str(site),'inventory':str(inventory),'inventory_sha256':publication.digest(inventory.read_bytes())}

    def test_three_classes_keep_all_twelve_planned_rows_and_exact_nested_packages(self):
        packages=[self.package(self.fixture(name,seed)) for name,seed in
                  (('hero',10),('bowmaster',20),('ice_lightning_arch_mage',30))]
        value,snapshot=self.compose(packages)
        self.assertEqual(len(snapshot['attempts']),12);self.assertEqual(snapshot['catalog']['planned'],12)
        self.assertEqual(snapshot['catalog']['verified'],3);self.assertEqual(snapshot['catalog']['complete_cohorts'],0)
        self.assertEqual(len(snapshot['research_matrix']['columns']),3)
        self.assertEqual({c['class_id'] for c in snapshot['research_matrix']['columns']},set(catalog.CLASSES))
        for row in snapshot['research_matrix']['models']:
            self.assertEqual([c['planned'] for c in row['cells']],[1,1,1])
        for p in packages:
            manifest=publication.verify_package(Path(p['package']),p['content_sha256'])
            checked_payload(Path(value['site']),Path(value['inventory']),value['inventory_sha256'],manifest)
            prefix=manifest['content']['target_path'].lstrip('/')
            for name,expected in manifest['content']['files'].items():
                self.assertEqual(publication.stable_fingerprint(Path(value['site'])/prefix/name,publication.MAX_ADAPTIVE_VIDEO),expected)
        recorded=[r for r in snapshot['attempts'] if r['recording']]
        self.assertTrue(all(r['recording']['url'].startswith('./cohorts/') for r in recorded))
        self.assertEqual([r['persisted_xp'] for r in recorded],[-50,-50,-50])
        self.assertFalse(value['deployment_performed']);self.assertEqual(value['api_requests'],0)
        again,_=self.compose(packages);self.assertEqual(again['catalog_sha256'],value['catalog_sha256'])

    def test_each_new_run_updates_root_without_hiding_unstarted_models(self):
        f=self.fixture();first=self.package(f);one,a=self.compose([first])
        f.attempt(1,xp=0);second=self.package(f);two,b=self.compose([second])
        self.assertNotEqual(one['catalog_sha256'],two['catalog_sha256'])
        self.assertEqual(b['catalog']['verified'],2);self.assertEqual(len(b['attempts']),4)
        self.assertEqual([r['status'] for r in b['attempts']],['completed','completed','not_started','not_started'])
        self.assertEqual(b['featured_run_id'],f.ids[1]);self.assertEqual(b['attempts'][1]['persisted_xp'],0)
        self.assertEqual(a['catalog']['verified'],1)

    def test_failed_and_unknown_attempts_stay_in_denominators(self):
        f=self.fixture();f.attempt(0)
        folder=f.attempts/f.ids[1];folder.mkdir()
        (folder/'journal.json').write_text(json.dumps({'attempt_id':f.ids[1],'status':'failed','phase':'run_controller',
            'request':f.plan['entries'][1]['spec'],'adapter_fingerprint':'9'*64,
            'events':[{'kind':'created','at_ms':900000}],'api_outcome':'uncertain'}))
        (f.attempts/f.ids[2]).mkdir();(f.attempts/f.ids[2]/'journal.json').write_text('{}')
        _,snapshot=self.compose([self.package(f)])
        cells=[m['cells'][0] for m in snapshot['research_matrix']['models']]
        self.assertEqual([c['planned'] for c in cells],[1,1,1,1])
        self.assertEqual([c['valid'] for c in cells],[1,0,0,0])
        self.assertEqual(cells[1]['failed'],1);self.assertEqual(cells[2]['unknown'],1)
        self.assertEqual(cells[3]['not_started'],1)

    def test_archive_is_preserved_then_removed_only_after_four_verified_recordings(self):
        archive=self.archive();f=self.fixture();partial=self.package(f,count=3)
        first,snapshot=self.compose([partial],archive)
        self.assertFalse(first['archive_retired']);self.assertEqual(snapshot['catalog']['archive_state'],'retained')
        old_files=json.loads(Path(archive['inventory']).read_text())['files']
        for name,expected in old_files.items():
            if name.startswith(('recordings/','latest/')) or name=='README.md':
                self.assertEqual(publication.stable_fingerprint(Path(first['site'])/name,publication.MAX_ADAPTIVE_VIDEO),expected)
        complete=self.package(f,count=4);second,snapshot=self.compose([complete],archive)
        self.assertTrue(second['archive_retired']);self.assertEqual(len(snapshot['attempts']),4)
        self.assertFalse((Path(second['site'])/'latest').exists())
        self.assertFalse((Path(second['site'])/'recordings').exists())
        self.assertTrue(Path(archive['site']).is_dir())
        for name,expected in old_files.items():
            self.assertEqual(publication.stable_fingerprint(Path(archive['site'])/name,publication.MAX_ADAPTIVE_VIDEO),expected)

    def test_missing_fourth_video_cannot_retire_archive_even_with_four_scores(self):
        f=self.fixture();p=self.package(f,count=4)
        (f.attempts/f.ids[3]/'video.webm').write_bytes(b'corrupt')
        p=self.package(f,count=4);value,snapshot=self.compose([p],self.archive())
        self.assertFalse(value['archive_retired']);self.assertEqual(snapshot['catalog']['verified'],4)
        self.assertEqual(snapshot['catalog']['complete_cohorts'],0)

    def test_duplicate_attempts_classes_or_cohort_prefixes_are_refused(self):
        hero=self.package(self.fixture('hero',10));bow=self.package(self.fixture('bowmaster',10))
        with self.assertRaisesRegex(ValueError,'catalog_duplicate_attempt'):self.compose([hero,bow])
        other=self.package(self.fixture('hero',20))
        with self.assertRaisesRegex(ValueError,'catalog_duplicate_class'):self.compose([hero,other])
        with self.assertRaisesRegex(ValueError,'catalog_duplicate_class'):self.compose([hero,hero])

    def test_wrong_source_hash_or_changed_source_bytes_are_refused(self):
        p=self.package(self.fixture());bad=p|{'content_sha256':'0'*64}
        with self.assertRaises(ValueError):self.compose([bad])
        (Path(p['package'])/'site'/'results.json').write_text('{}')
        with self.assertRaises(ValueError):self.compose([p])

    def test_missing_model_forged_summary_and_private_program_fields_are_refused(self):
        p=self.package(self.fixture())
        def edit(change):
            def mutate(site):
                path=site/'results.json';value=json.loads(path.read_text());change(value)
                path.write_bytes(publication.encoded(value))
            return self.mutate(p,mutate)
        cases=[edit(lambda s:s['attempts'].pop()),
            edit(lambda s:s['cohort'].update(complete=True)),
            edit(lambda s:s['attempts'][0].update(code='secret program')),
            edit(lambda s:s['research_matrix']['models'][0]['cells'][0].update(mean=999999))]
        for bad in cases:
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.compose([bad])

    def test_mixed_assets_and_escaped_or_remote_recording_links_are_refused(self):
        hero=self.package(self.fixture('hero',10));bow=self.package(self.fixture('bowmaster',20))
        bad=self.mutate(bow,lambda site:(site/'dashboard.js').write_bytes((site/'dashboard.js').read_bytes()+b'\n'))
        with self.assertRaisesRegex(ValueError,'catalog_mixed_assets'):self.compose([hero,bad])
        for url in ('https://example.test/video.webm','../recordings/'+('a'*32)+'.webm','./recordings/%2e%2e/video.webm'):
            def change(site):
                path=site/'results.json';snapshot=json.loads(path.read_text());snapshot['attempts'][0]['recording']['url']=url
                path.write_bytes(publication.encoded(snapshot))
            bad=self.mutate(hero,change)
            with self.assertRaisesRegex(ValueError,'catalog_recording_binding'):self.compose([bad])

    def test_changed_archive_inventory_or_extra_private_file_is_refused(self):
        p=self.package(self.fixture());archive=self.archive()
        archive['inventory_sha256']='0'*64
        with self.assertRaises(ValueError):self.compose([p],archive)
        archive['inventory_sha256']=publication.digest(Path(archive['inventory']).read_bytes())
        (Path(archive['site'])/'journal.json').write_text('{}')
        with self.assertRaises(ValueError):self.compose([p],archive)

    def test_payload_cap_remains_bounded_and_outputs_never_overlap_inputs(self):
        p=self.package(self.fixture())
        with patch.object(catalog,'MAX_PAYLOAD',1024),self.assertRaisesRegex(ValueError,'catalog_payload_limit'):
            self.compose([p])
        with self.assertRaisesRegex(ValueError,'catalog_inputs_overlap_output'):
            catalog.compose(self.request([p]),Path(p['package']))


class CatalogUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is required for public catalog UI checks')
    def test_root_links_and_saved_progress_refresh_use_actual_dashboard_code(self):
        source=(Path(__file__).resolve().parents[1]/'ui/full-client-dashboard/dashboard.js').read_text()
        render=source[source.index('  function renderCatalog(){'):source.index('  function renderResearch(){')]
        refresh=source[source.index('  async function refresh(){'):source.index("  window.addEventListener('pagehide'")]
        fixture="""
const assert=require('node:assert/strict');
const nodes={};const $=id=>nodes[id]||=( {children:[],replaceChildren(){this.children=[]},append(...v){this.children.push(...v)}} );
const el=(tag,text)=>({tag,text,children:[],append(...v){this.children.push(...v)}}),document={createTextNode:text=>({text})};
const links=()=>$('catalog-cohorts').children.flatMap(group=>group.children.filter(v=>v.tag==='a'));
let snapshot={catalog:{schema_version:1,cohorts:[
 {url:'./cohorts/aaaaaaaaaaaaaaaa/',class_id:'hero',verified:1},
 {url:'https://example.test/',class_id:'bowmaster',verified:4}]}},closed=false,timer;
"""
        checks="""
renderCatalog();assert.equal($('catalog-cohorts').hidden,false);
assert.equal(links().length,1);
assert.equal(links()[0].href,'./cohorts/aaaaaaaaaaaaaaaa/');
assert.equal(links()[0].text,'Hero · 1 / 4 verified');
let scheduled,rendered=0;const setTimeout=(fn,ms)=>{scheduled=ms;return fn};
const renderResearch=()=>rendered++,renderLive=()=>{},renderComparisons=()=>{},renderHistory=()=>{},freshness=()=>{};
const replay={open:false};
const next={schema_version:1,attempts:[{id:'a'},{id:'b'},{id:'c'},{id:'d'}],comparisons:[],generated_at_ms:1,
 live_status_available:false,catalog:{schema_version:2,previous_cohorts:[],cohorts:[{url:'./cohorts/aaaaaaaaaaaaaaaa/',class_id:'hero',verified:2}]}};
const fetch=async(url,options)=>{assert.equal(url,'./results.json');assert.equal(options.cache,'no-store');return{ok:true,json:async()=>next}};
"""
        final="""
(async()=>{await refresh();assert.equal(scheduled,10000);assert.equal(rendered,1);
 assert.equal(snapshot.attempts.length,4);assert.equal(links()[0].text,'Hero · 2 / 4 verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result=subprocess.run([shutil.which('node'),'--max-old-space-size=64','-e',fixture+render+checks+refresh+final],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()

class PreviousCohortTests(CatalogTests):
    def request2(self,active,previous,archive=None):
        return self.request(active,archive)|{'schema_version':2,'previous_cohorts':previous}
    def test_previous_different_assets_preserved_separate_from_active_matrix(self):
        prior=self.package(self.fixture('hero',100),2)
        prior=self.mutate(prior,lambda site:(site/'style.css').write_text('/* prior pinned UI */'))
        active=self.package(self.fixture('hero',200),1)
        request=self.request2([active],[prior],self.archive())
        result=catalog.compose(request,self.out);site=Path(result['site']);snapshot=json.loads((site/'results.json').read_text())
        self.assertEqual(snapshot['catalog']['schema_version'],2)
        self.assertEqual(snapshot['catalog']['planned'],4)
        self.assertEqual(snapshot['catalog']['previous_cohorts'][0]['scope'],'previous_cohort')
        self.assertEqual(len(snapshot['research_matrix']['columns']),1)
        self.assertEqual(len(snapshot['attempts']),12)
        manifest=publication.verify_package(Path(prior['package']),prior['content_sha256'])
        prefix=manifest['content']['target_path'].lstrip('/')
        for name,expected in manifest['content']['files'].items():
            self.assertEqual(publication.stable_fingerprint(site/prefix/name,publication.MAX_ADAPTIVE_VIDEO),expected)
        self.assertTrue(any(g['scope']=='previous_cohort' for g in snapshot['comparisons']))
    def test_active_complete_retires_previous_and_legacy_without_touching_inputs(self):
        prior=self.package(self.fixture('hero',100),2);active=self.package(self.fixture('hero',200),4)
        result=catalog.compose(self.request2([active],[prior],self.archive()),self.out)
        snapshot=json.loads((Path(result['site'])/'results.json').read_text())
        self.assertTrue(result['archive_retired']);self.assertEqual(snapshot['catalog']['previous_cohorts'],[])
        self.assertEqual(len(snapshot['attempts']),4)
        old=publication.verify_package(Path(prior['package']),prior['content_sha256'])
        self.assertFalse((Path(result['site'])/old['content']['target_path'].lstrip('/')).exists())
    def test_prior_selection_bounded_and_duplicate_mount_refused(self):
        active=self.package(self.fixture('hero',100),1)
        for previous,code in [([active]*4,'catalog_previous_cohorts_limit'),([active],'catalog_duplicate_mount')]:
            with self.assertRaisesRegex(ValueError,code):catalog.compose(self.request2([active],previous),self.out)
    def test_previous_cohort_does_not_waive_active_asset_consistency(self):
        active=self.package(self.fixture('hero',100),1)
        bow=self.package(self.fixture('bowmaster',200),1)
        bow=self.mutate(bow,lambda site:(site/'style.css').write_text('/* changed */'))
        with self.assertRaisesRegex(ValueError,'catalog_mixed_assets'):
            catalog.compose(self.request2([active,bow],[]),self.out)

class CatalogAnnotationTests(unittest.TestCase):
    setUp=CatalogTests.setUp
    tearDown=CatalogTests.tearDown
    fixture=CatalogTests.fixture
    package=CatalogTests.package
    request=CatalogTests.request

    def selected(self):
        package=self.package(self.fixture('bowmaster',700),1)
        manifest=publication.verify_package(Path(package['package']),package['content_sha256'])
        return package,manifest

    def test_root_note_changes_digest_but_preserves_every_nested_byte_and_score(self):
        package,manifest=self.selected();request=self.request([package]);plain=catalog.compose(request,self.out)
        note={'plan_sha256':manifest['content']['plan_sha256'],
              'text':'Hurricane is discrete & "channel" fidelity is unaccepted.'}
        request['annotations']=[note];result=catalog.compose(request,self.out);site=Path(result['site'])
        html=(site/'index.html').read_text();prefix=manifest['content']['target_path'].lstrip('/')
        self.assertIn('Cohort limitations',html)
        self.assertIn('discrete &amp; &quot;channel&quot;',html)
        self.assertIn('href="./'+prefix+'"',html)
        self.assertLess(html.index('Cohort limitations'),html.index('id="research-title"'))
        self.assertNotEqual(result['catalog_sha256'],plain['catalog_sha256'])
        for name,expected in manifest['content']['files'].items():
            self.assertEqual(publication.stable_fingerprint(site/prefix/name,publication.MAX_ADAPTIVE_VIDEO),expected)
        before=json.loads((Path(plain['site'])/'results.json').read_text());after=json.loads((site/'results.json').read_text())
        for key in ['attempts','comparisons','research_matrix']:self.assertEqual(before[key],after[key])
        content=json.loads((Path(result['directory'])/'catalog-manifest.json').read_text())['content']
        self.assertEqual(content['annotations'][0]['text'],note['text'])
        again=catalog.compose(request,self.out);self.assertEqual(again['catalog_sha256'],result['catalog_sha256'])
        checked_payload(site,Path(result['inventory']),result['inventory_sha256'],manifest)

    def test_rejects_unknown_duplicate_markup_control_and_private_fields(self):
        package,manifest=self.selected();note={'plan_sha256':manifest['content']['plan_sha256'],'text':'Discrete Hurricane only.'}
        invalid=[([note|{'plan_sha256':'f'*64}],'unknown_cohort'),([note,note],'duplicate'),
                 ([note|{'credentials':'secret'}],'schema'),([note|{'text':'<b>unsafe</b>'}],'text'),
                 ([note|{'text':'line\nline'}],'text'),([note|{'text':'hidden\u202e'}],'text'),
                 ([note|{'text':'[link](https://example.test)'}],'text'),
                 ([note|{'text':'/Users/operator/private'}],'text'),
                 ([note|{'text':'operator@example.test'}],'text'),([note|{'text':'127.0.0.1'}],'text'),
                 ([note|{'text':'token=private'}],'text'),([note|{'text':'a'*401}],'text'),
                 ([note]*7,'limit')]
        for notes,error in invalid:
            with self.subTest(error=error),self.assertRaisesRegex(ValueError,'catalog_annotation.*'+error):
                catalog.compose(self.request([package])|{'annotations':notes},self.out)

    def test_retired_previous_cohort_cannot_receive_a_visible_note(self):
        prior=self.package(self.fixture('bowmaster',700),1);active=self.package(self.fixture('bowmaster',800),4)
        old=publication.verify_package(Path(prior['package']),prior['content_sha256'])
        request=self.request([active])|{'schema_version':2,'previous_cohorts':[prior],
            'annotations':[{'plan_sha256':old['content']['plan_sha256'],'text':'Old limitation.'}]}
        with self.assertRaisesRegex(ValueError,'catalog_annotation_unknown_cohort'):catalog.compose(request,self.out)

    def test_empty_optional_notes_preserve_legacy_catalog_bytes(self):
        package,_=self.selected();request=self.request([package]);old=catalog.compose(request,self.out)
        new=catalog.compose(request|{'annotations':[]},self.out)
        self.assertEqual(old['catalog_sha256'],new['catalog_sha256'])

    def test_retained_previous_note_is_linked_and_duplicate_text_rejected(self):
        prior=self.package(self.fixture('bowmaster',700),1);active=self.package(self.fixture('bowmaster',800),1)
        old=publication.verify_package(Path(prior['package']),prior['content_sha256'])
        current=publication.verify_package(Path(active['package']),active['content_sha256'])
        note={'plan_sha256':old['content']['plan_sha256'],'text':'Discrete attacks only.'}
        request=self.request([active])|{'schema_version':2,'previous_cohorts':[prior],'annotations':[note]}
        result=catalog.compose(request,self.out)
        html=(Path(result['site'])/'index.html').read_text()
        self.assertIn('href=".'+old['content']['target_path']+'"',html)
        request['annotations'].append(note|{'plan_sha256':current['content']['plan_sha256']})
        with self.assertRaisesRegex(ValueError,'catalog_annotation_duplicate'):catalog.compose(request,self.out)
