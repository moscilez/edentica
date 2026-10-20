"""Evidence retrieval. A fetched page is evidence, never automatic expert approval."""
import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
import re
import time
from urllib.parse import urlencode,urljoin

from .net import public_request

DOCUMENTATION=[
 (r'python|пайтон','https://docs.python.org/ru/3/tutorial/','Руководство Python'),
 (r'pandas|анализ.*данных','https://pandas.pydata.org/docs/user_guide/index.html','Руководство pandas'),
 (r'визуализац|matplotlib','https://matplotlib.org/stable/users/index.html','Руководство Matplotlib'),
 (r'\bsql\b|баз.*данных','https://www.postgresql.org/docs/current/tutorial-sql.html','Учебник SQL PostgreSQL'),
 (r'статистик','https://docs.scipy.org/doc/scipy/tutorial/stats.html','Статистические методы SciPy'),
 (r'linux|линукс','https://docs.kernel.org/admin-guide/index.html','Документация Linux'),
 (r'docker|контейнер','https://docs.docker.com/get-started/','Документация Docker'),
 (r'ci/cd|непрерывн|gitlab','https://docs.gitlab.com/ci/','Документация GitLab CI/CD'),
 (r'мониторинг|prometheus','https://prometheus.io/docs/introduction/overview/','Документация Prometheus'),
 (r'iac|terraform|инфраструктур','https://opentofu.org/docs/','Документация OpenTofu'),
 (r'сет[ьи]|сетев','https://docs.kernel.org/networking/index.html','Сетевая подсистема Linux'),
 (r'кибер|безопас|защит.*информац','https://owasp.org/www-project-web-security-testing-guide/','OWASP: руководство тестирования безопасности'),
 (r'учител|педагог|нейросет|искусственн.*интеллект|\bии\b','https://developers.sber.ru/docs/ru/gigachat/guides/main','Документация GigaChat'),
]
_cache={}


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','nav','footer','noscript'):
            self.hidden += 1

    def handle_endtag(self,tag):
        if tag in ('script','style','nav','footer','noscript'):
            self.hidden=max(0,self.hidden-1)

    def handle_data(self,value):
        if not self.hidden and value.strip():
            self.parts.append(value.strip())


async def fetch_source(url):
    cached=_cache.get(url)
    if cached and cached[0]>time.monotonic():return dict(cached[1])
    value=await _fetch_source(url)
    if len(_cache)>=128:_cache.pop(next(iter(_cache)))
    _cache[url]=(time.monotonic()+(3600 if value.get('status')=='fetched' else 60),value)
    return dict(value)


async def _fetch_source(url):
    try:
        resolved=url
        async with asyncio.timeout(12):
            for attempt in range(3):
                code,headers,body=await public_request('GET',resolved,timeout=8,limit=600000)
                if code not in (301,302,303,307,308) or not headers.get('location'):break
                if attempt==2:return {'url':url,'status':'not_fetched','note':'Слишком много перенаправлений'}
                # Every hop is a fresh DNS-pinned public HTTPS request, with no
                # forwarded credentials, cookies, or proxy environment.
                resolved=urljoin(resolved,headers['location'])
        if code != 200 or not any(t in headers.get('content-type','') for t in ('text/html','text/plain')):
            return {'url':url,'status':'not_fetched','httpStatus':code}
        parser=Text()
        parser.feed(body.decode('utf-8',errors='replace'))
        text=' '.join(parser.parts)[:12000]
        return {'url':url,'resolvedUrl':resolved,'status':'fetched','excerpt':text,'checkedAt':datetime.now(timezone.utc).isoformat(),
                'note':'Текст получен с сайта. Актуальность и соответствие результата подтверждает эксперт.'}
    except Exception:
        return {'url':url,'status':'not_fetched','note':'Недоступен или не прошёл проверку сетевой безопасности'}


async def research(query,references):
    urls=[]
    for ref in references:
        urls.extend(re.findall(r'https://[^\s<>"\)]+',ref.get('text','')))
    key=os.getenv('BRAVE_SEARCH_API_KEY')
    search_available=False
    if key:
        try:
            status,_,raw=await public_request('GET','https://api.search.brave.com/res/v1/web/search?'+urlencode({'q':query,'count':4,'search_lang':'ru'}),headers={'X-Subscription-Token':key},timeout=10,limit=500000)
            if status==200:
                search_available=True
                urls.extend(x['url'] for x in json.loads(raw).get('web',{}).get('results',[])[:4])
        except Exception:
            pass
    defaults=[(url,title) for pattern,url,title in DOCUMENTATION if re.search(pattern,query,re.I)]
    urls.extend(url for url,_ in defaults)
    results=await asyncio.gather(*(fetch_source(url) for url in list(dict.fromkeys(urls))[:4]))
    names=dict(defaults)
    for x in results:x['title']=names.get(x['url'],x['url'])
    # Keep relevant excerpts rather than resending entire manuals for every lesson.
    words=set(re.findall(r'[\w/]{4,}',query.lower()))
    for x in results:
        content=x.get('excerpt','');chunks=[content[i:i+1000] for i in range(0,len(content),1000)]
        scored=sorted(enumerate(chunks),key=lambda pair:(-sum(w in pair[1].lower() for w in words),pair[0]))[:2]
        if chunks:x['excerpt']='\n'.join(chunk for _,chunk in sorted(scored))
    return {'searchAvailable':search_available,'evidence':[x for x in results if x.get('status')=='fetched'],
            'unavailable':[{'url':x['url'],'title':x.get('title',x['url']),'status':'unverified'} for x in results if x.get('status')!='fetched'],
            'note':'Поиск по интернету выполнен' if search_available else 'Используются ссылки референсов и тематический каталог первичной документации. Для открытого поиска по произвольным темам настройте BRAVE_SEARCH_API_KEY. Получение страницы не подтверждает её применимость.'}
