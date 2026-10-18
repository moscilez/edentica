"""Evidence retrieval. A fetched page is evidence, never automatic expert approval."""
import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
import re
from urllib.parse import urlencode

from .net import public_request


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
    try:
        code, headers, body = await public_request('GET',url,timeout=8,limit=600000)
        if code != 200 or not any(t in headers.get('content-type','') for t in ('text/html','text/plain')):
            return {'url':url,'status':'not_fetched','httpStatus':code}
        parser=Text()
        parser.feed(body.decode('utf-8',errors='replace'))
        text=' '.join(parser.parts)[:6000]
        return {'url':url,'status':'fetched','excerpt':text,'checkedAt':datetime.now(timezone.utc).isoformat(),
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
    results=await asyncio.gather(*(fetch_source(url) for url in list(dict.fromkeys(urls))[:4]))
    return {'searchAvailable':search_available,'evidence':[x for x in results if x.get('status')=='fetched'],
            'note':'Поиск по интернету выполнен' if search_available else 'Поисковый API не настроен или недоступен. Используются ссылки из референсов; модельные ссылки остаются неподтверждёнными.'}
