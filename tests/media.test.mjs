import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../server.mjs';
test('Media adapter: confirmation, owner access, idempotency and private audio',async()=>{
 let calls=0;const {server,db}=createApp(':memory:',{media:{env:{OPENAI_API_KEY:'fixture-key',TTS_MODEL:'tts-1',TTS_VOICE:'alloy',TTS_USD_PER_MILLION_CHARACTERS:'15',AI_DAILY_BUDGET_USD:'1',AI_GLOBAL_DAILY_BUDGET_USD:'1',HEYGEN_API_KEY:'fixture-key',HEYGEN_STOCK_AVATAR_ID:'fixture-avatar',HEYGEN_STOCK_VOICE_ID:'fixture-voice',HEYGEN_STOCK_RIGHTS_CONFIRMED:'1',VIDEO_USD_PER_MINUTE:'0.2'},fetchImpl:async(url)=>{calls++;if(url.includes('/video/generate'))return {ok:true,json:async()=>({data:{video_id:'fixture-video'}})};if(url.includes('/video_status.get'))return {ok:true,json:async()=>({data:{status:'completed',video_url:'https://media.heygen.com/fixture.mp4'}})};return {ok:true,arrayBuffer:async()=>Buffer.from('ID3-test-fixture')}}}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;
 const call=async(p,b,cookie='',method=b?'POST':'GET')=>{const r=await fetch(base+'/api'+p,{method,headers:{Cookie:cookie,'X-Edentica':'1','Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return {status:r.status,data:await r.json(),cookie:r.headers.get('set-cookie')?.split(';')[0]}};
 try{const author=(await call('/auth/register',{name:'Owner',email:'media@test.local',password:'safe-password'})).cookie;const other=(await call('/auth/register',{name:'Other',email:'other@test.local',password:'safe-password'})).cookie;
  const id=(await call('/courses',{title:'Media',category:'AI',description:'Description'},author)).data.id;
  await call('/courses/'+id,{title:'Media',category:'AI',description:'Description',visibility:'private',modules:[{title:'Module',content:'Lecture',threshold:70,questions:[{text:'Question',options:['A','B'],answer:0}]}]},author,'PATCH');
  const m=(await call('/courses/'+id,undefined,author)).data.modules[0];
  const input={moduleId:m.id,kind:'speech',script:'Учебный сценарий',requestKey:'unique',confirmCost:true,confirmTransfer:true};
  assert.equal((await call('/courses/'+id+'/media',{...input,confirmTransfer:false},author)).status,400);
  assert.equal((await call('/courses/'+id+'/media',input,other)).status,404);
  const j=(await call('/courses/'+id+'/media',input,author)).data;
  let ready;for(let i=0;i<30;i++){ready=await call('/media/'+j.id,undefined,author);if(ready.data.state==='ready')break;await new Promise(r=>setTimeout(r,10))}
  assert.equal(ready.data.state,'ready');assert.equal((await call('/courses/'+id+'/media',input,author)).data.id,j.id);assert.equal(calls,1);
  assert.equal((await fetch(base+'/api/media/'+j.id+'/audio',{headers:{Cookie:author}})).status,200);
  assert.equal((await call('/media/'+j.id+'/audio',undefined,other)).status,404);
  const video=(await call('/courses/'+id+'/media',{...input,kind:'video',requestKey:'video'},author)).data;
  let done;for(let i=0;i<30;i++){done=await call('/media/'+video.id,undefined,author);if(done.data.state==='ready')break;await new Promise(r=>setTimeout(r,10))}
  assert.equal(done.data.state,'ready');assert.equal(done.data.output_url,'https://media.heygen.com/fixture.mp4');
 }finally{await new Promise(r=>server.close(r));db.close()}
});
