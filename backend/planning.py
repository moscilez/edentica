"""Exact-hour scheduling from a semantic model outline, before human approval."""
from .contracts import Outline,Requirements
import re


def explicit_requirements(request):
    """Literal constraints take precedence over probabilistic extraction."""
    text=request.lower();result={}
    dpp=bool(re.search(r'повышени[ея]\s+квалификаци|\bдпп\b',text))
    general=bool(re.search(r'общеразвивающ|общеобразовательн',text))
    if dpp!=general:result['type']='dpp' if dpp else 'general'
    total=re.search(r'(?:на|объ[её]м(?:ом)?)\s+(\d{2,4})\s+(?:академических\s+|академич\.\s*)?час',text)
    if total:result['totalHours']=int(total[1])
    final=re.search(r'итоговая\s+аттестация[^.\n]{0,350}?(\d{1,3})\s+час',text)
    if final:result['finalHours']=int(final[1])
    weeks=re.search(r'(\d{1,3})\s+недел',text)
    if weeks:result['weeks']=int(weeks[1])
    practice=re.search(r'(?:не\s+менее|минимум)\s+(\d{1,4})\s+час\w*\s+практик',text)
    if practice:result['minPracticeHours']=int(practice[1])
    elif 'половина часов' in text and result.get('totalHours'):result['minPracticeHours']=(result['totalHours']+1)//2
    if 'очно-заоч' in text:result['format']='Очно-заочная'
    return result


def allocate(total,weights,minimum=0):
    if total<minimum*len(weights):raise ValueError('Число тем превышает доступные часы. Сократите структуру.')
    remaining=total-minimum*len(weights);denominator=sum(weights)
    values=[minimum+remaining*w//denominator for w in weights]
    order=sorted(range(len(weights)),key=lambda i:(-(remaining*weights[i]%denominator),i))
    for i in order[:total-sum(values)]:values[i]+=1
    return values


def build_skeleton(outline,requirements):
    outline=Outline.model_validate(outline).model_dump()
    req=Requirements.model_validate(requirements).model_dump()
    needed=('type','totalHours','audience','entryLevel','format','assessment')
    if any(not req.get(k) for k in needed):raise ValueError('Сначала уточните обязательные требования')
    ids={c['id'] for c in outline['competencies']}
    if len(ids)!=len(outline['competencies']):raise ValueError('Коды компетенций должны быть уникальны')
    topics=[t for m in outline['modules'] for t in m['topics']]
    if any(set(t['competencyIds'])-ids for t in topics):raise ValueError('Тема ссылается на неизвестную компетенцию')
    if ids-{c for t in topics for c in t['competencyIds']}:raise ValueError('Не все компетенции связаны с темами')
    final=req.get('finalHours') or 2
    if final>=req['totalHours']:raise ValueError('Аттестация должна оставлять часы на обучение')
    hours=allocate(req['totalHours']-final,[t['weight'] for t in topics],1)
    practical=req.get('minPracticeHours',0)
    if practical>sum(hours) or (practical and req['selfStudyOnly']):raise ValueError('Практические часы несовместимы с объёмом или форматом. Уточните требования.')
    practice=allocate(practical,hours) if practical else [h//2 for h in hours]
    rows=[];modules=[];index=0
    for mi,m in enumerate(outline['modules'],1):
        result={'id':f'M{mi}','title':m['title'],'topics':[],'totalHours':0}
        for ti,t in enumerate(m['topics'],1):
            h=hours[index];p=practice[index];index+=1
            parts={'lecture':0,'practice':0,'lab':0,'self':h} if req['selfStudyOnly'] else {'lecture':h-p,'practice':p,'lab':0,'self':0}
            contact=parts['lecture']+parts['practice']
            remote=contact//2 if any(x in req['format'].lower() for x in ('заоч','дистанц')) else 0
            topic={'id':f'T{mi}.{ti}','title':t['title'],'totalHours':h,'hours':parts,
                   'delivery':{'inPerson':contact-remote,'remote':remote},'competencyIds':t['competencyIds']}
            result['topics'].append(topic);result['totalHours']+=h;rows.append((topic['id'],h))
        modules.append(result)
    rows.append(('final',final));weeks=req.get('weeks') or max(1,(req['totalHours']+15)//16)
    # Split boundary-spanning topics into calendar rows without changing hours.
    week_loads=allocate(req['totalHours'],[1]*weeks);sessions=[];week=0;used=0
    for tid,h in rows:
        while h:
            while week<weeks-1 and used>=week_loads[week]:week+=1;used=0
            take=min(h,week_loads[week]-used)
            if take<=0:raise ValueError('Невозможно распределить календарные часы')
            sessions.append({'week':week+1,'hours':take,'topicIds':[tid]});h-=take;used+=take
    if req['type']=='general':
        for c in outline['competencies']:c['standard']=None
    return {k:req[k] for k in needed}|{'title':outline['title'],'goal':outline['goal'],'finalHours':final,
        'selfStudyOnly':req['selfStudyOnly'],'competencies':outline['competencies'],'modules':modules,
        'calendar':{'weeks':weeks,'sessions':sessions},'assumptions':outline['assumptions']+[
            'Часы и календарь рассчитаны алгоритмом по заданному объёму; распределение утверждает методист.']}
