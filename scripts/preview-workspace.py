"""Disposable UX preview database; never seeds production data."""
import asyncio
import os
from pathlib import Path
import sys
from uuid import uuid4
from dotenv import load_dotenv
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from psycopg.types.json import Jsonb
import uvicorn

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
load_dotenv(ROOT/'.env')
settings=conninfo_to_dict(os.environ['DATABASE_URL'])
name='edentica_ux_'+uuid4().hex
admin=make_conninfo(**{**settings,'dbname':'postgres'})
with psycopg.connect(admin,autocommit=True) as conn:
    conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING \'UTF8\'').format(sql.Identifier(name)))
try:
    settings['dbname']=name
    with psycopg.connect(make_conninfo(**settings)) as conn:
        conn.execute((ROOT/'backend/schema.sql').read_text(encoding='utf-8'))
        from backend.app import hash_password
        for role in ('methodist','expert','learner'):
            conn.execute('INSERT INTO users(id,name,email,password,login,role) VALUES(%s,%s,%s,%s,%s,%s)',
                         (role,'Проверка интерфейса · '+role,role+'@preview.invalid',hash_password('Preview-test-only-123'),role,role))
        for day in range(30):
            if day%6==0:continue
            conn.execute('''INSERT INTO llm_usage_events
                (id,owner,project_id,provider,model,skill,input_tokens,output_tokens,usage_known,status,created)
                VALUES(%s,'methodist','ux-program','Тестовый стенд','test','module',%s,%s,true,'completed',
                (now() AT TIME ZONE 'Europe/Moscow')::date - (%s * interval '1 day') + interval '12 hours')''',
                (str(uuid4()),(day%5+1)*4200,(day%4+1)*1800,day))
    # Existing classroom fixtures are confined to this temporary database.
    from backend.rules import Rules
    from backend.platform import content_digest
    fixture=asyncio.run(Rules().call('demonstration'))
    for module in fixture['materials'].values():
        for lecture in module['lectures']:
            lecture['content']='Учебный текст временного UX-стенда. '+('Переменная хранит значение. Создайте имя score и присвойте ему число 2. Выведите score + 3 и проверьте, что результат равен 5. Объясните, как изменится результат при другом исходном числе.\n\n'*4)
    config=asyncio.run(Rules().call('config'))
    fixture.update(id='ux-program',owner='methodist',request='Проверка интерфейса',referenceIds=[],requirements={},questions=[],notes=[],revision=1,state='draft_ready',demo=False,history=[],job=None,visibility='public',usage={'inputTokens':0,'outputTokens':0,'calls':0,'estimatedRubles':None},createdAt='2026-10-18T00:00:00Z',updatedAt='2026-10-18T00:00:00Z',sections={s:'Текст для проверки интерфейса' for s in config['templateSections']['general']})
    fixture['approval']={'by':'methodist','at':'2026-10-18T00:00:00Z','digest':asyncio.run(Rules().call('digest',fixture['skeleton'])),'revision':1}
    digest=content_digest(fixture)
    with psycopg.connect(make_conninfo(**settings)) as conn:
        conn.execute('INSERT INTO program_projects(id,owner,document) VALUES(%s,%s,%s)',('ux-program','methodist',Jsonb(fixture)))
        conn.execute('INSERT INTO program_reviews(project_id,expert,digest,status) VALUES(%s,%s,%s,%s)',('ux-program','expert',digest,'approved'))
        conn.execute('INSERT INTO publications(id,project_id,owner,expert,digest,visibility,title,description,snapshot) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',('ux-course','ux-program','methodist','expert',digest,'public',fixture['skeleton']['title'],fixture['skeleton']['goal'],Jsonb(fixture)))
    from urllib.parse import quote
    os.environ.update(DATABASE_URL=f"postgresql://{quote(settings['user'])}:{quote(settings.get('password',''),safe='')}@{settings['host']}:{settings['port']}/{name}",LLM_PROVIDER='cloudru',EDENTICA_MODE='hackathon',HOST='127.0.0.1',PUBLIC_URL='http://localhost:3010',CLOUDRU_API_KEY='',CLOUDRU_MODEL='',LLM_API_KEY='',LLM_MODEL='')
    from backend.app import create_app
    print('Disposable UX preview: localhost:3010; roles methodist/expert/learner; no model calls.',flush=True)
    uvicorn.run(create_app(),host='127.0.0.1',port=3010,log_level='warning')
finally:
    with psycopg.connect(admin,autocommit=True) as conn:
        conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
