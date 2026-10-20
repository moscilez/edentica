"""In-process educational invariants. No network, model or child process."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CONFIG=json.loads((Path(__file__).parent/'resources/skills.json').read_text(encoding='utf-8'))
SECTIONS=CONFIG['templateSections']
KINDS=('lecture','practice','lab','self')


def text(value,maximum=10000):
    return isinstance(value,str) and 0<len(value.strip())<=maximum and not re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value)


def integer(value):return type(value) is int
def total(hours):return sum(v for k in KINDS if integer(v:=(hours or {}).get(k)))
def issue(code,path,message):return {'code':code,'path':path,'message':message}


def digest(value):
    def normalize(v):
        if isinstance(v,float) and v.is_integer():return int(v)
        if isinstance(v,dict):return {k:normalize(x) for k,x in v.items()}
        if isinstance(v,list):return [normalize(x) for x in v]
        return v
    return hashlib.sha256(json.dumps(normalize(value),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def inspect_skeleton(s,requirements=None):
    errors=[];warnings=[];requirements=requirements or {}
    def bad(code,path,message):errors.append(issue(code,path,message))
    try:
        if not isinstance(s,dict):raise TypeError()
        if s.get('type') not in SECTIONS:bad('template','type','Выберите один из двух шаблонов АЦР')
        for key in ('title','goal','audience','entryLevel','format','assessment'):
            if not text(s.get(key),4000):bad('required',key,'Не заполнено поле '+key)
        if not integer(s.get('totalHours')) or not 16<=s['totalHours']<=10000:bad('hours','totalHours','Объём: целое число от 16 до 10000 часов')
        for key,code in [('totalHours','requested_hours'),('type','requested_type')]:
            if requirements.get(key) and s.get(key)!=requirements[key]:bad(code,key,'Значение не совпадает с запросом')
        if requirements.get('selfStudyOnly') and not s.get('selfStudyOnly'):bad('requested_delivery','selfStudyOnly','Запрошена стажировка без контактной работы')
        competencies=s.get('competencies');modules=s.get('modules')
        if not isinstance(competencies,list) or not 1<=len(competencies)<=40:raise TypeError()
        if not isinstance(modules,list) or not 1<=len(modules)<=40:raise TypeError()
        ids=set()
        for i,c in enumerate(competencies):
            path=f'competencies.{i}'
            if not text(c.get('id'),80) or c['id'] in ids:bad('id',path,'Код компетенции должен быть уникальным')
            ids.add(c.get('id'))
            for key in ('title','knowledge','abilities','skills'):
                if not text(c.get(key),3000):bad('competency',path+'.'+key,'Заполните результат и знания, умения, навыки')
            standard=c.get('standard') or {}
            if s.get('type')=='general' and standard:bad('standard',path,'Общеразвивающая программа не требует трудовых функций')
            if s.get('type')=='dpp' and not (standard.get('code') and standard.get('functionCode')):warnings.append(issue('standard_missing',path,'Профстандарт и трудовая функция требуют подтверждения'))
            if standard:
                from .standards import CATALOG,standard_issue
                if not re.fullmatch(r'\d{2}\.\d{3}',str(standard.get('code',''))):bad('standard_invalid',path,'Некорректный код профстандарта')
                elif any(x['code']==standard.get('code') for x in CATALOG) and standard_issue(standard):bad('standard_invalid',path,standard_issue(standard))
                elif standard_issue(standard):warnings.append(issue('standard_review',path,standard_issue(standard)))
        module_ids=set();topic_ids=set();covered=set();module_hours=0;practical=0;topic_hours={}
        for mi,m in enumerate(modules):
            path=f'modules.{mi}'
            if not text(m.get('id'),80) or m['id'] in module_ids:bad('id',path,'Уникальный код модуля обязателен')
            module_ids.add(m.get('id'))
            if not text(m.get('title'),300):bad('title',path,'Название модуля обязательно')
            if not isinstance(m.get('topics'),list) or not 1<=len(m['topics'])<=30:raise TypeError()
            hours=0
            for ti,t in enumerate(m['topics']):
                p=f'{path}.topics.{ti}';h=t.get('hours') or {}
                if not text(t.get('id'),80) or t['id'] in topic_ids:bad('id',p,'Код темы должен быть уникальным')
                topic_ids.add(t.get('id'))
                if not text(t.get('title'),300):bad('title',p,'Название темы обязательно')
                for key in KINDS:
                    if not integer(h.get(key)) or h[key]<0:bad('hours',p+'.hours.'+key,'Часы — неотрицательные целые числа')
                n=total(h);hours+=n;topic_hours[t.get('id')]=n
                if n<=0:bad('hours',p,'Тема не может иметь нулевой объём')
                if t.get('totalHours')!=n:bad('topic_sum',p,'Сумма видов работы не равна объёму темы')
                references=t.get('competencyIds')
                if not isinstance(references,list) or not references:bad('coverage',p,'Свяжите тему с результатом обучения');references=[]
                for cid in references:
                    if cid not in ids:bad('reference',p,'Неизвестная компетенция '+str(cid))
                    else:covered.add(cid)
                contact=sum(h.get(k,0) for k in KINDS[:3]);practical+=h.get('practice',0)+h.get('lab',0)
                if s.get('selfStudyOnly') and contact:bad('internship_contact',p,'В стажировке контактная работа должна равняться нулю')
                delivery=t.get('delivery')
                if delivery:
                    if any(not integer(delivery.get(k)) or delivery[k]<0 for k in ('inPerson','remote')) or sum(delivery.get(k,0) for k in ('inPerson','remote'))!=contact:bad('delivery',p,'Очная и дистанционная работа не совпадают с контактными часами')
                elif re.search('заочн|дистанц',s.get('format',''),re.I):bad('delivery',p,'Укажите очные и дистанционные часы')
            if m.get('totalHours')!=hours:bad('module_sum',path,'Сумма тем не равна объёму модуля')
            module_hours+=hours
        final=s.get('finalHours')
        if not integer(final) or not 1<=final<=s.get('totalHours',0):bad('final','finalHours','Укажите часы итоговой аттестации')
        if module_hours+(final or 0)!=s.get('totalHours'):bad('total_sum','totalHours','Сумма модулей и аттестации не равна запрошенному объёму')
        for cid in ids-covered:bad('coverage',cid,'Компетенция не раскрыта ни в одной теме')
        if practical<requirements.get('minPracticeHours',0):bad('practice','modules','Недостаточно практических часов')
        calendar=s.get('calendar') or {};sessions=calendar.get('sessions')
        if not integer(calendar.get('weeks')) or calendar['weeks']<1 or not isinstance(sessions,list) or not 1<=len(sessions)<=10000:bad('calendar','calendar','Укажите недели и занятия календаря')
        else:
            allocated={}
            for row in sessions:
                refs=row.get('topicIds')
                if not integer(row.get('hours')) or row['hours']<1 or not integer(row.get('week')) or not 1<=row['week']<=calendar['weeks'] or not isinstance(refs,list) or any(x not in topic_ids|{'final'} for x in refs):bad('calendar_reference','calendar','Проверьте часы, недели и ссылки календаря')
                parts=row.get('allocations')
                if parts is None and isinstance(refs,list) and len(refs)==1:parts=[{'topicId':refs[0],'hours':row.get('hours',0)}]
                if not isinstance(parts,list) or not parts or any(not isinstance(x,dict) or x.get('topicId') not in topic_ids|{'final'} or not integer(x.get('hours')) or x['hours']<=0 for x in parts):
                    bad('calendar_allocation','calendar','Нужна разбивка часов занятия по темам')
                else:
                    if sum(x['hours'] for x in parts)!=row.get('hours') or [x['topicId'] for x in parts]!=refs:bad('calendar_allocation','calendar','Распределение тем не совпадает с часами занятия')
                    for part in parts:allocated[part['topicId']]=allocated.get(part['topicId'],0)+part['hours']
            if sum(row.get('hours',0) for row in sessions)!=s.get('totalHours'):bad('calendar_sum','calendar','Сумма календаря не равна объёму программы')
            for tid,hours in topic_hours.items():
                if allocated.get(tid)!=hours:bad('calendar_topic',tid,'Календарные часы не совпадают с тематическим планом')
            if allocated.get('final')!=final:bad('calendar_final','calendar','Календарные часы аттестации не совпадают')
            if requirements.get('weeks') and calendar['weeks']!=requirements['weeks']:bad('calendar_weeks','calendar','Число недель не совпадает с запросом')
        from .acceptance import inspect_constraints
        errors+=inspect_constraints(s,requirements)
        return {'errors':errors,'warnings':warnings,'totalHours':module_hours+(final or 0),'practicalHours':practical}
    except (TypeError,KeyError,AttributeError,ValueError):
        return {'errors':errors+[issue('schema','skeleton','Неверная структура каркаса: проверьте компетенции, модули, темы и календарь')],'warnings':warnings}


def inspect_module(content,module,skeleton,allow_empty_questions=False):
    errors=[]
    def bad(message):errors.append(issue('content',module.get('id','module'),message))
    try:
        if not isinstance(content,dict) or content.get('moduleId')!=module['id']:bad('Ответ относится к другому модулю');return errors
        topic_ids={t['id'] for t in module['topics']};competency_ids={c for t in module['topics'] for c in t['competencyIds']}
        for key in ('summary','methodology'):
            if not text(content.get(key),30000):bad('Не заполнено '+key)
        for kind in ('questions','seminars','lectures'):
            items=content.get(kind)
            if kind=='questions' and allow_empty_questions and items==[]:continue
            if not isinstance(items,list) or not 1<=len(items)<=150:bad('Не заполнены '+kind);continue
            ids=set()
            for item in items:
                if not text(item.get('id'),80) or item['id'] in ids:bad('Повтор или отсутствие кода материала')
                ids.add(item.get('id'))
                if item.get('topicId') not in topic_ids:bad('Материал ссылается на тему вне модуля')
                linked=next((t for t in module['topics'] if t['id']==item.get('topicId')),None)
                if not isinstance(item.get('competencyIds'),list) or not item['competencyIds'] or any(c not in (linked or {}).get('competencyIds',[]) for c in item['competencyIds']):bad('Неверная привязка к результатам именно этой темы')
                if kind=='questions':
                    options=item.get('options')
                    if not text(item.get('text'),4000) or not isinstance(options,list) or not 2<=len(options)<=10 or any(not text(x,2000) for x in options) or not integer(item.get('answer')) or not 0<=item['answer']<len(options) or not text(item.get('explanation'),4000):bad('Тест требует вариантов ответа, корректного ключа и объяснения')
                if kind=='seminars':
                    if any(not text(item.get(k),limit) for k,limit in [('title',300),('task',20000),('deliverable',6000)]) or not valid_criteria(item.get('criteria')):bad('Задание требует результата и критериев суммарно на 100 баллов')
                if kind=='lectures':
                    slides=item.get('slides')
                    if not text(item.get('title'),300) or not text(item.get('plan'),20000) or not isinstance(slides,list) or not 1<=len(slides)<=20 or any(not all(text(x.get(k),n) for k,n in [('title',180),('text',650),('notes',10000)]) for x in slides):bad('Лекция требует плана и слайдов с заметками')
                    if not text(item.get('content'),60000) or len(item.get('content',''))<200:bad('Нужен полный учебный текст лекции, а не только план (не менее 200 символов)')
        for t in module['topics']:
            if not any(x.get('topicId')==t['id'] for x in content.get('lectures',[])):bad('Нет учебного материала темы '+t['id'])
        for item in content.get('interviews',[]):
            linked=next((t for t in module['topics'] if t['id']==item.get('topicId')),None)
            if not linked or not item.get('competencyIds') or set(item['competencyIds'])-set(linked['competencyIds']) or not text(item.get('text'),4000) or not text(item.get('expectedAnswer'),6000) or not valid_criteria(item.get('criteria')):bad('Собеседование требует темы, результата, ожидаемого ответа и критериев на 100 баллов')
    except (TypeError,KeyError,AttributeError,ValueError):bad('Некорректная структура материалов модуля')
    return errors


def valid_criteria(items):
    return isinstance(items,list) and len(items)>=2 and all(isinstance(x,dict) and text(x.get('title'),1000) and integer(x.get('points')) and x['points']>0 for x in items) and sum(x['points'] for x in items)==100


def inspect_sections(value,titles):
    if not isinstance(value,dict) or not isinstance(value.get('sections'),dict):return ['sections должен быть объектом с точными названиями разделов']
    errors=['Не заполнен раздел: '+title for title in titles if not text(value['sections'].get(title),30000)]
    final=value.get('finalAssessment') or {}
    if not isinstance(final,dict) or not text(final.get('title'),300) or not text(final.get('task'),20000) or not text(final.get('deliverable'),6000) or not valid_criteria(final.get('criteria')):errors.append('Нужны итоговое задание, результат и критерии на 100 баллов')
    return errors


def inspect_program(p):
    s=p.get('skeleton') or {};r=inspect_skeleton(s,p.get('requirements'));coverage=[]
    try:
        for c in s.get('competencies',[]):
            coverage.append({'id':c['id'],'title':c['title'],'topics':[t['id'] for m in s.get('modules',[]) for t in m['topics'] if c['id'] in t['competencyIds']],'questions':[],'assignments':[]})
        for m in s.get('modules',[]):
            content=p.get('materials',{}).get(m['id'])
            if not content:r['errors'].append(issue('missing_module',m['id'],'Комплект модуля ещё не подготовлен'));continue
            r['errors']+=inspect_module(content,m,s,allow_empty_questions=(p.get('requirements') or {}).get('currentControl')=='interview' or (p.get('requirements') or {}).get('testQuestionCount') is not None)
            for c in coverage:
                for kind,key in [('questions','questions'),('seminars','assignments')]:
                    c[key]+=[m['id']+':'+q['id'] for q in content.get(kind,[]) if c['id'] in q.get('competencyIds',[])]
                c['questions']+=[m['id']+':'+q['id'] for q in content.get('interviews',[]) if c['id'] in q.get('competencyIds',[])]
        requested=(p.get('requirements') or {}).get('testQuestionCount')
        if requested and sum(len(m.get('questions',[])) for m in p.get('materials',{}).values())!=requested:r['errors'].append(issue('question_count','materials','Количество тестовых вопросов не совпадает с запросом'))
        for c in coverage:
            if not c['questions'] or not c['assignments']:r['errors'].append(issue('assessment_coverage',c['id'],'Нужны тестовый вопрос и задание на каждый результат обучения'))
        for title in SECTIONS.get(s.get('type'),[]):
            if not text(p.get('sections',{}).get(title),30000):r['errors'].append(issue('section',title,'Не заполнен раздел шаблона'))
        f=p.get('finalAssessment') or {}
        if not text(f.get('task'),20000) or not valid_criteria(f.get('criteria')):r['errors'].append(issue('final_assessment','finalAssessment','Нужны итоговое задание и критерии на 100 баллов'))
    except (TypeError,KeyError,AttributeError,ValueError):r['errors'].append(issue('schema','materials','Некорректная структура комплекта'))
    sources=[{**x,'status':(x.get('verification') or {}).get('status','unverified')} for x in p.get('sources',[]) if isinstance(x,dict)]
    if p.get('referenceStatus',{}).get('mentionedButMissing'):r['warnings'].append(issue('reference_missing','referenceIds','Референс упомянут, но не прикреплён: использован стандартный шаблон, а не структура невидимого файла'))
    for source in sources:
        if source['status']=='rejected':r['errors'].append(issue('source_rejected',source.get('id',''),'Отклонённый источник нужно заменить или удалить: '+source.get('title','')))
        if source['status']!='confirmed':r['warnings'].append(issue('source_unverified',source.get('id',''),'Источник не подтверждён: '+source.get('title','')))
        if (source.get('accessCheck') or {}).get('access') in ('unavailable','invalid_url'):
            r['warnings'].append(issue('source_unavailable',source.get('id',''),'Источник недоступен или URL некорректен: '+source.get('title','')))
    if not sources:r['warnings'].append(issue('sources_missing','sources','Список литературы не заполнен'))
    for c in s.get('competencies',[]):
        if s.get('type')=='dpp' and not c.get('standard'):r['warnings'].append(issue('standard_missing',c.get('id',''),'Профстандарт и код трудовой функции не подтверждены'))
    structural_passed=not r['errors'];acceptance=[]
    if s.get('constraintVersion',0)>=3:
        from .acceptance import inspect_acceptance
        from .standards import standard_issue
        acceptance=inspect_acceptance(p)
        for row in acceptance:
            if row['status']=='failed':r['errors'].append(issue('requirement',row['id'],row['title']+': '+str(row['evidence'])))
        if s.get('type')=='dpp':
            for c in s.get('competencies',[]):
                problem=standard_issue(c.get('standard'))
                if problem:r['warnings'].append(issue('standard_review',c['id'],problem))
        from .regulations import section_policy_issues
        for problem in section_policy_issues({'sections':p.get('sections',{})},s.get('type')):r['errors'].append(issue('regulation','sections',problem))
    r.update(coverage=coverage,sources=sources,acceptance=acceptance,structuralPassed=structural_passed,
             checkedAt=datetime.now(timezone.utc).isoformat(),passed=not r['errors'],draft=True)
    return r
