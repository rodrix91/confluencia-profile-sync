"""Atomic public-metadata job; never reads CV documents or executes remote code."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import copy
import json
import os
import re
import runpy

CORE_PATH = Path(__file__).with_name('sync-public-profiles.py')
if not CORE_PATH.exists():
    CORE_PATH = Path(__file__).resolve().parents[2]/'scripts/sync-public-profiles.py'
CORE = runpy.run_path(str(CORE_PATH))
ROOT = Path(__file__).resolve().parent.parent
SCHEMA = 'confluencia-public-profile-job-v1'
KINDS = {'tool_repository','planned_tool','coursework','fork_reference','profile','static_space','public_repository'}


def require(value, code):
    if not value:
        raise ValueError(code)


def validate_policy(policy):
    require(set(policy)=={'schema','repository','entries'},'invalid_policy')
    require(policy['schema']=='reviewed-public-reference-policy-v1','invalid_policy')
    require(policy['repository']=='rodrix91/confluencia-profile-sync','unrelated_repository')
    require(isinstance(policy['entries'],list) and 1<=len(policy['entries'])<=1000,'invalid_policy')
    seen=set()
    for entry in policy['entries']:
        require(set(entry)=={'collection','remoteId','name','url','kind','reviewedAt'},'invalid_policy')
        key=entry['collection'];require(key in CORE['TARGETS'],'invalid_collection')
        require(entry['kind'] in KINDS,'unreviewed_type')
        identity=(key,entry['remoteId']);require(identity not in seen,'duplicate_policy_identity');seen.add(identity)
        require(isinstance(entry['reviewedAt'],str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T[^\s]+)?',entry['reviewedAt']),'invalid_review_date')
        if len(entry['reviewedAt'])==10:
            datetime.strptime(entry['reviewedAt'],'%Y-%m-%d')
        else:
            CORE['date'](entry['reviewedAt'])
        row={k:entry[k] for k in ['remoteId','name','url']}
        row.update(lastActivity=None,fork=entry['kind']=='fork_reference' if key=='github' else None,archived=None)
        CORE['validate_records'](key,[row])


def expected(policy,key):
    return {r['remoteId']:r for r in policy['entries'] if r['collection']==key}


def observe(cache,policy,validated_at):
    """Only approved identities and frozen review types enter the accepted output."""
    rows=[]
    for rule in policy['entries']:
        collection=cache['collections'][rule['collection']]
        row=next(r for r in collection['lastGood']['records'] if r['remoteId']==rule['remoteId'])
        require(row['name']==rule['name'] and row['url']==rule['url'],'changed_identity')
        rows.append(dict(collection=rule['collection'],remoteId=rule['remoteId'],name=rule['name'],url=rule['url'],
                         kind=rule['kind'],typeReviewedAt=rule['reviewedAt'],metadataLastActivity=row['lastActivity'],archived=row['archived']))
    return dict(schema='approved-public-observation-v1',validatedAt=validated_at,references=rows)


def validate_bundle(bundle,policy):
    validate_policy(policy)
    require(set(bundle)=={'schema','cache','accepted','lastRun','operationalRepositoryId'} and bundle['schema']==SCHEMA,'invalid_bundle')
    CORE['validate_state'](bundle['cache'])
    operational=bundle['operationalRepositoryId']
    require(operational is None or isinstance(operational,str) and re.fullmatch(r'[1-9][0-9]*',operational),'invalid_operational_identity')
    for key,collection in bundle['cache']['collections'].items():
        require(collection['pending'] is None,'unreviewed_pending_cache')
        rules=expected(policy,key)
        for row in collection['lastGood']['records']:
            rule=rules.get(row['remoteId'])
            own=key=='github' and row['remoteId']==operational and row['name']==policy['repository'] and row['url']=='https://github.com/'+policy['repository']
            require(own or rule and row['name']==rule['name'] and row['url']==rule['url'],'unreviewed_cache_identity')
    accepted=bundle['accepted']
    require(set(accepted)=={'schema','validatedAt','references'} and accepted['schema']=='approved-public-observation-v1','invalid_observation')
    CORE['date'](accepted['validatedAt'])
    require(len(accepted['references'])==len(policy['entries']),'incomplete_observation')
    seen=set()
    for row in accepted['references']:
        require(set(row)=={'collection','remoteId','name','url','kind','typeReviewedAt','metadataLastActivity','archived'},'invalid_observation')
        key=row['collection'];rule=expected(policy,key).get(row['remoteId']);identity=(key,row['remoteId'])
        require(rule and identity not in seen,'unapproved_observation');seen.add(identity)
        require(all(row[k]==rule[k] for k in ['name','url','kind']) and row['typeReviewedAt']==rule['reviewedAt'],'unreviewed_observation')
        if row['metadataLastActivity'] is not None:CORE['date'](row['metadataLastActivity'])
        require(row['archived'] is None or isinstance(row['archived'],bool),'invalid_observation')
    report=bundle['lastRun']
    require(set(report)=={'at','requests','result','issues','newCandidateCount'},'invalid_job_report')
    CORE['date'](report['at'])
    require(isinstance(report['requests'],int) and 0<=report['requests']<=CORE['MAX_REQUESTS'],'invalid_job_report')
    require(report['result'] in {'seed','promoted','retained'},'invalid_job_report')
    require(isinstance(report['newCandidateCount'],int) and 0<=report['newCandidateCount']<=2000,'invalid_job_report')
    require(isinstance(report['issues'],list) and all(re.fullmatch(r'[a-z_]+:[a-z_]+',s) for s in report['issues']),'invalid_job_report')


def process(bundle,policy,now,fetch=None,operational_id=None):
    validate_bundle(bundle,policy)
    if bundle['operationalRepositoryId'] and operational_id:
        require(bundle['operationalRepositoryId']==operational_id,'changed_operational_identity')
    operational_id=operational_id or bundle['operationalRepositoryId']
    if operational_id is not None:
        require(re.fullmatch(r'[1-9][0-9]*',operational_id),'invalid_operational_identity')
        require(operational_id not in expected(policy,'github'),'operational_identity_overlaps_profile')
    kwargs={} if fetch is None else {'fetch':fetch}
    updated,report=CORE['refresh'](bundle['cache'],now,force=True,**kwargs)
    issues=[];new_count=0
    for key,entry in updated['collections'].items():
        rules=expected(policy,key)
        rows=entry['lastGood']['records']
        valid={r['remoteId']:r for r in rows}
        allowed=set(rules)
        if key=='github' and operational_id:
            operational=valid.get(operational_id)
            if operational:
                require(operational['name']==policy['repository'] and operational['url']=='https://github.com/'+policy['repository'],'unrelated_operational_repository')
                allowed.add(operational_id)
        unknown=set(valid)-allowed;missing=set(rules)-set(valid)
        renamed=any(valid[i]['name']!=rules[i]['name'] or valid[i]['url']!=rules[i]['url'] for i in set(rules)&set(valid))
        pending=entry['pending']
        if pending:
            new_count+=len({r['remoteId'] for r in pending['records']}-allowed)
        new_count+=len(unknown)
        unsafe=bool(unknown or missing or renamed or pending)
        if unsafe:
            # Unreviewed names/URLs never enter the public repository's cache.
            prior=copy.deepcopy(bundle['cache']['collections'][key])
            prior.update(lastAttemptAt=entry['lastAttemptAt'],backoffUntil=entry['backoffUntil'],
                         status='review_required',failure=None,pending=None)
            updated['collections'][key]=prior
            issues.append(key+':identity_review_required')
        elif entry['status'] not in {'fresh','unchanged'} or entry['failure']:
            issues.append(key+':source_unavailable')
    if not report['allCollectionsValidated'] and not issues:
        issues.append('all:source_unavailable')
    result=copy.deepcopy(bundle)
    result['operationalRepositoryId']=operational_id
    result['cache']=updated
    if not issues:
        validated_at=min(v['lastValidatedAt'] for v in updated['collections'].values())
        result['accepted']=observe(updated,policy,validated_at)
    result['lastRun']=dict(at=CORE['stamp'](now),requests=report['requests'],result='retained' if issues else 'promoted',
                           issues=issues,newCandidateCount=new_count)
    validate_bundle(result,policy)
    # Policy/data fields must not silently acquire private diagnostics or secrets.
    require(not re.search(r'mailto:|Bearer\s|github_pat_|/Users/|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',json.dumps(result)), 'unsafe_output')
    return result


def execute(root,now,fetch=None,operational_id=None):
    root=Path(root);policy=json.loads((root/'approved/references.json').read_text())
    path=root/'state/current.json';require(not path.is_symlink(),'unsafe_state_path')
    lock=root/'state/.job-running';lock.mkdir()
    try:
        bundle=json.loads(path.read_text());new=process(bundle,policy,now,fetch,operational_id)
        CORE['atomic_write'](path,new)
        return new['lastRun']
    finally:
        lock.rmdir()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--assert-ready',action='store_true');args=parser.parse_args()
    try:
        policy=json.loads((ROOT/'approved/references.json').read_text())
        if args.assert_ready:
            bundle=json.loads((ROOT/'state/current.json').read_text());validate_bundle(bundle,policy)
            raise SystemExit(0 if bundle['lastRun']['result']=='promoted' else 2)
        repo=os.environ.get('GITHUB_REPOSITORY')
        if repo is not None:require(repo==policy['repository'],'unrelated_runtime_repository')
        report=execute(ROOT,datetime.now(timezone.utc),operational_id=os.environ.get('GITHUB_REPOSITORY_ID'))
        print(json.dumps(report))
    except (ValueError,OSError,KeyError,TypeError,StopIteration,CORE['Invalid']):
        print(json.dumps({'result':'error','code':'invalid_state_or_io','previousAcceptedDataPreserved':True}))
        raise SystemExit(1)
