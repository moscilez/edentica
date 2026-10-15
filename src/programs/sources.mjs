// Strict host allowlist avoids arbitrary URL fetches and access to local/cloud metadata.
const hosts=new Set(['docs.python.org','pandas.pydata.org','numpy.org','scipy.org','matplotlib.org','www.postgresql.org','www.sqlite.org','docs.docker.com','git-scm.com','kubernetes.io','prometheus.io','publication.pravo.gov.ru','pravo.gov.ru','profstandart.rosmintrud.ru','cloud.ru','developers.sber.ru']);
export async function probeSource(source,{fetchImpl=fetch}={}){
 const result={checkedAt:new Date().toISOString(),status:'unverified',note:'Проверка URL не подтверждает достоверность содержания или актуальность нормативного акта.'};
 let url;try{url=new URL(source.url)}catch{return {...result,access:'invalid_url'}}
 if(url.protocol!=='https:'||url.username||url.password||url.port&&url.port!=='443'||!hosts.has(url.hostname))return {...result,access:'manual_review',note:'Адрес вне списка первоисточников для автоматического доступа. Нужна ручная проверка.'};
 try{const response=await fetchImpl(url.href,{method:'HEAD',redirect:'manual',signal:AbortSignal.timeout(8000)});return {...result,access:response.ok?'reachable':response.status>=300&&response.status<400?'redirect_requires_review':'unavailable',httpStatus:response.status}}catch{return {...result,access:'unavailable'}}
}
