const base='https://foundation-models.api.cloud.ru/v1';
export function cloudStatus(){return {provider:'Cloud.ru Evolution Foundation Models',configured:!!(process.env.CLOUDRU_API_KEY&&process.env.CLOUDRU_MODEL),model:process.env.CLOUDRU_MODEL||null,endpoint:base}}
export function createCloudClient({fetchImpl=fetch}={}){
 return async function complete(skill,payload,{signal}={}){
  if(!cloudStatus().configured)throw Object.assign(Error('Настройте CLOUDRU_API_KEY и CLOUDRU_MODEL в локальном .env'),{status:503});
  const response=await fetchImpl(base+'/chat/completions',{method:'POST',signal:signal?AbortSignal.any([signal,AbortSignal.timeout(150000)]):AbortSignal.timeout(150000),headers:{'Content-Type':'application/json',Authorization:'Bearer '+process.env.CLOUDRU_API_KEY},body:JSON.stringify({model:process.env.CLOUDRU_MODEL,temperature:0.2,max_completion_tokens:12000,messages:[{role:'system',content:skill},{role:'user',content:JSON.stringify(payload)}]})});
  if(!response.ok)throw Object.assign(Error('Cloud.ru вернул HTTP '+response.status+'. Проверьте модель, доступы и квоты.'),{status:502});
  const data=await response.json();if(data.choices?.[0]?.finish_reason==='length')throw Error('Ответ модели обрезан лимитом токенов. Уменьшите модуль.');
  const raw=data.choices?.[0]?.message?.content;let value;
  try{value=JSON.parse(String(raw).replace(/^\s*```(?:json)?\s*/,'').replace(/\s*```\s*$/,''))}catch{throw Error('Модель вернула некорректный JSON')}
  return {value,usage:{inputTokens:data.usage?.prompt_tokens||0,outputTokens:data.usage?.completion_tokens||0},model:data.model||process.env.CLOUDRU_MODEL};
 }
}
