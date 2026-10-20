"""Curated documentary identities, not a claim about current legal applicability.

Metadata reviewed against the publisher/developer on 2026-10-19. Function codes
are immutable source facts; the expert must confirm their scope and currentness.
An LLM-supplied `verified` flag is never trusted.
"""
import copy
import re
CATALOG=[
 {'code':'01.001','title':'Педагог (педагогическая деятельность в сфере дошкольного, начального общего, основного общего, среднего общего образования) (воспитатель, учитель)',
  'order':'544н','date':'18.10.2013','url':'https://mintrud.gov.ru/docs/mintrud/orders/129',
  'documentUrl':'https://mintrud.gov.ru/uploads/magic/ru-RU/2f4a6464-1500963510.doc',
  'functions':{'A/01.6':'Общепедагогическая функция. Обучение'},'tags':r'учител|педагог'},
 {'code':'06.042','title':'Специалист по большим данным','order':'405н','date':'06.07.2020',
  'url':'https://apkit.ru/committees/komitet-po-obrazovaniyu/',
  'documentUrl':'https://apkit.ru/files/06.042_Big_data_Specialist%20%281%29.zip',
  'functions':{'A/01.6':'Выявление, формирование и согласование требований к результатам аналитических работ с применением технологий больших данных',
               'A/03.6':'Подготовка данных для проведения аналитических работ по исследованию больших данных',
               'A/04.6':'Проведение аналитического исследования с применением технологий больших данных в соответствии с требованиями заказчика'},
  'tags':r'анализ\w*\s+данных|pandas|статистик|аналитик'},
 {'code':'06.026','title':'Системный администратор информационно-коммуникационных систем','order':'680н','date':'29.09.2020',
  'url':'https://apkit.ru/committees/komitet-po-obrazovaniyu/','documentUrl':'https://apkit.ru/files/06.026_Sysadmin_IKS.zip',
  'functions':{'A/01.4':'Выполнение работ по выявлению и устранению типичных инцидентов информационно-коммуникационных систем'},
  'tags':r'devops|linux|системн\w*\s+администр|ci/cd'},
 {'code':'06.033','title':'Специалист по защите информации в автоматизированных системах','order':'525н','date':'14.09.2022',
  'url':'https://apkit.ru/committees/komitet-po-obrazovaniyu/','documentUrl':'https://apkit.ru/files/06.033_ZIAS_specialist_new.zip',
  'functions':{'A/01.5':'Проведение технического обслуживания систем защиты информации автоматизированных систем',
               'A/02.5':'Ведение технической документации, связанной с эксплуатацией систем защиты информации автоматизированных систем'},
  'tags':r'кибербезопас|защит\w*\s+информац|информационн\w*\s+безопас'},
]
def function_code(value):return str(value).upper().translate(str.maketrans('АВС','ABC')).replace(' ','')

def candidates(request):
    return [{k:v for k,v in copy.deepcopy(row).items() if k!='tags'}|{'metadataCheckedAt':'2026-10-19','status':'scope_requires_expert_review'} for row in CATALOG if re.search(row['tags'],request,re.I)]

def standard_issue(value):
    if not value:return 'Профстандарт не подобран. Приложите документ или укажите подтверждённый код; эксперт должен связать трудовую функцию с результатом.'
    row=next((x for x in CATALOG if x['code']==value.get('code')),None)
    if not row:return 'Код профстандарта отсутствует в проверенном справочнике. Источник и код функции НЕ ПОДТВЕРЖДЕНЫ.'
    if function_code(value.get('functionCode')) not in row['functions']:return 'Трудовая функция не найдена в проверенном документе профстандарта '+row['code']
    return None

def normalize_standard(value):
    if not value:return None
    row=next((x for x in CATALOG if x['code']==value.get('code')),None)
    if row and function_code(value.get('functionCode')) in row['functions']:
        code=function_code(value['functionCode'])
        return {k:row[k] for k in ('code','title','order','date','url','documentUrl')}|{'functionCode':code,'functionTitle':row['functions'][code],
            'status':'scope_requires_expert_review','metadataCheckedAt':'2026-10-19','verificationMethod':'curated_document_metadata'}
    return {**value,'status':'unverified','verificationMethod':'not_confirmed'}
