import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../server.mjs';
test('Copilot preview changes exactly one module; stale proposal rejected; tutor uses source text',async()=>{
 const generated={title:'Course',description:'Description',category:'AI',modules:[{title:'Updated module',content:'Новый материал о корреляции.',threshold:70,questions:[{text:'Question',options:['A','B'],answer:0}]}]};
 const {server,db}=createApp(':memory:',{assistant:{env:{OPENAI_API_KEY:'fixture',OPENAI_MODEL:'fixture',AI_INPUT_USD_PER_MILLION:'1',AI_OUTPUT_USD_PER_MILLION:'2',AI_DAILY_BUDGET_USD:'10',AI_GLOBAL_DAILY_BUDGET_USD:'10'},fetchImpl:async()=>({ok:true,json:async()=>({output:[{content:[{type:'output_text',text:JSON.stringify(generated)}]}]})})}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;
 const call=async(p,b,cookie='',method=b?'POST':'GET')=>{const r=await fetch(base+'/api'+p,{method,headers:{Cookie:cookie,'X-Edentica':'1','Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return {status:r.status,data:await r.json(),cookie:r.headers.get('set-cookie')?.split(';')[0]}};
 try{
  const author=(await call('/auth/register',{name:'Owner',email:'assistant@test.local',password:'long-password'})).cookie;
  const student=(await call('/auth/register',{name:'Student',email:'student@test.local',password:'long-password'})).cookie;
  const id=(await call('/courses',{title:'Course',description:'Description',category:'AI'},author)).data.id;
  const m=(title,content)=>({title,content,threshold:70,questions:[{text:'Q',options:['A','B'],answer:0}]});
  const draft={title:'Course',description:'Description',category:'AI',visibility:'public',modules:[m('First','Основы науки.'),m('Second','Корреляция означает совместное изменение показателей.')]};
  await call('/courses/'+id,draft,author,'PATCH');const before=(await call('/courses/'+id,undefined,author)).data.modules;
  const preview=(await call('/courses/'+id+'/copilot',{moduleId:before[0].id,message:'Добавить пример',requestKey:'one',confirmCost:true,confirmTransfer:true},author)).data;
  assert.equal((await call('/courses/'+id,undefined,author)).data.modules[0].title,'First');
  assert.equal((await call('/courses/'+id+'/apply-copilot',{requestId:preview.requestId},author)).status,200);
  const after=(await call('/courses/'+id,undefined,author)).data.modules;assert.equal(after[0].id,before[0].id);assert.equal(after[0].title,'Updated module');assert.deepEqual(after[1],before[1]);
  const stale=(await call('/courses/'+id+'/copilot',{moduleId:after[0].id,message:'Добавить пример',requestKey:'two',confirmCost:true,confirmTransfer:true},author)).data;
  await call('/courses/'+id,draft,author,'PATCH');assert.equal((await call('/courses/'+id+'/apply-copilot',{requestId:stale.requestId},author)).status,409);
  await call('/courses/'+id+'/publish',{},author);await call('/courses/'+id+'/enroll',{},student);
  const firstModule=(await call('/courses/'+id,undefined,student)).data.modules[0];await call('/modules/'+firstModule.id+'/attempt',{answers:[0]},student);
  const result=await call('/courses/'+id+'/tutor',{message:'Что означает корреляция?',searchOnly:true},student);assert.equal(result.status,200);assert.equal(result.data.sources[0].title,'Second');
  db.prepare('INSERT INTO exam_sessions VALUES(?,?,?)').run((await call('/me',undefined,student)).data.user.id,id,Date.now()+60000);
  assert.equal((await call('/courses/'+id+'/tutor',{message:'Что означает корреляция?',searchOnly:true},student)).status,403);
 }finally{await new Promise(r=>server.close(r));db.close()}
});
