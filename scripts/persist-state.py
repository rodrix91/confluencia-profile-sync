"""Write only the validated public state via the ephemeral job token. No token files."""
from pathlib import Path
import base64
import json
import os
import re
import runpy
import subprocess
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parent.parent
JOB=runpy.run_path(str(Path(__file__).with_name('profile-job.py')))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):
        raise ValueError('redirect_refused')


def build_request(root,repository,token,prior_sha):
    policy=json.loads((root/'approved/references.json').read_text());JOB['require'](repository==policy['repository'],'unrelated_repository')
    JOB['require'](isinstance(token,str) and token and '\r' not in token and '\n' not in token,'invalid_ephemeral_token')
    JOB['require'](re.fullmatch(r'[a-f0-9]{40}',prior_sha),'invalid_prior_sha')
    path=root/'state/current.json';JOB['require'](not path.is_symlink(),'unsafe_state_path')
    content=path.read_bytes();JOB['require'](len(content)<=1_000_000,'state_too_large')
    JOB['validate_bundle'](json.loads(content),policy)
    payload=dict(message='Update validated public profile metadata',content=base64.b64encode(content).decode(),sha=prior_sha,branch='main')
    return urllib.request.Request('https://api.github.com/repos/'+repository+'/contents/state/current.json',
        data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
        'Content-Type':'application/json','User-Agent':'Confluencia-profile-job/1.0'},method='PUT')


if __name__=='__main__':
    try:
        repository=os.environ['GITHUB_REPOSITORY'];token=os.environ['CONFLUENCIA_JOB_TOKEN']
        prior=subprocess.check_output(['git','rev-parse','HEAD:state/current.json'],cwd=ROOT,stderr=subprocess.DEVNULL).decode().strip()
        request=build_request(ROOT,repository,token,prior)
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=20) as response:
            result=json.loads(response.read(100_000))
            JOB['require'](response.status in (200,201),'persist_failed')
            commit=result.get('commit',{}).get('sha');JOB['require'](isinstance(commit,str) and re.fullmatch(r'[a-f0-9]{40}',commit),'invalid_commit_receipt')
            print(json.dumps({'stateCommit':commit,'path':'state/current.json'}))
    except (ValueError,OSError,KeyError,subprocess.CalledProcessError,JOB['CORE']['Invalid']):
        # Never log request headers, token, response body or private diagnostics.
        print(json.dumps({'persisted':False,'code':'persist_failed_or_conflict','requiresRemoteReadback':True}))
        raise SystemExit(1)
