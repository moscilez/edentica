"""Token accounting must survive cache hits, failed output and project deletion."""
import asyncio
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from backend.app import create_app
from backend.rules import Rules
from backend.usage import with_usage

H={'X-Edentica':'1'}


def register(c):
    return c.post('/api/auth/register',headers=H,json={'login':'usage-'+uuid4().hex,'name':'Проверка расхода','password':'Disposable-only-test-123','role':'methodist'}).json()


def action(c,name,**data):
    r=c.post('/api/agent',headers=H,json={'action':name,**data})
    assert r.status_code in (200,201),r.text
    return r.json()


def wait(c,id):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        p=action(c,'get',id=id)
        if p.get('job',{}).get('state')!='running':return p
        time.sleep(.05)
    raise AssertionError('Job did not finish')


def value():
    s=asyncio.run(Rules().call('demonstration'))['skeleton']
    return {'requirements':{k:s[k] for k in ('type','totalHours','audience','entryLevel','format','assessment')},'questions':[],'notes':[],'skeleton':s}


def test_no_program_quota_usage_isolated_cache_not_charged(postgres_url):
    calls=[]; response=value()
    async def complete(*args):
        calls.append(args)
        return {'value':response,'usage':{'inputTokens':100,'outputTokens':50},'model':'usage-test'}
    with TestClient(create_app(postgres_url,complete),base_url='http://localhost') as c:
        assert c.get('/api/usage').status_code==401
        register(c)
        p=action(c,'create',request='Общеразвивающая программа на 16 часов. Проверка кеша '+uuid4().hex)
        p['usage']['inputTokens']=900000;p['tokenBudget']=1
        c.app.state.db.execute('UPDATE program_projects SET document=%s WHERE id=%s',(Jsonb(p),p['id']))
        action(c,'analyze',id=p['id']);assert wait(c,p['id'])['state']=='skeleton_review'
        other=action(c,'create',request=p['request']);action(c,'analyze',id=other['id']);assert wait(c,other['id'])['usage']['cacheHits']==1
        assert len(calls)==1
        stats=c.get('/api/usage?days=7&timezone=Europe/Moscow').json()
        assert len(stats['days'])==7
        assert sum(d['inputTokens'] for d in stats['days'])==100
        assert sum(d['outputTokens'] for d in stats['days'])==50
        assert stats['allTime']['calls']==1
        for query in ['days=0','days=367','days=no','timezone=Not/AZone']:
            assert c.get('/api/usage?'+query).status_code==422
        c.cookies.clear();register(c)
        assert c.get('/api/usage').json()['allTime']['inputTokens']==0


def test_failed_json_usage_retained_after_deletion(postgres_url):
    response=value();calls=[]
    async def complete(*args):
        calls.append(args)
        if len(calls)==1:
            raise with_usage(ValueError('Модель вернула некорректный JSON'),{'model':'test','usage':{'inputTokens':20,'outputTokens':40},'usageReported':True})
        return {'value':response,'usage':{'inputTokens':100,'outputTokens':50},'model':'test'}
    with TestClient(create_app(postgres_url,complete),base_url='http://localhost') as c:
        register(c);p=action(c,'create',request='Проверка повтора '+uuid4().hex)
        action(c,'analyze',id=p['id']);p=wait(c,p['id'])
        assert p['job']['state']=='completed'
        assert p['usage']['inputTokens']==120 and p['usage']['outputTokens']==90
        stats=c.get('/api/usage').json()
        assert stats['allTime']=={'inputTokens':120,'outputTokens':90,'calls':2}
        assert sum(d['failedCalls'] for d in stats['days'])==1
        action(c,'delete',id=p['id'],confirm=True)
        assert c.get('/api/usage').json()['allTime']==stats['allTime']


def test_timezone_days_and_legacy_baseline_no_double_count(postgres_url):
    async def complete(*args):return {'value':value(),'usage':{'inputTokens':10,'outputTokens':5},'model':'test'}
    app=create_app(postgres_url,complete)
    with TestClient(app,base_url='http://localhost') as c:
        owner=register(c);p=action(c,'create',request='Старый счётчик '+uuid4().hex)
        p['usage'].update(inputTokens=1000,outputTokens=500,calls=4)
        app.state.db.execute('UPDATE program_projects SET document=%s WHERE id=%s',(Jsonb(p),p['id']))
        cookie=c.cookies.get('session')
    for _ in range(2):
        with TestClient(create_app(postgres_url,complete),base_url='http://localhost') as c:
            c.cookies.set('session',cookie)
            data=c.get('/api/usage').json()
            assert data['legacy']=={'inputTokens':1000,'outputTokens':500,'calls':4}
            assert data['allTime']==data['legacy']
            assert sum(d['calls'] for d in data['days'])==0
    with TestClient(create_app(postgres_url,complete),base_url='http://localhost') as c:
        c.cookies.set('session',cookie)
        app=c.app
        app.state.db.execute('''INSERT INTO llm_usage_events(id,owner,project_id,provider,model,skill,input_tokens,output_tokens,usage_known,status,created)
            VALUES(%s,%s,%s,'test','test','intake',12,8,false,'completed',
            (date_trunc('day',now() AT TIME ZONE 'UTC')-interval '1 day'+interval '22 hours 30 minutes') AT TIME ZONE 'UTC')''',(str(uuid4()),owner['id'],p['id']))
        moscow=c.get('/api/usage?days=7&timezone=Europe/Moscow').json()
        utc=c.get('/api/usage?days=7&timezone=UTC').json()
        md=next(d for d in moscow['days'] if d['calls']);ud=next(d for d in utc['days'] if d['calls'])
        assert md['date']!=ud['date']
        assert md['unknownCalls']==1
        assert moscow['allTime']=={'inputTokens':1012,'outputTokens':508,'calls':5}



def test_api_output_has_no_platform_token_cap_and_failed_usage_survives(monkeypatch):
    import json
    import pytest
    from fastapi import HTTPException
    from backend.models import compatible
    sent=[]
    async def transport(*args,**kwargs):
        sent.append(kwargs['payload'])
        return 200,{},json.dumps({'choices':[{'finish_reason':'length','message':{'content':'{'}}],
            'usage':{'prompt_tokens':123,'completion_tokens':456}}).encode()
    monkeypatch.setattr('backend.models.public_request',transport)
    with pytest.raises(HTTPException) as error:
        asyncio.run(compatible('https://example.com/v1','test-key','test-model','JSON instruction',{}))
    assert not any(k in sent[0] for k in ('max_tokens','max_completion_tokens','max_output_tokens'))
    assert error.value.model_result['usage']=={'inputTokens':123,'outputTokens':456}
    assert error.value.model_result['usageReported'] is True
