"""Independent acceptance of user constraints; no LLM self-approval."""
from collections import Counter
from .planning import concept_present,normalize,duplicates_final
from .canonical import numeric_sections

def inspect_constraints(s,requirements):
    errors=[]
    def bad(path,message):errors.append({'code':'requirement','path':path,'message':message})
    topics=[t for m in s.get('modules',[]) for t in m.get('topics',[])]
    titles=[normalize(t.get('title','')) for t in topics]
    if len(titles)!=len(set(titles)):bad('modules','Обнаружены повторяющиеся темы')
    if any(duplicates_final(t) for t in titles) or any(duplicates_final(m.get('title','')) for m in s.get('modules',[])):bad('modules','Проведение итоговой аттестации продублировано в учебных модулях')
    context=[m.get('title','')+' '+t.get('title','') for m in s.get('modules',[]) for t in m.get('topics',[])]
    for name in requirements.get('requiredTopics',[]):
        if not any(concept_present(name,t) for t in context):bad('modules','Нет обязательной темы: '+name)
    sessions=s.get('calendar',{}).get('sessions',[])
    if requirements.get('sessionHours') and any(x.get('hours')!=requirements['sessionHours'] for x in sessions):bad('calendar','Нарушена длительность занятий')
    counts=Counter(x.get('week') for x in sessions)
    frequency=requirements.get('sessionsPerWeek')
    if frequency and (any(n>frequency for n in counts.values()) or any(n!=frequency for week,n in counts.items() if week<s.get('calendar',{}).get('weeks',0))):bad('calendar','Нарушена частота занятий в неделю')
    days=Counter()
    for x in sessions:
        if s.get('constraintVersion',0)>=3 and (type(x.get('day')) is not int or not 1<=x['day']<=7):bad('calendar','Нужен учебный день от 1 до 7')
        days[(x.get('week'),x.get('day'))]+=x.get('hours',0)
    limit=requirements.get('maxHoursPerDay')
    if (s.get('constraintVersion',0)>=3 or any(x.get('day') for x in sessions)) and any(h>24 for h in days.values()):bad('calendar','Нагрузка не может превышать 24 часа в день')
    if limit and any(h>limit for h in days.values()):bad('calendar','Превышена дневная нагрузка')
    if requirements.get('finalHours') and s.get('finalHours')!=requirements['finalHours']:bad('finalHours','Часы итоговой аттестации не совпадают с запросом')
    return errors

def inspect_acceptance(program):
    s=program.get('skeleton') or {};req=program.get('requirements') or {};checks=[]
    def check(key,title,ok,evidence,pending=False):
        checks.append({'id':key,'title':title,'status':'pending' if pending else 'passed' if ok else 'failed','evidence':evidence})
    errors=inspect_constraints(s,req)
    check('constraints','Требования к темам и календарю',not errors,[x['message'] for x in errors] or ['Явные ограничения соблюдены'])
    for title,value in numeric_sections(s).items():
        if title in program.get('sections',{}):
            check('section:'+title,title,program['sections'][title]==value,'Текст рассчитан из согласованного плана')
    materials=list(program.get('materials',{}).values());complete=bool(program.get('sections'))
    count=req.get('portfolioItems')
    if count:
        items=(program.get('finalAssessment') or {}).get('items',[])
        check('portfolio','Состав итогового портфолио',len(items)==count and all(isinstance(x,dict) and x.get('title') and x.get('requirements') for x in items),f'Требуется {count}; подготовлено {len(items)}',not complete)
    if req.get('currentControl') in ('interview','mixed'):
        needed={t['id'] for m in s.get('modules',[]) for t in m['topics']}
        actual={q.get('topicId') for m in materials for q in m.get('interviews',[])}
        check('interviews','Собеседования по всем разделам',needed<=actual,'Темы без собеседования: '+', '.join(sorted(needed-actual)),not complete)
    lecture_topics={l.get('topicId') for m in materials for l in m.get('lectures',[]) if l.get('slides')}
    wanted=set()
    for row in s.get('calendar',{}).get('sessions',[])[:req.get('slidesForSessions') or 0]:wanted.update(set(row.get('topicIds',[]))-{'final'})
    for m in s.get('modules',[]):
        if any(concept_present(name,m['title']+' '+' '.join(t['title'] for t in m['topics'])) for name in req.get('slidesForTopics',[])):
            wanted.update(t['id'] for t in m['topics'])
    if wanted:check('slides','Слайды запрошенных занятий и модулей',wanted<=lecture_topics,'Темы без слайдов: '+', '.join(sorted(wanted-lecture_topics)),not complete)
    domain_sources=[x for x in program.get('sources',[]) if x.get('kind') in ('documentation','literature')]
    check('bibliography','Предметная литература',bool(domain_sources),'Источников по теме: '+str(len(domain_sources)),not complete)
    if s.get('type')=='dpp':
        from .standards import standard_issue
        for c in s.get('competencies',[]):
            problem=standard_issue(c.get('standard'))
            check('standard:'+c['id'],'Реквизиты профстандарта для '+c['id'],not problem,
                problem or 'Код и функция найдены в документе; тематическую применимость и актуальность утверждает эксперт.',bool(problem))
    if req.get('russiaOnlyServices'):
        import re,json
        body=json.dumps({'materials':materials,'sections':program.get('sections',{})},ensure_ascii=False)
        prohibited=re.findall(r'\b(?:ChatGPT|Claude|Midjourney|Gemini|DALL[ -]?E)\b',body,re.I)
        # A denial/comparison is not an instruction to use a service. Require explicit Russian alternatives.
        usage=re.search(r'(?:войдите|зарегистрируйтесь|используйте|откройте|воспользуйтесь)[^.!?]{0,80}\b(?:ChatGPT|Claude|Midjourney|Gemini)\b',body,re.I)
        check('services','Сервисы для аудитории в России',not usage,'Найдены указания использовать ограниченный сервис' if usage else 'Запрещённые указания не обнаружены; доступность подтверждает эксперт',not complete)
    return checks
