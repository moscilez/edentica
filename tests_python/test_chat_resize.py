import copy
import json
from pathlib import Path
from uuid import uuid4
import pytest
from psycopg.types.json import Jsonb
from backend.resize import requested_hours,resize_plan
from backend.validation import inspect_skeleton

H={'X-Edentica':'1'}
BASE=json.loads((Path(__file__).parent/'fixtures/program.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('message',['Увеличь программу с 16 до 24 часов','Измени курс с 16 часов на 24','Сделай программу на 24 часа','Увеличь до 24 часов','Измени объём до 24 часов'])
def test_explicit_total_volume_is_a_course_edit(message):
    assert requested_hours(message)==24

@pytest.mark.parametrize('message',['Что изучают за 24 часа?','Измени часы урока в программе до 24 часов','Добавь пример в урок 2','Увеличь первый урок до 24 часов'])
def test_questions_and_lesson_edits_do_not_resize_a_course(message):
    assert requested_hours(message) is None

def test_relative_hour_change_is_not_confused_with_target_volume():
    assert requested_hours('Увеличь программу на 8 часов',16)==24
    assert requested_hours('Сократи программу на 8 часов',32)==24
    assert requested_hours('Увеличь программу с 16 на 24 часа',16)==24
    assert requested_hours('Увеличь программу на 8 часов') is None

def test_resize_has_exact_hours_and_preserves_competency_content():
    p=copy.deepcopy(BASE);p['requirements']={'minPracticeHours':8,'sessionHours':2,'sessionsPerWeek':2}
    s,req=resize_plan(p,24)
    assert s['totalHours']==24 and s['calendar']['weeks']==6
    assert sum(x['hours'] for x in s['calendar']['sessions'])==24
    assert sum(m['totalHours'] for m in s['modules'])+s['finalHours']==24
    assert req['minPracticeHours']==12
    assert s['competencies']==p['skeleton']['competencies']
    assert not inspect_skeleton(s,req)['errors']
    assert p['skeleton']['totalHours']==16

def test_fixed_schedule_conflict_does_not_silently_extend_deadline():
    from fastapi import HTTPException
    p=copy.deepcopy(BASE);p['requirements']={'sessionHours':2,'sessionsPerWeek':2,'weeks':4}
    with pytest.raises(HTTPException):resize_plan(p,24)
    assert resize_plan(p,24,weeks=6)[0]['calendar']['weeks']==6

def test_resize_preserves_profstandard_evidence_and_mapping_reason():
    from backend.standards import normalize_standard
    p=copy.deepcopy(BASE);p['skeleton']['type']='dpp'
    standard={**normalize_standard({'code':'06.042','functionCode':'A/03.6'}),'mappingReason':'Наблюдаемый результат связан с обработкой данных'}
    for c in p['skeleton']['competencies']:c['standard']=copy.deepcopy(standard)
    planned,_=resize_plan(p,24)
    assert all(c['standard']==standard for c in planned['competencies'])

def test_chat_volume_confirmation_invalidates_old_content_and_restores_requirements(client):
    r=client.post('/api/auth/register',headers=H,json={'login':'resize-'+uuid4().hex,'name':'Тест изменения объёма','password':'Disposable-test-only-123','role':'methodist'})
    assert r.status_code==200
    def action(name,**data):return client.post('/api/agent',headers=H,json={'action':name,**data})
    p=action('demo').json();p['demo']=False
    p['requirements']={k:p['skeleton'][k] for k in ('type','totalHours','audience','entryLevel','format','assessment')}
    client.app.state.db.execute('UPDATE program_projects SET document=%s WHERE id=%s',(Jsonb(p),p['id']))
    assert action('approve',id=p['id'],expectedRevision=p['revision'],confirm=True).status_code==200
    response=action('chat',id=p['id'],message='Увеличь программу с 16 до 24 часов')
    assert response.status_code==200,response.text
    message=response.json()[-1]
    assert message['proposal']['action']=='resize_program'
    legacy={**message['proposal'],'action':'revise_lesson','instruction':'Перераспредели нагрузку'}
    client.app.state.db.execute('UPDATE agent_messages SET proposal=%s WHERE id=%s',(Jsonb(legacy),message['id']))
    assert action('messages',id=p['id']).json()[-1]['proposal']['action']=='resize_program'
    assert action('get',id=p['id']).json()['skeleton']['totalHours']==16
    assert action('apply_proposal',id=p['id'],messageId=message['id'],confirm=False).status_code==422
    changed=action('apply_proposal',id=p['id'],messageId=message['id'],confirm=True)
    assert changed.status_code==200,changed.text
    changed=changed.json()
    assert changed['skeleton']['totalHours']==changed['requirements']['totalHours']==24
    assert changed['approval'] is None and not changed['materials'] and changed['state']=='skeleton_review'
    assert action('generate',id=p['id']).status_code==422
    assert action('apply_proposal',id=p['id'],messageId=message['id'],confirm=True).status_code==409
    restored=action('restore',id=p['id'],revision=p['revision']).json()
    assert restored['requirements']['totalHours']==restored['skeleton']['totalHours']==16


def test_unknown_lesson_does_not_produce_an_unusable_confirmation(client,monkeypatch):
    client.post('/api/auth/register',headers=H,json={'login':'lesson-'+uuid4().hex,'name':'Тест','password':'Disposable-test-only-123','role':'methodist'})
    p=client.post('/api/agent',headers=H,json={'action':'demo'}).json()
    async def reply(*args,**kwargs):
        return {'action':'revise_lesson','message':'Предлагаю изменить урок','lessonIds':['nonexistent-topic-id']}
    monkeypatch.setattr(client.app.state.programs,'call',reply)
    response=client.post('/api/agent',headers=H,json={'action':'chat','id':p['id'],'message':'Измени объяснение в первом уроке'})
    assert response.status_code==200,response.text
    assert response.json()[-1]['proposal']['action']=='answer'
    assert 'Уточните' in response.json()[-1]['message']
