"""Portable offline contracts; reads only the exported public package."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import copy
import json
import runpy
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
M=runpy.run_path(str(Path(__file__).with_name('profile-job.py')))
P=runpy.run_path(str(Path(__file__).with_name('persist-state.py')))
NOW=datetime.now(timezone.utc)+timedelta(days=2)


class JobContract(unittest.TestCase):
    def setUp(self):
        self.policy=json.loads((ROOT/'approved/references.json').read_text())
        self.bundle=json.loads((ROOT/'state/current.json').read_text())
        # Keep the offline fixture independent of real job backoff and its own repo.
        for key,entry in self.bundle['cache']['collections'].items():
            allowed=M['expected'](self.policy,key)
            good=entry['lastGood'];good['records']=[r for r in good['records'] if r['remoteId'] in allowed]
            good['pages']=[];good['sha256']=M['CORE']['digest'](good['records'])
            entry.update(status='historical',lastAttemptAt=None,backoffUntil=None,failure=None,pending=None)
        self.bundle['operationalRepositoryId']=None
        self.rows={}
        for key,entry in self.bundle['cache']['collections'].items():
            self.rows[key]=[]
            for row in entry['lastGood']['records']:
                if key=='github':
                    raw=dict(id=int(row['remoteId']),full_name=row['name'],html_url=row['url'],private=False,owner={'login':'rodrix91'},pushed_at=row['lastActivity'],fork=row['fork'],archived=row['archived'])
                elif key=='gitlab':
                    raw=dict(id=int(row['remoteId']),path_with_namespace=row['name'],web_url=row['url'],visibility='public',namespace={'full_path':'rodripn91'},last_activity_at=row['lastActivity'],archived=row['archived'])
                else:
                    raw=dict(_id=row['remoteId'],id=row['name'],private=False,lastModified=row['lastActivity'])
                self.rows[key].append(raw)
        self.calls=[]

    def fetch(self,url,headers):
        self.calls.append((url,headers))
        key=next(k for k,v in M['CORE']['TARGETS'].items() if v[3].split('?')[0]==url.split('?')[0])
        second='cursor=fixture-second-page' in url
        rows=self.rows[key][100:] if second else self.rows[key][:100]
        h={'content-type':'application/json','etag':'"fixture"'}
        if len(self.rows[key])>100 and not second:
            h['link']='<'+url+'&cursor=fixture-second-page>; rel="next"'
        return 200,h,json.dumps(rows).encode()

    def process(self,**kwargs):
        return M['process'](self.bundle,self.policy,NOW,fetch=self.fetch,**kwargs)

    def test_success_promotes_only_reviewed_metadata_and_keeps_type_review_dates(self):
        before=copy.deepcopy(self.bundle);out=self.process()
        self.assertEqual(self.bundle,before)
        self.assertEqual(out['lastRun']['result'],'promoted')
        self.assertEqual(len(out['accepted']['references']),len(self.policy['entries']))
        self.assertEqual(out['lastRun']['newCandidateCount'],0)
        self.assertEqual(out['accepted']['references'][0]['typeReviewedAt'],self.policy['entries'][0]['reviewedAt'])

    def test_unknown_names_and_urls_never_enter_persisted_output(self):
        self.rows['spaces'].append(dict(_id='abcdef012345678901234567',id='Hugdrigo/unreviewed-fixture-name',private=False))
        out=self.process()
        self.assertEqual(out['accepted'],self.bundle['accepted'])
        self.assertEqual(out['lastRun']['result'],'retained')
        self.assertEqual(out['lastRun']['newCandidateCount'],1)
        self.assertNotIn('unreviewed-fixture-name',json.dumps(out))
        self.assertNotIn('abcdef012345678901234567',json.dumps(out))

    def test_removed_reference_retains_accepted_observation_and_full_prior_cache(self):
        self.rows['spaces']=self.rows['spaces'][1:];out=self.process()
        self.assertEqual(out['accepted'],self.bundle['accepted'])
        self.assertEqual(out['cache']['collections']['spaces']['lastGood'],self.bundle['cache']['collections']['spaces']['lastGood'])
        self.assertIsNone(out['cache']['collections']['spaces']['pending'])

    def test_renamed_reference_requires_review_without_publishing_the_new_name(self):
        row=self.rows['github'][0];row['full_name']='rodrix91/unreviewed-rename';row['html_url']='https://github.com/'+row['full_name']
        out=self.process();self.assertEqual(out['accepted'],self.bundle['accepted']);self.assertNotIn('unreviewed-rename',json.dumps(out))

    def test_http_failure_retains_accepted_data_and_records_safe_failure_status(self):
        out=M['process'](self.bundle,self.policy,NOW,fetch=lambda *_:(503,{},b'private server diagnostic'))
        self.assertEqual(out['accepted'],self.bundle['accepted'])
        self.assertEqual(out['lastRun']['result'],'retained')
        self.assertNotIn('private server diagnostic',json.dumps(out))

    def test_rate_limit_backoff_survives_in_the_atomic_bundle(self):
        out=M['process'](self.bundle,self.policy,NOW,fetch=lambda *_:(429,{'retry-after':'7200'},b''))
        again=M['process'](out,self.policy,NOW+timedelta(hours=1),fetch=lambda *_:self.fail('Backoff must avoid network'))
        self.assertEqual(again['lastRun']['requests'],0)
        self.assertEqual(again['accepted'],self.bundle['accepted'])

    def test_operational_repository_is_not_counted_as_a_professional_reference(self):
        own='9999999999';self.rows['github'].append(dict(id=int(own),full_name=self.policy['repository'],html_url='https://github.com/'+self.policy['repository'],private=False,owner={'login':'rodrix91'},fork=False,archived=False,pushed_at=None))
        out=self.process(operational_id=own)
        self.assertEqual(out['lastRun']['result'],'promoted')
        self.assertEqual(out['operationalRepositoryId'],own)
        self.assertEqual(len(out['accepted']['references']),len(self.policy['entries']))
        self.assertFalse(any(r['remoteId']==own for r in out['accepted']['references']))

    def test_operational_id_must_not_belong_to_an_unrelated_or_reviewed_repository(self):
        own='9999999999';self.rows['github'].append(dict(id=int(own),full_name='rodrix91/unrelated-fixture',html_url='https://github.com/rodrix91/unrelated-fixture',private=False,owner={'login':'rodrix91'},fork=False,archived=False,pushed_at=None))
        with self.assertRaises(ValueError):self.process(operational_id=own)
        with self.assertRaises(ValueError):self.process(operational_id=self.policy['entries'][0]['remoteId'])

    def test_private_fields_or_unsafe_destinations_cannot_be_added_to_policy(self):
        for change in [lambda p:p['entries'][0].update(email='fixture@example.invalid'),lambda p:p['entries'][0].update(url='javascript:alert(1)'),lambda p:p.update(repository='someone-else/repo')]:
            policy=copy.deepcopy(self.policy);change(policy)
            with self.assertRaises(Exception):M['validate_policy'](policy)

    def test_accepted_data_and_cache_cannot_include_unapproved_records(self):
        bad=copy.deepcopy(self.bundle);bad['accepted']['references'][0]['name']='someone-else/unknown'
        with self.assertRaises(ValueError):M['validate_bundle'](bad,self.policy)
        bad=copy.deepcopy(self.bundle);bad['cache']['collections']['spaces']['pending']=copy.deepcopy(bad['cache']['collections']['spaces']['lastGood'])
        with self.assertRaises(ValueError):M['validate_bundle'](bad,self.policy)

    def test_atomic_failure_leaves_all_prior_bundle_bytes_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'approved').mkdir();(root/'state').mkdir();(root/'approved/references.json').write_text(json.dumps(self.policy));path=root/'state/current.json';path.write_text(json.dumps(self.bundle));before=path.read_bytes()
            with patch.object(M['CORE']['os'],'replace',side_effect=OSError('fixture failure')):
                with self.assertRaises(OSError):M['execute'](root,NOW,self.fetch)
            self.assertEqual(path.read_bytes(),before);self.assertFalse((root/'state/.job-running').exists())

    def test_lock_prevents_two_local_writers(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'approved').mkdir();(root/'state').mkdir();(root/'approved/references.json').write_text(json.dumps(self.policy));(root/'state/current.json').write_text(json.dumps(self.bundle));(root/'state/.job-running').mkdir()
            with self.assertRaises(FileExistsError):M['execute'](root,NOW,self.fetch)

    def test_persistence_request_has_one_fixed_destination_and_no_token_in_payload(self):
        token='synthetic-not-a-secret';req=P['build_request'](ROOT,self.policy['repository'],token,'a'*40)
        self.assertEqual(req.get_method(),'PUT');self.assertEqual(req.full_url,'https://api.github.com/repos/rodrix91/confluencia-profile-sync/contents/state/current.json')
        self.assertNotIn(token,req.data.decode());body=json.loads(req.data);self.assertEqual(body['branch'],'main');self.assertEqual(body['sha'],'a'*40)
        with self.assertRaises(ValueError):P['build_request'](ROOT,'someone-else/repo',token,'a'*40)

    def test_workflow_is_bounded_public_only_and_does_not_retrigger_on_state_commits(self):
        text=(ROOT/'.github/workflows/profile-sync.yml').read_text()
        self.assertIn("cron: '37 10 * * *'",text);self.assertIn('timeout-minutes: 6',text);self.assertIn('github.event.repository.private == false',text)
        self.assertNotIn('pull_request_target',text);self.assertNotIn('actions/cache',text);self.assertNotIn('upload-artifact',text);self.assertNotIn("- 'state/",text)
        self.assertIn('persist-credentials: false',text);self.assertIn('cancel-in-progress: false',text)
        self.assertRegex(text,r'actions/checkout@[a-f0-9]{40}');self.assertRegex(text,r'actions/setup-python@[a-f0-9]{40}')


if __name__=='__main__':
    unittest.main()
