import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../server.mjs';
test('Organizations, versions, websites, profile and consent enforce ownership',async()=>{
 const {server,db}=createApp(':memory:');await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;
 const call=async(p,body,cookie='',method=body?'POST':'GET')=>{const r=await fetch(base+'/api'+p,{method,headers:{Cookie:cookie,'X-Edentica':'1','Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});return {status:r.status,data:await r.json(),cookie:r.headers.get('set-cookie')?.split(';')[0]}};
 try{
  const author=(await call('/auth/register',{name:'Owner',email:'owner@test.local',password:'long-password'})).cookie;
  const member=(await call('/auth/register',{name:'Member',email:'member@test.local',password:'long-password'})).cookie;
  const outsider=(await call('/auth/register',{name:'Other',email:'other@test.local',password:'long-password'})).cookie;
  const c=(await call('/courses',{title:'Private',description:'Description',category:'Business'},author)).data.id;
  const payload={title:'Private',description:'Description',category:'Business',visibility:'private',modules:[{title:'One',content:'Material',threshold:70,questions:[{text:'Q',options:['A','B'],answer:0}]}]};
  await call('/courses/'+c,payload,author,'PATCH');await call('/courses/'+c,{...payload,title:'Revised'},author,'PATCH');
  const versions=(await call('/courses/'+c+'/versions',undefined,author)).data;assert.equal(versions.length,2);
  assert.equal((await call('/courses/'+c+'/restore',{versionId:versions.find(v=>v.snapshot.course.title==='Private'&&v.snapshot.modules.length===1).id},outsider)).status,404);
  assert.equal((await call('/courses/'+c+'/restore',{versionId:versions.find(v=>v.snapshot.modules.length===1).id},author)).status,200);
  await call('/courses/'+c+'/publish',{},author);
  const website=await call('/courses/'+c+'/website',{color:'#123456',intro:'Welcome',faq:[],template:'minimal'},author);assert.equal(website.status,200);
  assert.equal((await call('/sites/'+website.data.slug)).status,404);
  const org=(await call('/organizations',{name:'Company'},author)).data.id;
  assert.equal((await call('/organizations/'+org,undefined,outsider)).status,403);
  await call('/organizations/'+org+'/assign',{courseId:c},author);
  const inv=(await call('/organizations/'+org+'/invite',{},author)).data.token;
  await call('/organizations/accept',{token:inv},member);
  assert.equal((await call('/courses/'+c,undefined,member)).status,200);
  assert.equal((await call('/organizations/'+org+'/report',undefined,member)).status,403);
  assert.equal((await call('/organizations/'+org+'/report',undefined,author)).data.length,2);
  assert.equal((await call('/courses/'+c+'/copy',{},member)).status,403);
  assert.equal((await call('/courses/'+c+'/copy',{},author)).status,200);
  const consent=(await call('/identity',{name:'Own avatar',scope:'both',consent:true},author)).data.id;
  assert.equal((await call('/identity/'+consent+'/revoke',{},outsider)).status,404);
  assert.equal((await call('/identity/'+consent+'/revoke',{},author)).status,200);
  assert.equal((await call('/admin',undefined,author)).status,403);
  const memberId=(await call('/me',undefined,member)).data.user.id;
  await call('/organizations/'+org+'/members',{userId:memberId,remove:true},author);
  assert.equal((await call('/courses/'+c,undefined,member)).status,404);
  assert.equal((await call('/organizations/'+org,undefined,member)).status,403);
 }finally{await new Promise(r=>server.close(r));db.close()}
});
