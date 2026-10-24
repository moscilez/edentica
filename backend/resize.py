"""Explicit course-volume changes reuse semantic content, never invent lesson IDs."""
import copy
import math
import re
from .contracts import Requirements
from .planning import build_skeleton,schedule_question
from .programs_helpers import ensure


def requested_hours(message,current=None):
    text=message.lower().replace('ё','е')
    if not re.search(r'увелич|сократ|уменьш|измен|помен|адаптир|сдела',text):return None
    # The conversation is already scoped to a course. Short follow-up requests
    # need not repeat its name; an explicitly targeted lesson remains local.
    if re.search(r'урок|модул|занят',text) and not re.search(r'(?:увелич|измен|сократ|уменьш|сдела)\w*\s+(?:всю\s+)?(?:программ|курс)|общ\w*\s+объем|объем\w*\s+программ',text):return None
    if re.search(r'(?:объем|час\w*)\s+(?:этого\s+)?(?:урок|модул)',text):return None
    values=re.findall(r'(?:до|на)\s*(\d{1,5})\s*(?:академическ\w*\s+)?(?:час\w*|ч\b)',text)
    if not values and re.search(r'час|\bч\b',text):values=re.findall(r'(?:до|на)\s*(\d{1,5})\s*[.!?]?$',text)
    if not values:return None
    value=int(values[-1])
    if re.search(r'увелич|сократ|уменьш',text) and re.search(r'\bна\s*\d+',text) and not re.search(r'\bдо\s*\d+|\bс\s*\d+\s*(?:час\w*)?\s+на\s*\d+',text):
        if current is None:return None
        return current-value if re.search(r'сократ|уменьш',text) else current+value
    return value


def resize_plan(program,total,weeks=None):
    ensure(type(total) is int and 16<=total<=10000,'Объём программы должен быть от 16 до 10 000 часов')
    s=program.get('skeleton');ensure(s,'Сначала создайте каркас программы')
    ensure(total!=s['totalHours'],'У программы уже указан этот объём часов')
    req={**s.get('constraints',{}),**program.get('requirements',{})}
    for key in ('type','audience','entryLevel','format','assessment','selfStudyOnly'):
        if key in s:req.setdefault(key,s[key])
    req.update(totalHours=total,finalHours=s['finalHours'])
    minimum=req.get('minPracticeHours',0)
    if minimum:req['minPracticeHours']=math.ceil(minimum*total/s['totalHours'])
    if weeks is not None:req['weeks']=weeks
    req=Requirements.model_validate(req).model_dump(exclude_none=True)
    question=schedule_question(req)
    ensure(not question,question['question'] if question else '')
    maximum=max(t['totalHours'] for m in s['modules'] for t in m['topics'])
    outline={k:copy.deepcopy(s[k]) for k in ('title','goal','competencies')}
    outline['modules']=[{'title':m['title'],'topics':[{'title':t['title'],'competencyIds':t['competencyIds'],
        'weight':max(1,round(t['totalHours']/maximum*100))} for t in m['topics']]} for m in s['modules']]
    outline['assumptions']=['Часы и календарь пересчитаны по новой трудоёмкости. Проверьте каркас перед созданием материалов.']
    if minimum:outline['assumptions'].append('Минимум практических часов масштабирован пропорционально объёму программы.')
    planned=build_skeleton(outline,req)
    if req['type']=='dpp':
        original={c['id']:c.get('standard') for c in s['competencies']}
        for competency in planned['competencies']:
            competency['standard']=copy.deepcopy(original[competency['id']])
    return planned,req
