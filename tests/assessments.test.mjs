import {test} from 'node:test';
import assert from 'node:assert/strict';
import {gradeAssessment,normalizeQuestions} from '../src/assessments.mjs';
import {createApp} from '../server.mjs';
test('Six automatic question types grade answers on server and reject duplicate order',()=>{
 const qs=[{type:'single',text:'Q',options:['A','B'],answer:0},{type:'multiple',text:'Q',options:['A','B','C'],answer:[0,2]},{type:'truefalse',text:'Q',options:['Верно','Неверно'],answer:1},{type:'short',text:'Q',answer:'Корреляция'},{type:'ordering',text:'Q',options:['A','B'],answer:[1,0]},{type:'matching',text:'Q',options:['A','B'],prompts:['X','Y'],answer:[1,0]}];
 assert.equal(gradeAssessment(qs,[0,[2,0],1,'  КОРРЕЛЯЦИЯ ',[1,0],[1,0]]).score,100);
 assert.throws(()=>gradeAssessment(qs,[0,[2,0],1,'x',[1,1],[1,0]]));
 assert.throws(()=>normalizeQuestions([{type:'multiple',text:'Q',options:['A','B'],answer:[0,0]}]));
});
test('Manual work gates progress until owner review and cannot be graded twice',async()=>{
 const {server,db}=createApp(':memory:');await new Promise(r=>server.listen(0,'127.0.0.1',r));const url=`http://127.0.0.1:${server.address().port}`;
 const call=async(p,b,cookie='',method=b?'POST':'GET')=>{const r=await fetch(url+'/api'+p,{method,headers:{Cookie:cookie,'X-Edentica':'1','Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return {status:r.status,data:await r.json(),cookie:r.headers.get('set-cookie')?.split(';')[0]}};
 try{const author=(await call('/auth/register',{name:'Author',email:'grading@test.local',password:'long-password'})).cookie;const student=(await call('/auth/register',{name:'Student',email:'student@test.local',password:'long-password'})).cookie;
  const id=(await call('/courses',{title:'Course',description:'Description',category:'AI'},author)).data.id;
  await call('/courses/'+id,{title:'Course',description:'Description',category:'AI',modules:[{title:'Practice',content:'Материал',threshold:70,questions:[{type:'practical',text:'Приведите пример',answer:'Пример должен раскрывать тему',points:5}]}]},author,'PATCH');await call('/courses/'+id+'/publish',{},author);await call('/courses/'+id+'/enroll',{},student);
  const module=(await call('/courses/'+id,undefined,student)).data.modules[0];assert.equal('answer' in module.questions[0],false);
  const r=await call('/modules/'+module.id+'/attempt',{answers:['Мой пример']},student);assert.equal(r.data.pending,true);assert.equal(r.data.passed,false);
  assert.equal((await call('/courses/'+id+'/exam',undefined,student)).status,403);
  const pending=(await call('/courses/'+id+'/grading',undefined,author)).data[0];assert.equal((await call('/grading/'+pending.attempt_id,{points:5,feedback:'Хороший пример'},student)).status,403);
  assert.equal((await call('/grading/'+pending.attempt_id,{points:5,feedback:'Хороший пример'},author)).data.passed,true);
  assert.equal((await call('/grading/'+pending.attempt_id,{points:5,feedback:'Повтор'},author)).status,409);
  assert.equal((await call('/courses/'+id,undefined,student)).data.modules[0].passed,true);
  assert.equal((await call('/notifications',undefined,student)).data.length,1);
 }finally{await new Promise(r=>server.close(r));db.close()}
});
