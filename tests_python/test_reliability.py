import asyncio,json
import httpx,pytest
from fastapi import HTTPException
from backend.models import compatible,Models


def test_transport_retries_only_transient_responses(monkeypatch):
    replies=[429,503,200];attempts=[];delays=[]
    async def request(method,url,**kwargs):
        attempts.append(url);code=replies.pop(0)
        body={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}]}
        return code,{},json.dumps(body).encode()
    async def sleep(delay):delays.append(delay)
    monkeypatch.setattr('backend.models.public_request',request)
    monkeypatch.setattr('backend.models.asyncio.sleep',sleep)
    assert asyncio.run(compatible('https://model.example/v1','test','test','instruction',{}))['value']['ok']
    assert len(attempts)==3 and delays==[.5,1.0]


@pytest.mark.parametrize('failure',['authentication','network'])
def test_transport_does_not_retry_authentication_or_hide_network_exhaustion(monkeypatch,failure):
    attempts=[]
    async def request(*args,**kwargs):
        attempts.append(1)
        if failure=='network':raise httpx.ConnectError('unavailable')
        return 401,{},b'{}'
    async def sleep(delay):pass
    monkeypatch.setattr('backend.models.public_request',request)
    monkeypatch.setattr('backend.models.asyncio.sleep',sleep)
    with pytest.raises(HTTPException):asyncio.run(compatible('https://model.example/v1','test','test','instruction',{}))
    assert len(attempts)==(3 if failure=='network' else 1)


def test_existing_personal_connection_is_blocked_before_decryption_or_http(monkeypatch):
    monkeypatch.setenv('EDENTICA_MODE','hackathon')
    row={'base_url':'https://api.openai.com/v1','model':'gpt-4','encrypted_key':'not-even-a-key'}
    service=Models(None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.complete('owner','instruction',{},None,selected=row))
    assert error.value.status_code==403

def test_rejected_source_blocks_structural_readiness():
    from pathlib import Path
    from backend.validation import inspect_program
    program=json.loads((Path(__file__).parent/'fixtures/program.json').read_text(encoding='utf-8'))
    program['sources'][0]['verification']={'status':'rejected'}
    report=inspect_program(program)
    assert not report['passed']
    assert any(x['code']=='source_rejected' for x in report['errors'])

def test_literal_case_constraints_override_wrong_llm_extraction():
 from backend.planning import explicit_requirements
 request='Программа повышения квалификации на 72 академических часа. Очно-заочная форма, 6 недель. Не менее 36 часов практики. Итоговая аттестация — защита проекта, 4 часа внутри 72.'
 req=explicit_requirements(request)
 assert req=={'type':'dpp','totalHours':72,'finalHours':4,'weeks':6,'minPracticeHours':36,'format':'Очно-заочная'}


def test_regulatory_references_are_template_specific():
 from backend.regulations import references,section_policy_issues
 assert any('629' in x['title'] for x in references('general'))
 assert section_policy_issues({'sources':[{'title':'Приказ Минпросвещения России № 266'}]},'general')
 assert section_policy_issues({'sections':{'x':'Приказ № 123456'}},'dpp')
 assert not section_policy_issues({'sources':references('general')},'general')

@pytest.mark.parametrize('fault',[None,'model','database','encryption'])
def test_preflight_validates_shapes_without_exposing_secrets(monkeypatch,capsys,fault):
    from cryptography.fernet import Fernet
    from backend.preflight import main
    monkeypatch.setenv('EDENTICA_MODE','hackathon')
    monkeypatch.setenv('LLM_PROVIDER','cloudru')
    monkeypatch.setenv('LLM_BASE_URL','https://hub.gigaschool.ru/api/v1/llm/v1')
    monkeypatch.setenv('LLM_API_KEY','test-only-secret-never-printed')
    monkeypatch.setenv('LLM_MODEL','GigaChat/GigaChat-3-Pro' if fault!='model' else '')
    monkeypatch.setenv('DATABASE_URL','postgresql://user:private@db:5432/test' if fault!='database' else 'sqlite:///file.db')
    monkeypatch.setenv('APP_ENCRYPTION_KEY',Fernet.generate_key().decode() if fault!='encryption' else 'invalid-key')
    assert main()==(0 if fault is None else 2)
    output=capsys.readouterr().out
    assert json.loads(output)['ready']==(fault is None)
    assert 'test-only-secret' not in output and 'private' not in output

def test_structured_output_is_passed_to_provider_and_capability_fallback_is_bounded(monkeypatch):
    observed=[]
    async def request(method,url,**kwargs):
        observed.append(json.loads(json.dumps(kwargs['payload'])))
        if len(observed)==1:return 400,{},b'{"error":"unsupported response_format"}'
        return 200,{},json.dumps({'choices':[{'message':{'content':'{"answer":"ok"}'},'finish_reason':'stop'}]}).encode()
    monkeypatch.setattr('backend.models.public_request',request)
    schema={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}
    result=asyncio.run(compatible('https://model.example/v1','secret','test','instruction',{},response_schema=schema))
    assert result['value']=={'answer':'ok'}
    assert observed[0]['response_format']['json_schema']['schema']==schema
    assert observed[1]['response_format']=={'type':'json_object'}

def test_dynamic_schemas_require_fields_cardinality_and_current_lesson_ids():
    from backend.output_contracts import schema_for
    payload={'module':{'topics':[{'id':'T2.3','competencyIds':['C2']}]},'questionQuota':1,'requirements':{'portfolioItems':3}}
    s=schema_for('assessment',payload)
    assert s['properties']['questions']['minItems']==s['properties']['questions']['maxItems']==1
    assert s['$defs']['TestQuestion']['properties']['topicId']['enum']==['T2.3']
    assert 'title' in s['$defs']['Seminar']['properties']
    assert s['$defs']['Seminar']['required']==list(s['$defs']['Seminar']['properties'])
    f=schema_for('final_assessment',payload)
    assert f['properties']['items']['minItems']==f['properties']['items']['maxItems']==3

@pytest.mark.parametrize('redirect',['/new','http://127.0.0.1/private'])
def test_research_redirects_are_revalidated_and_never_claim_expert_confirmation(monkeypatch,redirect):
    from backend.research import fetch_source
    from backend.net import public_url
    from uuid import uuid4
    url='https://example.org/'+uuid4().hex;calls=[]
    async def request(method,target,**kwargs):
        public_url(target)
        calls.append(target)
        if len(calls)==1:return 302,{'location':redirect},b''
        return 200,{'content-type':'text/html'},'<p>Проверяемый текст источника</p>'.encode()
    monkeypatch.setattr('backend.research.public_request',request)
    result=asyncio.run(fetch_source(url))
    if redirect.startswith('/'):
        assert result['status']=='fetched' and result['resolvedUrl']=='https://example.org/new'
        assert len(calls)==2 and result.get('verification') is None
    else:
        assert result['status']=='not_fetched' and len(calls)==1
