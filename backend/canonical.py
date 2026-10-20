"""Single source of truth for numeric sections and export tables."""
def normalize_criteria(value):
    """Treat positive model scores as weights; calculate the 100-point scale."""
    if not isinstance(value,list) or not 2<=len(value)<=100:return value
    if any(not isinstance(x,dict) or type(x.get('points')) is not int or x['points']<=0 for x in value):return value
    if sum(x['points'] for x in value)==100:return value
    from .planning import allocate
    scores=allocate(100,[x['points'] for x in value],1)
    return [{**x,'points':score,'originalWeight':x['points']} for x,score in zip(value,scores)]


def hour_totals(s):
    return {k:sum(t['hours'][k] for m in s['modules'] for t in m['topics']) for k in ('lecture','practice','lab','self')}|{'attestation':s['finalHours']}

def numeric_sections(s):
    h=hour_totals(s);volume=(f'Объём программы — {s["totalHours"]} академических часов: лекции — {h["lecture"]}, '
        f'практические занятия — {h["practice"]}, лабораторные — {h["lab"]}, самостоятельная работа — {h["self"]}, '
        f'итоговая аттестация — {h["attestation"]}. Аттестация входит в общий объём и не дублируется в модулях.')
    calendar=s['calendar'];sessions=calendar['sessions']
    schedule=(f'Срок — {calendar["weeks"]} недель; учебных дней — {len(sessions)}; '
        f'общая нагрузка — {sum(x["hours"] for x in sessions)} академических часов. '
        f'Не более {max(x["hours"] for x in sessions)} часов в учебный день. '
        'Распределение по неделям, дням и темам приведено в календарной таблице.')
    plan=volume+'\n'+'\n'.join(f'{m["id"]}. {m["title"]} — {m["totalHours"]} ч.' for m in s['modules'])
    outcomes='\n'.join(c['id']+'. '+c['title']+'\nЗнать: '+c['knowledge']+'\nУметь: '+c['abilities']+'\nВладеть: '+c['skills'] for c in s['competencies'])
    return {'Объём программы':volume,'Сроки реализации':schedule,
            'Форма обучения':s['format'],'Требования к слушателям':s['audience']+'. Входной уровень: '+s['entryLevel'],
            'Категории обучающихся':s['audience']+'. Входной уровень: '+s['entryLevel'],
            'Цель реализации программы':s['goal'],'Цель и задачи программы':s['goal'],
            'Планируемые результаты обучения':outcomes,
            'Выдаваемый документ':'Удостоверение о повышении квалификации при успешном освоении программы и соблюдении требований к допуску.' if s['type']=='dpp' else 'Документ об обучении по правилам организации; не является удостоверением о повышении квалификации.',
            'Организация образовательного процесса':s['format']+'. '+schedule+'\n'+('Самостоятельная работа с обратной связью наставника; контактные занятия не предусмотрены.' if s.get('selfStudyOnly') else 'Рекомендации по изучению и контролю приведены в рабочих программах модулей.'),
            'Учебный план':plan,'Учебно-тематический план':volume,
            'Календарный учебный график':schedule}

def canonicalize_sections(sections,s):
    return {k:numeric_sections(s).get(k,v) for k,v in sections.items()}
