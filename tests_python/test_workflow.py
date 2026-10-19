"""Single-entry workflow, mandatory human gate and typed arithmetic contracts."""
import asyncio,copy,json,time
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.rules import Rules
from backend.validation import inspect_skeleton,SECTIONS
from backend.planning import build_skeleton
from backend.config import Settings
from fastapi import HTTPException

H={'X-Edentica':'1'}

def fixture():
 from pathlib import Path
 return json.loads((Path(__file__).parent/'fixtures/program.json').read_text(encoding='utf-8'))

def semantic():
 s=fixture()['skeleton']
 return {k:copy.deepcopy(s[k]) for k in ('title','goal','competencies','modules')}

@pytest.mark.parametrize('kind',['general','dpp'])
@pytest.mark.parametrize('hours',[16,36,72,248,500])
def test_hour_and_calendar_contract_for_case_matrix(kind,hours):
 req={'type':kind,'totalHours':hours,'audience':'Взрослые слушатели','entryLevel':'Начальный','format':'Очно-заочная','assessment':'Проект','weeks':4,'minPracticeHours':hours//2}
 s=build_skeleton(semantic(),req)
 assert not inspect_skeleton(s,req)['errors']
 assert sum(m['totalHours'] for m in s['modules'])+s['finalHours']==hours
 assert sum(r['hours'] for r in s['calendar']['sessions'])==hours

@pytest.mark.parametrize('base,model',[('https://api.openai.com/v1','gpt-4'),('https://api.anthropic.com/v1','claude'),('https://foundation-models.api.cloud.ru/v1/other','Qwen'),('https://foundation-models.api.cloud.ru/v1','openai/gpt-4')])
def test_hackathon_provider_policy_denies_before_transport(monkeypatch,base,model):
 monkeypatch.setenv('EDENTICA_MODE','hackathon')
 with pytest.raises(ValueError):Settings.load().validate_endpoint(base,model)


@pytest.mark.parametrize('resume_after_failure',[False,True])
def test_single_entry_end_to_end_human_gate_and_all_exports(postgres_url,monkeypatch,resume_after_failure):
 async def probe(source):return {'access':'reachable','status':'unverified'}
 monkeypatch.setattr('backend.programs.probe_source',probe)
 base=fixture();calls=[];lecture_calls=[];failed_once=[]
 async def model(skill,payload):
  calls.append(payload)
  if 'Навык 1' in skill:
   value={'requirements':{'type':'general','totalHours':16,'audience':'Школьники','entryLevel':'Без опыта','format':'Очно','assessment':'Проект'},'questions':[{'field':'слайды','question':'Сколько нужно слайдов?'}],'notes':[]}
  elif 'Навык 2' in skill:value=semantic()
  elif 'Навык 3' in skill:
   m=payload['module'];t=m['topics'][0];original=next(iter(base['materials'].values()))
   if 'JSON-объект лекции' in skill:
    lecture_calls.append(t['id'])
    value=copy.deepcopy(original['lectures'][0]);value.update(topicId=t['id'],competencyIds=t['competencyIds'])
    return {'value':value,'usage':{'inputTokens':10,'outputTokens':20},'model':'contract-only'}
   if resume_after_failure and not failed_once:
    failed_once.append(True)
    raise HTTPException(503,'Проверяемый временный сбой оценивания')
   value={'moduleId':m['id'],'summary':'Описание урока','methodology':'Практика с обратной связью','sources':base['sources']}
   for kind in ('lectures','questions','seminars'):
    item=copy.deepcopy(original[kind][0]);item.update(topicId=t['id'],competencyIds=t['competencyIds']);value[kind]=[item]
  else:value={'sections':{t:'Содержательный текст раздела программы' for t in SECTIONS[payload['skeleton']['type']]},'finalAssessment':base['finalAssessment'],'sources':base['sources']}
  return {'value':value,'usage':{'inputTokens':10,'outputTokens':20},'model':'contract-only'}
 with TestClient(create_app(postgres_url,model),base_url='http://localhost') as c:
  c.post('/api/auth/register',headers=H,json={'login':'workflow-'+uuid4().hex,'name':'Тестовый методист','password':'Disposable-only-123','role':'methodist'}).raise_for_status()
  def post(**body):
   r=c.post('/api/programs',headers=H,json=body);assert r.status_code==200,r.text;return r.json()
  def wait(id):
   deadline=time.monotonic()+15
   while time.monotonic()<deadline:
    p=c.get('/api/programs',params={'id':id}).json()
    if p.get('job',{}).get('state')!='running':return p
    time.sleep(.03)
   raise AssertionError('Workflow did not finish')
  request='Программа повышения квалификации на 72 академических часа. Итоговая аттестация — защита проекта, 4 часа внутри 72.' if resume_after_failure else 'Полный запрос '+uuid4().hex
  p=post(request=request);p=wait(p['id'])
  assert p['state']=='skeleton_review',p.get('job')
  assert p['skeleton']['type']==('dpp' if resume_after_failure else 'general')
  assert p['skeleton']['totalHours']==(72 if resume_after_failure else 16)
  if resume_after_failure:assert p['skeleton']['finalHours']==4
  assert p['workflow']['humanApprovalRequired']
  assert not p['materials']
  before=len(calls);post(action='workflow',id=p['id']);assert len(calls)==before
  assert c.post('/api/programs',headers=H,json={'action':'generate','id':p['id']}).status_code==422
  post(action='approve',id=p['id'],expectedRevision=p['revision'],confirm=True)
  post(action='workflow',id=p['id']);p=wait(p['id'])
  if resume_after_failure:
   assert p['job']['state']=='failed'
   assert next(iter(next(iter(p['lessonDrafts'].values())).values()))['lectures']
   post(action='workflow',id=p['id']);p=wait(p['id'])
   assert len(lecture_calls)==len(set(lecture_calls)), 'Готовая лекция не должна генерироваться повторно'
  assert p['job']['state']=='completed',p['job']
  assert p['report']['passed'],p['report']['errors']
  assert p['state']=='draft_ready'
  assert all(c['questions'] and c['assignments'] and c['topics'] for c in p['report']['coverage'])
  assert len(p['report']['checks'])==5
  for format in ['docx','pptx','gift','json','report','zip']:
   r=c.post('/api/programs',headers=H,json={'action':'export','id':p['id'],'format':format})
   assert r.status_code==200,r.text[:300]
   if format=='zip':
    z=ZipFile(BytesIO(r.content));assert z.testzip() is None
    assert {'program.docx','program.json','tests.gift','validation-report.html'}<=set(z.namelist())
   if format=='report':assert 'Отчёт автопроверки' in r.text
