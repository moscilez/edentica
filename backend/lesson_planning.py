"""A study topic may span many independently teachable lessons."""
import math


def lesson_slots(module):
    slots=[]
    # Keep large modules within the material/export contract, while small
    # courses retain short lessons. Explicit lesson counts are never rounded.
    unit_hours=2
    explicit=sum(t.get('lessonCount') or 0 for t in module['topics'])
    if explicit>150:raise ValueError('Разделите модуль: не более 150 отдельных уроков')
    while sum(t.get('lessonCount') or math.ceil(t['totalHours']/unit_hours) for t in module['topics'])>150:
        unit_hours+=1
        if unit_hours>10000:raise ValueError('Разделите модуль на несколько модулей')
    for topic in module['topics']:
        # A lesson includes explanation and its associated practice/self study.
        hours=topic['totalHours']
        count=topic.get('lessonCount') or math.ceil(hours/unit_hours)
        if type(count) is not int or not 1<=count<=150:
            raise ValueError('Укажите целое количество уроков от 1 до 150')
        if count>hours:
            raise ValueError('Количество уроков превышает часы темы '+topic['title'])
        remaining={kind:topic.get('hours',{}).get(kind,0) for kind in ('lecture','practice','lab','self')}
        for index in range(count):
            load=hours//count+(index<hours%count)
            activities={}
            if sum(remaining.values()):
                total=sum(remaining.values())
                activities={kind:load*value//total for kind,value in remaining.items()}
                order=sorted(remaining,key=lambda kind:-(load*remaining[kind]%total))
                for kind in order[:load-sum(activities.values())]:activities[kind]+=1
                remaining={kind:value-activities[kind] for kind,value in remaining.items()}
            slots.append({'id':f"{topic['id']}-L{index+1}",'topicId':topic['id'],
                          'number':index+1,'count':count,
                          'hours':load,'activities':activities,
                          'title':topic['title']+(f' · занятие {index+1}' if count>1 else '')})
    return slots


def coverage(module,material):
    slots=lesson_slots(module)
    actual={l.get('lessonId') for l in (material or {}).get('lectures',[])}
    missing=[slot for slot in slots if slot['id'] not in actual]
    return {'expected':len(slots),'completed':len(slots)-len(missing),'missing':missing}
