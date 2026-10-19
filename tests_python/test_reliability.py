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
