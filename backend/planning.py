"""General request constraints and exact arithmetic; never model-generated hours."""
import math
import re
import copy
from .contracts import Outline, Requirements

NUMBERS={'один':1,'одного':1,'два':2,'две':2,'двух':2,'три':3,'трех':3,
         'четыре':4,'четырех':4,'пять':5,'пяти':5,'шесть':6,'шести':6,'семь':7,'семи':7,
         'восемь':8,'восьми':8,'девять':9,'десять':10,'десяти':10}
NUMBER=r'(\d{1,4}|'+'|'.join(NUMBERS)+r')'
def number(value):return int(value) if value.isdigit() else NUMBERS[value]

# Concepts, not canned courses: also used for unseen request checks.
TOPICS={'Python':r'\bpython\b|пайтон', 'pandas':r'\bpandas\b', 'SQL':r'\bsql\b',
        'визуализация':r'визуализац', 'статистика':r'статистик', 'Linux':r'\blinux\b|линукс',
        'CI/CD':r'ci\s*/\s*cd|непрерывн\w*\s+(?:интеграц|достав)',
        'контейнеризация':r'docker|контейнер', 'мониторинг':r'мониторинг',
        'инфраструктура как код':r'\biac\b|инфраструктур\w*\s+как\s+код|terraform',
        'сети':r'сет[ьи]|сетев', 'этика ИИ':r'этик|безопасн\w*\s+использован\w*\s+ии',
        'персональные данные':r'персональн\w*\s+данн|работ\w*\s+с\s+детьми',
        'кибербезопасность':r'кибербезопас|информационн\w*\s+безопас|сетев\w*\s+безопас|защит\w*\s+(?:информац|данн|сет)'}
def normalize(value):return re.sub(r'\s+',' ',str(value).lower().replace('ё','е')).strip()
def concept_present(concept,value):
    pattern=next((pattern for name,pattern in TOPICS.items() if normalize(name)==normalize(concept)),re.escape(normalize(concept)))
    return bool(re.search(pattern,normalize(value)))

def duplicates_final(title):
    return bool(re.match(r'^(?:итогов\w*\s+(?:аттестац|экзамен|защит)|практическ\w*\s+(?:итогов\w*\s+)?экзамен|защита\s+(?:итогов\w*\s+)?(?:отчета|проекта))',normalize(title)))

def explicit_requirements(request):
    """Literal constraints override probabilistic extraction across arbitrary IT topics."""
    text=normalize(request);result={}
    dpp=bool(re.search(r'повышени[ея]\s+квалификаци|\bдпп\b',text))
    general=bool(re.search(r'общеразвивающ|общеобразовательн',text))
    if dpp!=general:result['type']='dpp' if dpp else 'general'
    total=re.search(r'(?:на|объем(?:ом)?|,|—)\s*(\d{2,4})\s+(?:академических\s+|академич\.\s*)?час',text)
    if not total:total=re.search(r'\b(\d{2,4})\s*[-–]\s*часов(?:ой|ая|ую|ый|ого|ом)\b',text)
    if not total:
        candidates=list(re.finditer(r'\b(\d{2,4})\s*(?:ак(?:ад)?\.\s*)?(?:час\w*|ч\.)(?!\w)',text))
        candidates=[m for m in candidates if not re.search(r'не\s+менее|не\s+более|практик|аттестаци',text[max(0,m.start()-35):m.start()]) and not re.match(r'\s*(?:в\s+день|в\s+неделю|практик)',text[m.end():])]
        if len(candidates)==1:total=candidates[0]
    if total:result['totalHours']=int(total[1])
    final=re.search(r'итоговая\s+аттестация[^.\n]{0,180}?'+NUMBER+r'\s+час',text)
    if final:result['finalHours']=number(final[1])
    patterns={
        'weeks':NUMBER+r'\s+недел',
        'sessionHours':r'(?:занятия[^.]{0,20}?по|занятие[^.]{0,15}?длится|длительность\s+занятия)\s+'+NUMBER+r'\s+час',
        'sessionsPerWeek':NUMBER+r'\s+раз\w*\s+в\s+недел',
        'daysPerWeek':NUMBER+r'\s+(?:дней|дня|день)\s+в\s+недел',
        'maxHoursPerDay':r'(?:не\s+(?:больше|более)|максимум|до)\s+'+NUMBER+r'\s+час\w*\s+в\s+день',
        'durationMonths':NUMBER+r'\s+месяц',
        'portfolioItems':r'портфолио\s+из\s+'+NUMBER+r'\s+(?:материал|работ)',
        'testQuestionCount':NUMBER+r'\s+вопрос',
        'slidesForSessions':r'слайд\w*\s+для\s+первых\s+'+NUMBER+r'\s+заняти'}
    for key,pattern in patterns.items():
        match=re.search(pattern,text)
        if match:result[key]=number(match[1])
    if re.search(r'(?:около|примерно|приблизительно)\s+(?:на\s+)?(?:'+NUMBER+r'\s+)?месяц',text):
        result['approximateDuration']=True;result.setdefault('durationMonths',1)
    practice=re.search(r'(?:не\s+менее|минимум|не\s+меньше)\s+'+NUMBER+r'\s+час\w*\s+практик',text)
    if practice:result['minPracticeHours']=number(practice[1])
    elif re.search(r'практик[^.]{0,70}половин|половин[^.]{0,50}практик',text) and result.get('totalHours'):
        result['minPracticeHours']=math.ceil(result['totalHours']/2)
    percent=re.search(r'практик[^.]{0,50}?(\d{1,3})\s*(?:%|процент)',text) or re.search(r'(\d{1,3})\s*(?:%|процент\w*)[^.]{0,30}практик',text)
    if percent and result.get('totalHours') and 0<=int(percent[1])<=100:result['minPracticeHours']=math.ceil(result['totalHours']*int(percent[1])/100)
    if re.search(r'\bежедневно\b|каждый\s+день',text):result['daysPerWeek']=7
    if re.search(r'вся\s+работа\s+самостоятельная|аудиторных\s+занятий\s+нет|без\s+контактной\s+работы',text):
        result.update(selfStudyOnly=True,currentControl='interview')
    if 'собеседован' in text:result['currentControl']='interview'
    if 'очно-заоч' in text:result['format']='Очно-заочная с применением дистанционных образовательных технологий' if re.search(r'дистанц|\bдот\b',text) else 'Очно-заочная'
    elif re.search(r'\bочно\b|\bочная\b',text):result['format']='Очная'
    if re.search(r'сервис[^.]{0,80}доступн[^.]{0,20}росси',text):result['russiaOnlyServices']=True
    topics=[title for title,pattern in TOPICS.items() if re.search(pattern,text)]
    if re.search(r'\bdevops\b',text):
        topics=list(dict.fromkeys(topics+['Linux','сети','контейнеризация','CI/CD','мониторинг','инфраструктура как код']))
    if topics:result['requiredTopics']=topics
    slide_text=re.search(r'слайд[^.]{0,130}',text)
    if slide_text:result['slidesForTopics']=[name for name in topics if concept_present(name,slide_text[0])]
    return result

def merge_requirements(request,model,structured=None,answers=None):
    """Do not let an LLM invent decisive parameters of an incomplete brief."""
    literal=explicit_requirements(request);structured=structured or {};answers=answers or {}
    aliases={'level':'entryLevel','hours':'totalHours','аудитория':'audience','уровень':'entryLevel',
             'итоговая аттестация':'assessment','форма':'format','тип':'type'}
    answered={aliases.get(k,k):v for k,v in answers.items()}
    if isinstance(answered.get('type'),str):
        value=normalize(answered['type'])
        if re.search(r'повышени[ея]\s+квалификаци|\bдпп\b',value):answered['type']='dpp'
        elif re.search(r'общеразвивающ|общеобразовательн',value):answered['type']='general'
    supplied={**literal,**{k:v for k,v in structured.items() if v not in (None,'')},**answered}
    for key,value in list(supplied.items()):
        if key in Requirements.model_fields and isinstance(value,str):
            if value.strip().isdigit():supplied[key]=int(value)
            elif key in ('totalHours','weeks','finalHours','sessionHours','sessionsPerWeek','maxHoursPerDay','testQuestionCount','minPracticeHours','portfolioItems'):
                match=re.fullmatch(r'\s*(\d+)\s*(?:академическ\w*\s+)?(?:час\w*|ч\.?|недел\w*|вопрос\w*|материал\w*)\s*',value,re.I)
                if match:supplied[key]=int(match[1])
    result={**model,**supplied}
    for key in ('weeks','finalHours','sessionHours','sessionsPerWeek','daysPerWeek','maxHoursPerDay','durationMonths','minPracticeHours','testQuestionCount','portfolioItems','slidesForSessions'):
        if key not in supplied:result.pop(key,None)
    provenance={k:('user_answer' if k in answered else 'form' if k in structured and structured[k] not in (None,'') else 'explicit_text' if k in literal else 'model_inference') for k in result}
    for key in ('type','totalHours'):
        if key not in supplied:result[key]=None
    incomplete=not result.get('type') or not result.get('totalHours')
    if incomplete:
        for key in ('entryLevel','format','assessment'):
            if key not in supplied:result[key]=None
    return Requirements.model_validate(result).model_dump(exclude_none=True),provenance

def allocate(total,weights,minimum=0):
    if not weights or total<minimum*len(weights):raise ValueError('Число тем превышает доступные часы. Сократите структуру.')
    remaining=total-minimum*len(weights);denominator=sum(weights)
    values=[minimum+remaining*w//denominator for w in weights]
    order=sorted(range(len(weights)),key=lambda i:(-(remaining*weights[i]%denominator),i))
    for i in order[:total-sum(values)]:values[i]+=1
    return values

def calendar_for(rows,req):
    total=req['totalHours'];per_week=req.get('sessionsPerWeek');weeks=req.get('weeks')
    limit=req.get('maxHoursPerDay');session=req.get('sessionHours')
    if session and limit and session>limit:raise ValueError('Длительность занятия больше дневного лимита')
    if session and total%session:raise ValueError('Объём не кратен длительности занятий: уточните длительность последнего занятия')
    if not weeks and req.get('durationMonths') and not limit and not session:weeks=req['durationMonths']*4
    if not session:session=limit or (min(24,max(1,math.ceil(total/(weeks*(per_week or req['daysPerWeek']))))) if weeks else 2)
    loads=[min(session,total-i) for i in range(0,total,session)]
    if not per_week:per_week=math.ceil(len(loads)/weeks) if weeks else req['daysPerWeek']
    if per_week>7:raise ValueError('Запрошенный срок требует более семи учебных дней в неделю. Уточните срок или дневную нагрузку.')
    actual_weeks=math.ceil(len(loads)/per_week)
    if weeks and actual_weeks>weeks:raise ValueError('Занятия не помещаются в запрошенное число недель')
    weeks=weeks or actual_weeks
    if weeks>len(loads):raise ValueError('Занятий меньше числа недель: уточните периодичность')
    if req.get('durationMonths') and not req.get('approximateDuration') and len(loads)>req['durationMonths']*30:
        raise ValueError('Дневной лимит несовместим с запрошенным сроком в месяцах')
    counts=allocate(len(loads),[1]*weeks);sessions=[];queue=[list(row) for row in rows];ri=0;pos=0
    for week,count in enumerate(counts,1):
        for day in range(1,count+1):
            hours=loads[pos];pos+=1;left=hours;parts=[]
            while left:
                tid,remaining=queue[ri];take=min(left,remaining)
                parts.append({'topicId':tid,'hours':take});left-=take;queue[ri][1]-=take
                if not queue[ri][1]:ri+=1
            sessions.append({'id':f'S{pos}','week':week,'day':day,'hours':hours,
                             'topicIds':[x['topicId'] for x in parts],'allocations':parts})
    return {'weeks':weeks,'daysPerWeek':per_week,'sessionHours':session,'sessions':sessions}

def schedule_question(requirements):
    """Ask before a model call if hard limits cannot fit; never silently change them."""
    req=Requirements.model_validate(requirements).model_dump()
    if not req.get('totalHours'):return None
    final=req.get('finalHours') or 2
    try:calendar=calendar_for([('study',req['totalHours']-final),('final',final)],req)
    except ValueError as error:
        field='sessionHours' if req.get('sessionHours') and req['totalHours']%req['sessionHours'] else 'weeks'
        daily=req.get('sessionHours') or req.get('maxHoursPerDay') or 8
        proposed=math.ceil(math.ceil(req['totalHours']/daily)/(req.get('sessionsPerWeek') or req['daysPerWeek']))
        return {'field':field,'question':str(error)+('. Укажите допустимую длительность занятия.' if field=='sessionHours' else f' При текущей нагрузке нужно не менее {proposed} недель. Какой срок согласовать?'),
                'suggestedValue':None if field=='sessionHours' else proposed}
    if req.get('approximateDuration') and req.get('durationMonths') and req.get('maxHoursPerDay') and not req.get('weeks'):
        days=math.ceil(req['totalHours']/req['maxHoursPerDay'])
        if days>req['durationMonths']*30:
            weeks=calendar['weeks']
            return {'field':'weeks','question':f'{req["totalHours"]} часов при лимите {req["maxHoursPerDay"]} ч./день требуют минимум {days} учебных дней. В ориентир {req["durationMonths"]} мес. это не помещается. При {calendar["daysPerWeek"]} учебных днях в неделю нужно {weeks} недель. Какой увеличенный срок согласовать?', 'suggestedValue':weeks}
    return None

def unresolved_competencies(outline):
    """Find references requiring model-authored definitions; never guess bindings."""
    known={c.get('id') for c in outline.get('competencies',[]) if isinstance(c,dict)}
    return list(dict.fromkeys(cid for m in outline.get('modules',[]) if isinstance(m,dict)
        for t in m.get('topics',[]) if isinstance(t,dict)
        for cid in t.get('competencyIds',[]) if isinstance(cid,str) and cid not in known))


def repair_competencies(outline, additions):
    from .contracts import Competency
    missing=unresolved_competencies(outline)
    values=[Competency.model_validate(value).model_dump() for value in additions]
    if len(values)!=len(missing) or {c['id'] for c in values}!=set(missing):
        raise ValueError('Доработка должна определить только отсутствующие компетенции с точными ID')
    result=copy.deepcopy(outline)
    result['competencies'].extend(values)
    return result


def build_skeleton(outline,requirements):
    # Preserve explanatory model objects as readable assumptions; never treat their
    # numbers as authoritative requirements or hour allocations.
    outline=copy.deepcopy(outline)
    changes=[]
    # Known field aliases are shape normalization, not invented educational content.
    modules=[]
    for m in outline.get('modules',[]):
        if isinstance(m,dict) and set(m)=={'assumptions'}:
            current=outline.get('assumptions') or []
            outline['assumptions']=(current if isinstance(current,list) else [current])+[m['assumptions']]
            continue
        if duplicates_final(m.get('title','')):
            changes.append({'originalTitle':m['title'],'title':'Подготовка итоговой работы','reason':'Проведение аттестации учитывается отдельно'})
            m['title']='Подготовка итоговой работы'
        for t in m.get('topics',[]):
            if not t.get('title') and isinstance(t.get('text'),str):t['title']=t.pop('text')
            if duplicates_final(t.get('title','')):
                original=t['title'];t['title']=('Подготовка к итоговой аттестации: '+original)[:300]
                changes.append({'originalTitle':original,'title':t['title'],'reason':'Учебная подготовка отделена от проведения аттестации'})
        modules.append(m)
    outline['modules']=modules
    if isinstance(outline.get('assumptions'),(str,dict)):outline['assumptions']=[outline['assumptions']]
    if outline.get('assumptions') is None:outline['assumptions']=[]
    if isinstance(outline.get('assumptions'),list):
        outline['assumptions']=[('; '.join(str(k)+': '+str(v) for k,v in x.items() if k!='status') if isinstance(x,dict) else '\n'.join(map(str,x)) if isinstance(x,list) else x) for x in outline['assumptions']]
    outline=Outline.model_validate(outline).model_dump();req=Requirements.model_validate(requirements).model_dump()
    needed=('type','totalHours','audience','entryLevel','format','assessment')
    if any(not req.get(k) for k in needed):raise ValueError('Сначала уточните обязательные требования')
    ids={c['id'] for c in outline['competencies']}
    if len(ids)!=len(outline['competencies']):raise ValueError('Коды компетенций должны быть уникальны')
    topics=[t for m in outline['modules'] for t in m['topics']]
    if any(set(t['competencyIds'])-ids for t in topics):raise ValueError('Неизвестная компетенция в теме')
    if ids-{c for t in topics for c in t['competencyIds']}:raise ValueError('Не все компетенции связаны с темами')
    titles=[normalize(t['title']) for t in topics]
    if len(titles)!=len(set(titles)):raise ValueError('Темы дублируются')
    context=[m['title']+' '+t['title'] for m in outline['modules'] for t in m['topics']]
    missing=[name for name in req['requiredTopics'] if not any(concept_present(name,title) for title in context)]
    if missing:raise ValueError('Нет обязательных тем: '+', '.join(missing))
    if any(duplicates_final(t) for t in titles) or any(duplicates_final(m['title']) for m in outline['modules']):raise ValueError('Аттестация учитывается отдельно; уберите модуль/тему её проведения. Подготовку отчёта и проекта можно оставить как учебную работу.')
    final=req.get('finalHours') or 2
    if final>=req['totalHours']:raise ValueError('Аттестация должна оставлять часы на обучение')
    hours=allocate(req['totalHours']-final,[t['weight'] for t in topics],1);practical=req['minPracticeHours']
    if practical>sum(hours) or (practical and req['selfStudyOnly']):raise ValueError('Практические часы несовместимы с объёмом или форматом')
    practice=allocate(practical,hours) if practical else [h//2 for h in hours]
    rows=[];modules=[];index=0
    for mi,m in enumerate(outline['modules'],1):
        result={'id':f'M{mi}','title':m['title'],'topics':[],'totalHours':0}
        for ti,t in enumerate(m['topics'],1):
            h=hours[index];p=practice[index];index+=1
            parts={'lecture':0,'practice':0,'lab':0,'self':h} if req['selfStudyOnly'] else {'lecture':h-p,'practice':p,'lab':0,'self':0}
            contact=parts['lecture']+parts['practice'];remote=contact//2 if re.search('заоч|дистанц',req['format'],re.I) else 0
            topic={'id':f'T{mi}.{ti}','title':t['title'],'totalHours':h,'hours':parts,
                   'delivery':{'inPerson':contact-remote,'remote':remote},'competencyIds':t['competencyIds']}
            result['topics'].append(topic);result['totalHours']+=h;rows.append((topic['id'],h))
        modules.append(result)
    calendar=calendar_for(rows+[('final',final)],req)
    assumptions=outline['assumptions']+['Часы и календарь рассчитаны алгоритмом; распределение утверждает методист.']
    if changes:assumptions.append('Проведение итоговой аттестации вынесено из учебных модулей; в темах оставлена только подготовка. Изменения названий перечислены в planningChanges.')
    if re.search('заоч|дистанц',req['format'],re.I) and not req['selfStudyOnly']:
        assumptions.append('Предложенное распределение контактных часов на очную и дистанционную работу указано в плане и требует согласования методистом.')
    if req.get('approximateDuration'):
        assumptions.append(f'Ориентир {req["durationMonths"]} мес. не является точным сроком. При {calendar["daysPerWeek"]} учебных днях в неделю требуется {calendar["weeks"]} недель; подтвердите календарь до генерации материалов.')
    if req['type']=='general':
        for c in outline['competencies']:c['standard']=None
    return {k:req[k] for k in needed}|{'title':outline['title'],'goal':outline['goal'],'finalHours':final,
        'constraintVersion':3,'constraints':req,'planningChanges':changes,'selfStudyOnly':req['selfStudyOnly'],
        'competencies':outline['competencies'],'modules':modules,'calendar':calendar,'assumptions':assumptions}
