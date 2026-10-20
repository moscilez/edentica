"""User briefs and adversarial mutations, independent of live model wording."""
import copy,json
from pathlib import Path
from io import BytesIO
from docx import Document
import pytest
from backend.planning import explicit_requirements,merge_requirements,build_skeleton,calendar_for
from backend.validation import inspect_skeleton,inspect_program
from backend.canonical import canonicalize_sections
from backend.acceptance import inspect_acceptance
from backend.docx_export import build
from backend.standards import normalize_standard,standard_issue
from backend.exports import slide_targets

CASES=json.loads((Path(__file__).parent/'fixtures/case-requests.json').read_text(encoding='utf-8'))
BASE=json.loads((Path(__file__).parent/'fixtures/program.json').read_text(encoding='utf-8'))

def outline(topics):
    c=copy.deepcopy(BASE['skeleton']['competencies'][0]);c['id']='C1'
    return {'title':'Учебная программа','goal':'Выполнять проверяемую задачу соответствующего уровня',
        'competencies':[c],'modules':[{'title':'Основные темы','topics':[{'title':t,'competencyIds':['C1']} for t in topics]}]}

def req(case):
    return {'type':'dpp','totalHours':72,'audience':'Слушатели','entryLevel':'Начальный',
            'format':'Очная','assessment':'Проект',**explicit_requirements(CASES[str(case)])}

@pytest.mark.parametrize('case',[1,2,3,5])
def test_exact_brief_constraints_are_preserved(case):
    r=req(case);s=build_skeleton(outline(r['requiredTopics']),r)
    assert not inspect_skeleton(s,r)['errors']
    assert sum(x['hours'] for x in s['calendar']['sessions'])==r['totalHours']
    if case==1:
        assert len(s['calendar']['sessions'])==8 and s['calendar']['weeks']==4
        assert all(x['hours']==2 for x in s['calendar']['sessions'])
        assert sum(t['hours']['practice'] for m in s['modules'] for t in m['topics'])>=8
        assert r['testQuestionCount']==10 and r['slidesForSessions']==2
    elif case==2:assert r['portfolioItems']==3 and r['russiaOnlyServices']
    elif case==3:assert s['calendar']['weeks']==4 and 'SQL' in r['requiredTopics'] and r['slidesForTopics']==['pandas']
    elif case==5:
        assert max(x['hours'] for x in s['calendar']['sessions'])<=4
        assert sum(t['hours']['self'] for m in s['modules'] for t in m['topics'])==254
        assert all(t['hours']['lecture']==t['hours']['practice']==t['hours']['lab']==0 for m in s['modules'] for t in m['topics'])
        assert r['currentControl']=='interview'
        assert any('подтвердите календарь' in x for x in s['assumptions'])

def test_incomplete_cyber_brief_cannot_be_invented_by_model():
    guessed=req(3)
    actual,provenance=merge_requirements(CASES['4'],guessed)
    assert all(not actual.get(k) for k in ('type','totalHours','entryLevel','format','assessment'))
    actual,_=merge_requirements(CASES['4'],guessed,answers={'type':'dpp','totalHours':72,'entryLevel':'3 курс СПО, сети и Linux','format':'Очная','assessment':'Практический экзамен на стенде'})
    assert actual['totalHours']==72 and actual['assessment']=='Практический экзамен на стенде'

@pytest.mark.parametrize('mutation',['duration','frequency','daily','topic','final','allocation'])
def test_mutations_previously_passing_are_rejected(mutation):
    r=req(1);r['maxHoursPerDay']=2;s=build_skeleton(outline(['Python']),r)
    if mutation=='duration':s['calendar']['sessions'][0]['hours']=1
    if mutation=='frequency':s['calendar']['sessions'][2]['week']=1
    if mutation=='daily':s['calendar']['sessions'][1]['day']=1
    if mutation=='topic':s['modules'][0]['topics'][0]['title']='Работа с таблицами'
    if mutation=='final':s['finalHours']=3
    if mutation=='allocation':s['calendar']['sessions'][0]['allocations'][0]['hours']=999
    assert inspect_skeleton(s,r)['errors']

def test_strict_infeasible_deadline_requires_human_change():
    r=req(5);r.update(weeks=8,daysPerWeek=7)
    with pytest.raises(ValueError,match='семи|помещаются'):build_skeleton(outline(r['requiredTopics']),r)

@pytest.mark.parametrize('hours,session,frequency',[(18,3,2),(40,4,5),(120,6,4),(500,5,5)])
def test_unseen_volumes_and_schedules(hours,session,frequency):
    r={'type':'general','totalHours':hours,'audience':'Взрослые','entryLevel':'Начальный','format':'Очная','assessment':'Проект','sessionHours':session,'sessionsPerWeek':frequency}
    s=build_skeleton(outline(['Алгоритмы и структуры данных']),r)
    assert not inspect_skeleton(s,r)['errors']
    assert all(x['hours']==session for x in s['calendar']['sessions'])

def test_word_totals_equal_types_including_final_and_wrong_prose_is_detected():
    r=req(5);s=build_skeleton(outline(r['requiredTopics']),r)
    p=copy.deepcopy(BASE);p.update(skeleton=s,requirements=r,materials={},sections=canonicalize_sections({'Учебный план':'9999 часов','Учебно-тематический план':'9999 часов'},s))
    doc=Document(BytesIO(build(p)))
    plans=[t for t in doc.tables if t.rows[0].cells[0].text=='Модуль или тема']
    assert len(plans)==2
    for t in plans:
        for row in list(t.rows)[1:]:
            values=[int(c.text) for c in row.cells[1:]]
            assert values[0]==sum(values[1:])
        assert [c.text for c in t.rows[-1].cells[2:5]]==['0','0','0']
    p['sections']['Учебный план']='9999 часов'
    assert any(x['status']=='failed' for x in inspect_acceptance(p))

def test_portfolio_and_oral_control_are_acceptance_requirements():
    r=req(2);p=copy.deepcopy(BASE);p.update(requirements=r,skeleton=build_skeleton(outline(r['requiredTopics']),r),sections={'Оценочные материалы':'Комплект подготовлен'})
    assert next(x for x in inspect_acceptance(p) if x['id']=='portfolio')['status']=='failed'
    p['finalAssessment']['items']=[{'title':str(i),'requirements':'Проверяемый учебный материал'} for i in range(3)]
    assert next(x for x in inspect_acceptance(p) if x['id']=='portfolio')['status']=='passed'
    p['requirements']['currentControl']='interview'
    assert next(x for x in inspect_acceptance(p) if x['id']=='interviews')['status']=='failed'

def test_profstandard_function_pair_cannot_be_approved_by_model_flag():
    assert standard_issue({'code':'06.042','functionCode':'ZZ/999.9','status':'verified'})
    good=normalize_standard({'code':'06.042','functionCode':'А/03.6'})
    assert good['functionCode']=='A/03.6' and good['status']=='scope_requires_expert_review'
    r=req(3);s=build_skeleton(outline(r['requiredTopics']),r)
    s['competencies'][0]['standard']={'code':'999.999','functionCode':'ZZ/999.9','status':'verified'}
    assert any(x['code']=='standard_invalid' for x in inspect_skeleton(s,r)['errors'])

def test_slide_export_mapping_matches_calendar_and_requested_module():
    r=req(1);p={'requirements':r,'skeleton':build_skeleton(outline(['Python']),r)}
    targets=slide_targets(p)
    assert len(targets)==2 and all(x['topicIds']==['T1.1'] for x in targets)
    r=req(3);p={'requirements':r,'skeleton':build_skeleton(outline(r['requiredTopics']),r)}
    assert slide_targets(p)[0]['moduleId']=='M1'

@pytest.mark.parametrize('text',['Приказ Минсельхоза России от 27.07.2022 № 629','Приказ Минпросвещения России от 01.01.2099 № 629'])
def test_known_number_does_not_validate_invented_issuer_or_date(text):
    from backend.regulations import section_policy_issues
    assert section_policy_issues({'sections':{'Основания':text}},'general')

def test_unrelated_topic_competency_cannot_fake_coverage():
    from backend.validation import inspect_module
    p=copy.deepcopy(BASE);m=next(iter(p['skeleton']['modules']));content=p['materials'][m['id']]
    m['topics'].append({**m['topics'][0],'id':'different','competencyIds':['FOREIGN']})
    content['questions'][0]['competencyIds']=['FOREIGN']
    assert inspect_module(content,m,p['skeleton'])

def test_provider_optional_shapes_preserve_content_without_inventing_fields():
    s=outline(['Python']);s['assumptions']={'description':'Базовая компьютерная грамотность','status':'согласовано'}
    s['modules'][0]['topics'][0]['text']=s['modules'][0]['topics'][0].pop('title')
    planned=build_skeleton(s,req(1))
    assert planned['modules'][0]['topics'][0]['title']=='Python'
    assert all('согласовано' not in a for a in planned['assumptions'])
    from backend.programs import intake_issues
    data={'requirements':{'type':'повышение квалификации','minPracticeHours':None},'questions':[],'notes':[]}
    assert not intake_issues(data)
    assert data['requirements']['type']=='dpp' and 'minPracticeHours' not in data['requirements']

def test_model_invented_numbers_do_not_constrain_a_program():
    actual,_=merge_requirements(CASES['3'],{'type':'dpp','totalHours':999,'weeks':1,'minPracticeHours':70,'testQuestionCount':100})
    assert actual['totalHours']==72 and actual['weeks']==4
    assert actual['minPracticeHours']==0 and not actual.get('testQuestionCount')

def test_model_contracts_do_not_ask_supported_models_to_repeat_json_schema():
    from backend.skills import instructions
    from backend.validation import CONFIG
    skills=instructions(CONFIG)
    assert all('"$defs"' not in skills[k] and '"properties":' not in skills[k] for k in ('outline','lesson','assessment'))

def test_score_scale_is_calculated_from_positive_weights_and_invalid_values_stay_invalid():
    from backend.canonical import normalize_criteria
    weighted=[{'title':'Работающий результат','points':4},{'title':'Объяснение решения','points':2}]
    result=normalize_criteria(weighted)
    assert sum(x['points'] for x in result)==100 and result[0]['points']>result[1]['points']
    assert [x['originalWeight'] for x in result]==[4,2]
    invalid=[{'title':'Первый','points':-2},{'title':'Второй','points':1}]
    assert normalize_criteria(invalid)==invalid

@pytest.mark.parametrize('brief',['ДПП 96 часов по администрированию','96-часовой общеразвивающий курс','Повышение квалификации: 120 ч.'])
def test_unseen_hour_phrasings_are_not_lost(brief):
    assert explicit_requirements(brief)['totalHours']==(120 if '120' in brief else 96)

def test_natural_text_answers_are_normalized_without_guessing_numbers():
    r,provenance=merge_requirements(CASES['4'],{},answers={'type':'Повышение квалификации','hours':'72 часа','level':'Сети и Linux','format':'Очная','assessment':'Экзамен'})
    assert r['type']=='dpp' and r['totalHours']==72 and r['entryLevel']=='Сети и Linux'
    assert provenance['entryLevel']=='user_answer'

@pytest.mark.parametrize('title',['Итоговая аттестация и защита отчёта','Защита отчёта перед комиссией (2 часа)','Итоговый экзамен'])
def test_final_assessment_cannot_be_hidden_in_self_study_modules(title):
    r=req(5);o=outline(r['requiredTopics']);o['modules'].append({'title':title,'topics':[{'title':'Подготовка отчёта','competencyIds':['C1']}]})
    s=build_skeleton(o,r)
    assert s['planningChanges'] and s['modules'][-1]['title']=='Подготовка итоговой работы'
    assert not inspect_skeleton(s,r)['errors']
    s['modules'][-1]['topics'][0]['title']='Защита отчёта'
    assert any(x['code']=='requirement' for x in inspect_skeleton(s,r)['errors'])

def test_incompatible_duration_is_a_question_before_model_outline():
    from backend.planning import schedule_question
    r=req(5);q=schedule_question(r)
    assert q['field']=='weeks' and q['suggestedValue']==13 and '64' in q['question']
    assert schedule_question({**r,'weeks':13}) is None
    q=schedule_question({**r,'weeks':8,'daysPerWeek':7})
    assert q and q['suggestedValue']==10
    assert schedule_question(req(1)) is None

def test_unseen_practice_percent_and_daily_schedule():
    r=explicit_requirements('Общеразвивающая программа на 40 часов. Практики не менее 60%. Учимся 4 дня в неделю.')
    assert r['minPracticeHours']==24 and r['daysPerWeek']==4


def test_missing_competency_repair_preserves_existing_graph_and_rejects_wrong_ids():
    from backend.planning import unresolved_competencies,repair_competencies
    from backend.output_contracts import schema_for
    original=outline(['Python']);before=copy.deepcopy(original)
    original['modules'][0]['topics'][0]['competencyIds'].append('C-missing')
    assert unresolved_competencies(original)==['C-missing']
    definition={**original['competencies'][0],'id':'C-missing','title':'Применять Python в заданной теме'}
    repaired=repair_competencies(original,[definition])
    assert not unresolved_competencies(repaired)
    assert repaired['modules']==original['modules']
    assert repaired['competencies'][:-1]==before['competencies']
    assert len(original['competencies'])==len(before['competencies'])
    for values in ([],[original['competencies'][0]],[definition,definition]):
        with pytest.raises(ValueError):repair_competencies(original,values)
    schema=schema_for('competency_repair',{'missingIds':['C-missing']})
    assert schema['properties']['competencies']['minItems']==1
    assert schema['properties']['competencies']['items']['properties']['id']['enum']==['C-missing']


def test_cybersecurity_requirement_accepts_security_modules_without_literal_course_name():
    from backend.planning import concept_present
    assert concept_present('кибербезопасность','Основы сетевой безопасности и защиты данных')
    assert concept_present('Кибербезопасность','Информационная безопасность и управление доступом')
    assert not concept_present('кибербезопасность','Python: списки и визуализация таблиц')
    planned=build_skeleton(outline(['Основы информационной безопасности']),{**req(4),'requiredTopics':['кибербезопасность']})
    assert planned['modules'][0]['topics']
