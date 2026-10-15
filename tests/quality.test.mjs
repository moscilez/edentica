import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../server.mjs';
test('Sensitive publication requires human approval bound to current content',async()=>{
 const {server,db}=createApp(':memory:');await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;const previousAdmin=process.env.ADMIN_USER_ID;
 const call=async(p,b,cookie='',method=b?'POST':'GET')=>{const r=await fetch(base+'/api'+p,{method,headers:{Cookie:cookie,'X-Edentica':'1','Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return {status:r.status,data:await r.json(),cookie:r.headers.get('set-cookie')?.split(';')[0]}};
 try{
  const author=(await call('/auth/register',{name:'Author',email:'author@quality.test',password:'long-password'})).cookie;
  const admin=(await call('/auth/register',{name:'Admin',email:'admin@quality.test',password:'long-password'})).cookie;
  process.env.ADMIN_USER_ID=(await call('/me',undefined,admin)).data.user.id;
  const id=(await call('/courses',{title:'Медицинская информация',description:'Основы',category:'Медицина'},author)).data.id;
  const draft={title:'Медицинская информация',description:'Основы',category:'Медицина',modules:[{title:'Модуль',content:'Материал для экспертной проверки.',threshold:70,questions:[{text:'Q',options:['A','B'],answer:0}]}]};
  await call('/courses/'+id,draft,author,'PATCH');assert.equal((await call('/courses/'+id+'/publish',{},author)).status,409);
  const inspected=(await call('/admin/courses/'+id,undefined,admin)).data;
  assert.equal((await call('/admin/moderate',{action:'approve-sensitive-course',target:id,reviewerName:'Test expert',statement:'Test-only human review',digest:inspected.digest},author)).status,403);
  await call('/admin/moderate',{action:'approve-sensitive-course',target:id,reviewerName:'Test expert',statement:'Test-only human review',digest:inspected.digest},admin);
  assert.equal((await call('/courses/'+id+'/quality',undefined,author)).data.expert.approved,true);
  await call('/courses/'+id,{...draft,description:'Изменённая программа'},author,'PATCH');assert.equal((await call('/courses/'+id+'/publish',{},author)).status,409);
  assert.equal((await call('/admin/moderate',{action:'approve-sensitive-course',target:id,reviewerName:'Test expert',statement:'Test-only review',digest:inspected.digest},admin)).status,409);
  await call('/admin/moderate',{action:'hide-course',target:id},admin);
  const copy=(await call('/courses/'+id+'/copy',{},author)).data.id;
  const blocked=await call('/courses/'+copy+'/publish',{},author);assert.equal(blocked.status,409);assert.match(blocked.data.error,/модератор/);
 }finally{if(previousAdmin===undefined)delete process.env.ADMIN_USER_ID;else process.env.ADMIN_USER_ID=previousAdmin;await new Promise(r=>server.close(r));db.close()}
});
