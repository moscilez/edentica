import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../server.mjs';
import {validateGeneratedCourse} from '../src/ai.mjs';
test('AI queue: cost consent, preview and deduplication with test provider',async()=>{
 const course={title:'AI course',description:'Description',category:'AI',modules:[{title:'First module',content:'Material',threshold:70,questions:[{text:'Question',options:['A','B'],answer:0}]}]};
 let calls=0;const {server,db}=createApp(':memory:',{ai:{
  env:{OPENAI_API_KEY:'test-only',OPENAI_MODEL:'test-model',AI_INPUT_USD_PER_MILLION:'1',AI_OUTPUT_USD_PER_MILLION:'2',AI_DAILY_BUDGET_USD:'1',AI_GLOBAL_DAILY_BUDGET_USD:'1'},
  fetchImpl:async()=>{calls++;return {ok:true,json:async()=>({output:[{content:[{type:'output_text',text:JSON.stringify(course)}]}],usage:{input_tokens:100,output_tokens:200}})}}
 }});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const url=`http://127.0.0.1:${server.address().port}`;let cookie='';
 const call=async(p,b)=>{const r=await fetch(url+'/api'+p,{method:b?'POST':'GET',headers:{'X-Edentica':'1','Content-Type':'application/json',Cookie:cookie},body:b?JSON.stringify(b):undefined});if(r.headers.get('set-cookie'))cookie=r.headers.get('set-cookie').split(';')[0];return {status:r.status,data:await r.json()}};
 try{await call('/auth/register',{name:'Author',email:'ai@example.test',password:'safe-password'});
  assert.equal((await call('/ai/jobs',{prompt:'Create a course',requestKey:'one'})).status,400);
  const j=await call('/ai/jobs',{prompt:'Create a course',requestKey:'one',confirmCost:true});assert.equal(j.status,202);
  let job;for(let i=0;i<30;i++){job=await call('/ai/jobs/'+j.data.id);if(job.data.state==='ready')break;await new Promise(r=>setTimeout(r,10))}
  assert.equal(job.data.state,'ready');assert.equal(job.data.result.title,course.title);
  assert.equal((await call('/ai/jobs',{prompt:'Create a course',requestKey:'one',confirmCost:true})).data.id,j.data.id);assert.equal(calls,1);
  assert.equal(db.prepare('SELECT count(*) n FROM courses').get().n,0,'Generation cannot publish or apply a course automatically');
  assert.throws(()=>validateGeneratedCourse({...course,modules:[{...course.modules[0],questions:[{text:'Bad',options:['A','B'],answer:8}]}]}));
 }finally{await new Promise(r=>server.close(r));db.close()}
});
test('Cancellation prevents a delayed provider result from becoming ready',async()=>{
 let started;const began=new Promise(resolve=>{started=resolve});
 const {server,db}=createApp(':memory:',{ai:{env:{OPENAI_API_KEY:'fixture',OPENAI_MODEL:'fixture',AI_INPUT_USD_PER_MILLION:'1',AI_OUTPUT_USD_PER_MILLION:'2',AI_DAILY_BUDGET_USD:'1',AI_GLOBAL_DAILY_BUDGET_USD:'1'},fetchImpl:async(_url,options)=>new Promise((_resolve,reject)=>{started();options.signal.addEventListener('abort',()=>reject(Object.assign(Error('Aborted'),{name:'AbortError'})),{once:true})})}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;let cookie='';
 const call=async(p,b)=>{const r=await fetch(base+'/api'+p,{method:b?'POST':'GET',headers:{Cookie:cookie,'X-Edentica':'1','Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});if(r.headers.get('set-cookie'))cookie=r.headers.get('set-cookie').split(';')[0];return r.json()};
 try{await call('/auth/register',{name:'Author',email:'cancel@test.local',password:'long-password'});const j=await call('/ai/jobs',{requestKey:'cancel',prompt:'Create course',confirmCost:true});await began;await call('/ai/jobs/'+j.id+'/cancel',{});assert.equal((await call('/ai/jobs/'+j.id)).state,'cancelled');assert.equal(db.prepare('SELECT count(*) n FROM courses').get().n,0);assert.ok(db.prepare('SELECT estimate FROM generation_jobs WHERE id=?').get(j.id).estimate>0)}finally{await new Promise(r=>server.close(r));db.close()}
});
