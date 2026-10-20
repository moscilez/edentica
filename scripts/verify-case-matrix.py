"""Opt-in paid acceptance run on exact briefs, isolated from all user data.

python scripts/verify-case-matrix.py --full --cases 1 2 3 4 5
Uses configured server-model credentials. Does not manufacture or approve content.
The approval in this harness represents the explicit test operator, not the agent.
"""
import argparse,json,os,sys,time
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit,urlunsplit

ROOT=Path.cwd() if __file__=='<stdin>' else Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
parser=argparse.ArgumentParser()
parser.add_argument('--cases',nargs='+',choices=['1','2','3','4','5'],default=['1','2','3','4','5'])
parser.add_argument('--full',action='store_true')
parser.add_argument('--credentials-stdin',action='store_true',help='Optional ephemeral LLM settings; never written to disk')
parser.add_argument('--gateway-key-stdin',action='store_true',help='Hidden terminal input for the hackathon key')
parser.add_argument('--output',default='output/case-matrix')
parser.add_argument('--requests',default=str(ROOT/'tests_python/fixtures/case-requests.json'),help='JSON map of exact input briefs')
parser.add_argument('--resume',action='store_true',help='Reuse synthetic saved checkpoints from this output directory')
args=parser.parse_args()
if args.gateway_key_stdin:
    from getpass import getpass
    os.environ.update(LLM_API_KEY=getpass('Gateway key (hidden): '),LLM_BASE_URL='https://hub.gigaschool.ru/api/v1/llm/v1',LLM_MODEL='GigaChat/GigaChat-3-Pro')
if args.credentials_stdin:
    from getpass import getpass
    values=json.loads(getpass('Gateway settings (hidden): ') if sys.stdin.isatty() else sys.stdin.readline())
    for key in ('LLM_BASE_URL','LLM_API_KEY','LLM_MODEL'):
        if values.get(key):os.environ[key]=values[key]
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
os.environ.update(EDENTICA_MODE='hackathon',LLM_PROVIDER='cloudru',SYSTEM_LLM_SHARED_ACCESS='1')
from backend.config import Settings
Settings.load().validate()
from backend.app import create_app
from backend.observability import logger
import logging
logger.setLevel(logging.WARNING)
from fastapi.testclient import TestClient
import psycopg
from psycopg import sql

cases=json.loads(Path(args.requests).read_text(encoding='utf-8'))
url=urlsplit(os.environ['DATABASE_URL']);name='edentica_acceptance_'+uuid4().hex
admin=urlunsplit((url.scheme,url.netloc,'/postgres',url.query,''))
test=urlunsplit((url.scheme,url.netloc,'/'+name,url.query,''))
output=ROOT/args.output;output.mkdir(parents=True,exist_ok=True)
answers={'type':'dpp','totalHours':72,'entryLevel':'3 курс СПО, изучены компьютерные сети и Linux',
    'audience':'Студенты колледжа направления информационных систем','format':'Очная в колледже','assessment':'Практический экзамен на стенде'}
defaults={'entryLevel':'Без опыта в изучаемой теме; уверенный пользователь компьютера',
    'audience':'Стажёры ИТ-компаний с базовыми знаниями Linux',
    'format':'Самостоятельная стажировка под руководством наставника',
    'assessment':'Защита отчёта о стажировке'}
H={'X-Edentica':'1'};results=[]
with psycopg.connect(admin,autocommit=True) as conn:conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING \'UTF8\'').format(sql.Identifier(name)))
try:
    from backend import cloudru
    async def recorded(skill,payload,*,response_schema=None):
        result=await cloudru.complete(skill,payload,response_schema=response_schema)
        # Synthetic test briefs only. No credentials, messages or reference uploads.
        with (output/'model-responses.jsonl').open('a',encoding='utf-8') as trace:
            trace.write(json.dumps({'skill':skill[:80],'validationErrors':payload.get('validationErrors'),'value':result.get('value')},ensure_ascii=False)+'\n')
        return result
    with TestClient(create_app(test,recorded),base_url='http://localhost') as c:
        r=c.post('/api/auth/register',headers=H,json={'login':'acceptance-'+uuid4().hex,'name':'Оператор проверки','password':uuid4().hex,'role':'methodist'});r.raise_for_status()
        def post(**body):
            r=c.post('/api/programs',headers=H,json=body);r.raise_for_status();return r.json()
        def wait(pid):
            deadline=time.monotonic()+1220;last=None
            while time.monotonic()<deadline:
                p=c.get('/api/programs',params={'id':pid}).json();job=p.get('job') or {}
                if job.get('step')!=last:print(json.dumps({'id':pid,'step':job.get('step')},ensure_ascii=False),flush=True);last=job.get('step')
                if job.get('state')!='running':return p
                time.sleep(1)
            raise TimeoutError('Этап не завершён за время проверки')
        for case in args.cases:
            started=time.monotonic();row={'case':case,'exactBrief':True,'full':args.full,'testAnswers':{},'model':Settings.load().model};p=None
            try:
                checkpoint=output/f'case-{case}.json'
                previous=json.loads(checkpoint.read_text(encoding='utf-8')) if args.resume and checkpoint.exists() else None
                if previous and previous.get('request')==cases[case] and previous.get('skeleton',{}).get('constraintVersion')==3:
                    created=post(action='create',request=cases[case])
                    p={**previous,'id':created['id'],'owner':created['owner'],'approval':None,'job':None,'state':'skeleton_review'}
                    from psycopg.types.json import Jsonb
                    c.app.state.db.execute('UPDATE program_projects SET document=%s WHERE id=%s',(Jsonb(p),p['id']))
                    row.update(resumed=True,previousUsage=previous.get('usage'))
                else:
                    p=post(request=cases[case]);p=wait(p['id'])
                for clarification_round in range(6):
                    if p['state']!='clarification':break
                    chosen={q['field']:(answers if case=='4' else defaults).get(q['field'],q.get('suggestedValue')) for q in p['questions']}
                    if any(x is None for x in chosen.values()):raise ValueError('Требуется решение оператора по полям: '+str([k for k,v in chosen.items() if v is None]))
                    row['testAnswers'].update(chosen)
                    post(action='workflow',id=p['id'],answers=chosen);p=wait(p['id'])
                assert p['state']=='skeleton_review',p.get('job')
                if not row.get('resumed'):row['skeletonSeconds']=round(time.monotonic()-started,2)
                assert not p.get('approval') and (row.get('resumed') or not p.get('materials')),'Нарушена остановка перед согласованием'
                if args.full:
                    post(action='approve',id=p['id'],expectedRevision=p['revision'],confirm=True)
                    post(action='workflow',id=p['id']);p=wait(p['id'])
                    assert (p.get('job') or {}).get('state')=='completed',p.get('job')
                    assert p['report']['passed'],p['report']['errors']
                    for fmt in ('docx','pptx','gift','report','zip'):
                        r=c.post('/api/programs',headers=H,json={'action':'export','id':p['id'],'format':fmt});r.raise_for_status()
                        (output/f'case-{case}.{ "html" if fmt=="report" else fmt}').write_bytes(r.content)
                row.update(success=True,state=p['state'],usage=p['usage'],acceptance=p.get('report',{}).get('acceptance'),warnings=p.get('report',{}).get('warnings'))
            except Exception as error:row.update(success=False,errorType=type(error).__name__,error=str(error)[:2500])
            finally:
                row['seconds']=round(time.monotonic()-started,2)
                if p:(output/f'case-{case}.json').write_text(json.dumps(p,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
                results.append(row);(output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
                (output/f'case-{case}-result.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({k:v for k,v in row.items() if k not in ('usage','acceptance','warnings')},ensure_ascii=False),flush=True)
finally:
    with psycopg.connect(admin,autocommit=True) as conn:conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
raise SystemExit(0 if all(x.get('success') for x in results) else 1)
