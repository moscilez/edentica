"""Case references, not automatic confirmation of a law's current applicability."""
import re

LAW={'title':'Федеральный закон от 29.12.2012 № 273-ФЗ «Об образовании в Российской Федерации»',
     'url':'https://minjust.gov.ru/ru/documents/7629/','kind':'standard',
     'reason':'Нормативный ориентир из ТЗ. Карточка Минюста подтверждает реквизиты; применимую редакцию проверяет эксперт.'}


def references(kind):
    values=[dict(LAW)]
    if kind=='general':
        values.append({'title':'Приказ Минпросвещения России от 27.07.2022 № 629',
            'url':'https://publication.pravo.gov.ru/Document/View/0001202209270013','kind':'standard',
            'reason':'Шаблон общеразвивающей программы из ТЗ; содержание и актуальную редакцию подтверждает эксперт.'})
    else:
        values.extend([
            {'title':'Приказ Минобрнауки России от 01.07.2013 № 499','url':'','kind':'standard',
             'reason':'Указан в ТЗ кейса. Применимость к новой программе требует юридической проверки; не считать автоматически действующим.'},
            {'title':'Приказ Минобрнауки России от 24.03.2025 № 266',
             'url':'https://mchs.gov.ru/dokumenty/bazovye-normativnye-pravovye-akty/normativnye-pravovye-akty-ministerstv-i-vedomstv/8006',
             'kind':'standard','reason':'Карточка МЧС подтверждает реквизиты документа о ДПО. Эксперту нужно разрешить расхождение с указанным в ТЗ приказом № 499.'}])
    return values


def section_policy_issues(data,kind):
    from .standards import CATALOG
    allowed={'273','629'} if kind=='general' else {'273','499','266'}
    identities={'273':('29.12.2012',None),'629':('27.07.2022','Минпросвещения'),
                '499':('01.07.2013','Минобрнауки'),'266':('24.03.2025','Минобрнауки')}
    for row in CATALOG:
        allowed.add(re.sub(r'\D','',row['order']));identities[re.sub(r'\D','',row['order'])]=(row['date'],'Минтруда')
    errors=[]
    values=[str(x) for x in (data.get('sections') or {}).values()]
    values += [str(s.get('title','')) for s in data.get('sources',[]) if isinstance(s,dict)]
    for text in values:
        if not re.search(r'приказ|федеральн\w*\s+закон',text,re.I):continue
        for number in re.findall(r'(?:№|\bN)\s*(\d+)',text):
            if number not in allowed:errors.append('Нормативный акт № '+number+' не подтверждён справочником кейса для этого шаблона. Не выдумывай реквизиты; используй regulatoryReferences.')
        for match in re.finditer(r'(?:приказ|федеральн\w*\s+закон)(?:(?!приказ|федеральн\w*\s+закон)[^;\n]){0,220}?(?:№|\bN)\s*(\d+)',text,re.I):
            number=match[1];identity=identities.get(number)
            if not identity:continue
            clause=match[0];date,issuer=identity
            dates=re.findall(r'\b\d{2}\.\d{2}\.\d{4}\b',clause)
            if dates and any(d!=date for d in dates):errors.append('Дата документа № '+number+' не совпадает с подтверждёнными реквизитами '+date)
            agency=re.search(r'\bМин[а-яё]+',clause,re.I)
            if issuer and agency and agency[0].lower()!=issuer.lower():errors.append('Ведомство документа № '+number+' не совпадает с подтверждённым: '+issuer)
        if kind=='general' and re.search(r'(?:№|\bN)\s*(?:266|499)\b',text):errors.append('Приказы о ДПО нельзя подставлять вместо приказа № 629 для общеразвивающей программы.')
    return list(dict.fromkeys(errors))
