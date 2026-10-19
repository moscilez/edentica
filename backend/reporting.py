"""Human-readable validation outcome, separate from immutable teaching content."""
from html import escape


def enrich(report,program):
    errors=report['errors'];warnings=report['warnings'];complete=bool(program.get('sections'))
    groups=[('hours','Часы и календарь',{'hours','topic_sum','module_sum','total_sum','calendar','calendar_sum','calendar_topic','calendar_final','delivery','practice','requested_hours','requested_type','schema'}),
            ('coverage','Компетенции и оценивание',{'coverage','reference','assessment_coverage','question_count'}),
            ('content','Лекции, тесты и задания',{'content','missing_module','final_assessment'}),
            ('template','Полнота шаблона АЦР',{'section'}),('sources','Источники и профстандарты',{'source_unverified','source_unavailable','source_rejected','sources_missing','standard_missing','standard_review'})]
    checks=[]
    for key,title,codes in groups:
        failures=[x for x in errors if x['code'] in codes];notes=[x for x in warnings if x['code'] in codes]
        pending=not complete and key in ('content','coverage','template')
        status='pending' if pending else 'failed' if failures else 'warning' if notes else 'passed'
        checks.append({'id':key,'title':title,'status':status,'errors':len(failures),'warnings':len(notes),
                       'explanation':'Материалы ещё готовятся' if pending else 'Нужно исправить замечания' if failures else 'Требуется подтверждение человеком' if notes else 'Проверка пройдена'})
    report.update(checks=checks,summary={'errors':len(errors),'warnings':len(warnings),'readyForExpertReview':report['passed'],
        'message':'Черновик комплекта прошёл структурные проверки. Проверьте источники и передайте эксперту.' if report['passed'] else
            'Каркас подготовлен. Утвердите цель, компетенции и часы перед созданием материалов.' if not program.get('approval') else
            'Комплект требует доработки. Исправьте отмеченные разделы или продолжите незавершённую генерацию.'})
    return report


def workflow(program):
    state=program.get('state','brief');busy=(program.get('job') or {}).get('state')=='running'
    steps=[('requirements','Требования',state!='brief'),('skeleton','Каркас',bool(program.get('skeleton'))),
           ('approval','Подтверждение методиста',bool(program.get('approval'))),
           ('materials','Материалы',bool(program.get('sections'))),('validation','Проверка комплекта',state=='draft_ready')]
    return {'state':state,'busy':busy,'steps':[{'id':k,'title':t,'completed':ok} for k,t,ok in steps],
            'nextAction':'wait' if busy else 'answer_questions' if state=='clarification' else 'approve' if program.get('skeleton') and not program.get('approval') else
                'export' if state=='draft_ready' else 'generate' if program.get('approval') else 'workflow',
            'humanApprovalRequired':bool(program.get('skeleton') and not program.get('approval'))}


def report_html(program):
    report=program['report'];e=lambda v:escape(str(v))
    parts=['<!doctype html><html lang="ru"><meta charset="utf-8"><title>Отчёт проверки Эдентика</title>',
        '<style>body{font:16px/1.6 sans-serif;max-width:1000px;margin:40px auto;padding:20px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:10px;text-align:left}h1,h2{color:#51318f}</style>',
        '<h1>Отчёт автопроверки</h1><p>'+e(program['skeleton']['title'])+'</p><p>'+e(report['summary']['message'])+'</p>',
        '<p>Черновик. Доступность URL и структурная проверка не подтверждают педагогическую или юридическую достоверность.</p>',
        '<h2>Результаты проверок</h2><table><tr><th>Проверка</th><th>Результат</th></tr>']
    for row in report['checks']:parts.append('<tr><td>'+e(row['title'])+'</td><td>'+e(row['explanation'])+'</td></tr>')
    parts.append('</table><h2>Замечания</h2><ul>')
    for row in report['errors']+report['warnings']:parts.append('<li>'+e(row['path'])+': '+e(row['message'])+'</li>')
    parts.append('</ul><h2>Покрытие результатов обучения</h2><table><tr><th>Компетенция</th><th>Темы</th><th>Вопросы</th><th>Задания</th></tr>')
    for row in report['coverage']:parts.append('<tr>'+''.join('<td>'+e(row['title'] if k=='title' else ', '.join(row[k]))+'</td>' for k in ['title','topics','questions','assignments'])+'</tr>')
    parts.append('</table><p>Проверено: '+e(report['checkedAt'])+'</p></html>')
    return ''.join(parts).encode('utf-8')
