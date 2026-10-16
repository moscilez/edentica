import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../server.mjs';
import {demonstration} from '../src/programs/demo.mjs';
import {inspectSkeleton,inspectProgram,templateSections} from '../src/programs/validation.mjs';
import {gift,programDocx} from '../src/programs/exports.mjs';
import {createCloudClient} from '../src/programs/cloudru.mjs';
import {spawnSync} from 'node:child_process';
import {join} from 'node:path';
import {probeSource} from '../src/programs/sources.mjs';

test('Часы на всех уровнях, СРС, календарь и покрытие компетенций',()=>{
 const fixture=demonstration(),s=fixture.skeleton;
 assert.equal(inspectSkeleton(s).errors.length,0);assert.equal(inspectSkeleton(s,{totalHours:72}).errors[0].code,'requested_hours');
 for(const hours of [16,36,72,256,500]){
  const plan=structuredClone(s);plan.totalHours=hours;plan.finalHours=2;plan.selfStudyOnly=true;plan.modules=[{id:'m',title:'Стажировка',totalHours:hours-2,topics:[{id:'t',title:'Самостоятельная работа',totalHours:hours-2,hours:{lecture:0,practice:0,lab:0,self:hours-2},competencyIds:plan.competencies.map(c=>c.id)}]}];plan.calendar={weeks:4,sessions:[{week:1,hours:hours-2,topicIds:['t']},{week:4,hours:2,topicIds:['final']}]};assert.deepEqual(inspectSkeleton(plan).errors,[]);
  plan.modules[0].topics[0].hours.practice=1;assert.ok(inspectSkeleton(plan).errors.some(x=>x.code==='internship_contact'));
 }
 const bad=structuredClone(s);bad.modules[0].topics[0].hours.practice++;assert.ok(inspectSkeleton(bad).errors.some(x=>x.code==='topic_sum'));assert.ok(inspectSkeleton(bad).errors.some(x=>x.code==='total_sum'));
 const sections=Object.fromEntries(templateSections.general.map(x=>[x,'Содержательное описание раздела']));const p={...fixture,sections};assert.equal(inspectProgram(p).passed,true);
 p.materials['М1'].seminars=[];assert.equal(inspectProgram(p).passed,false);assert.ok(inspectProgram(p).errors.some(x=>x.code==='assessment_coverage'));
});

test('Cloud.ru adapter обращается только к Foundation Models и считает usage',async()=>{
 const prevKey=process.env.CLOUDRU_API_KEY,prevModel=process.env.CLOUDRU_MODEL;process.env.CLOUDRU_API_KEY='test-only';process.env.CLOUDRU_MODEL='test-model';
 try{
  const complete=createCloudClient({fetchImpl:async(url,options)=>{assert.equal(url,'https://foundation-models.api.cloud.ru/v1/chat/completions');const body=JSON.parse(options.body);assert.equal(body.model,'test-model');assert.equal(options.headers.Authorization,'Bearer test-only');return new Response(JSON.stringify({model:'test-model',choices:[{message:{content:'{"ok":true}'},finish_reason:'stop'}],usage:{prompt_tokens:20,completion_tokens:8}}))}});
  const result=await complete('test instruction',{request:'test'});assert.equal(result.value.ok,true);assert.deepEqual(result.usage,{inputTokens:20,outputTokens:8});
 }finally{if(prevKey===undefined)delete process.env.CLOUDRU_API_KEY;else process.env.CLOUDRU_API_KEY=prevKey;if(prevModel===undefined)delete process.env.CLOUDRU_MODEL;else process.env.CLOUDRU_MODEL=prevModel}
});

test('Единый API: уточнение → каркас → согласование → материалы → точечная правка → экспорт',async()=>{
 const fixture=demonstration();let moduleCalls=0;
 const complete=async(skill,payload)=>{
  let value;
  if(skill.includes('Навык 1'))value={requirements:{type:'general',totalHours:16,audience:'Школьники',entryLevel:'Без опыта',format:'Очно',assessment:'Проект'},questions:payload.answers?.level?[]:[{field:'level',question:'Какой входной уровень?'}],notes:[]};
  else if(skill.includes('Навык 2'))value=structuredClone(fixture.skeleton);
  else if(skill.includes('Навык 3')||skill.includes('Навык 5')){value=structuredClone(fixture.materials[payload.module.id]);moduleCalls++;if(payload.instruction)value.summary='Точечно обновлённое содержание'}
  else value={sections:Object.fromEntries(templateSections.general.map(x=>[x,'Раздел учебной программы для школьников'])),finalAssessment:fixture.finalAssessment,sources:fixture.sources};
  return {value,usage:{inputTokens:100,outputTokens:50},model:'mock-only'};
 };
 const {server,db}=createApp(':memory:',{hackathon:true,programs:{complete,allowUnconfigured:true}});await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;let cookie;
 const req=async(action,data={},otherCookie=cookie)=>{const r=await fetch(base+'/api/agent',{method:'POST',headers:{'Content-Type':'application/json','X-Edentica':'1',Cookie:otherCookie||''},body:JSON.stringify({action,...data})});return {status:r.status,data:r.headers.get('content-type')?.includes('json')?await r.json():await r.text()}};
 const wait=async id=>{for(let i=0;i<100;i++){const r=await req('get',{id});if(r.data.job?.state!=='running')return r.data;await new Promise(r=>setTimeout(r,10))}throw Error('worker timeout')};
 try{
  assert.equal((await fetch(base)).status,200);assert.match(await(await fetch(base)).text(),/<title>Edentica<\/title>/);
  assert.equal((await req('list')).status,401);
  const auth=await fetch(base+'/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json','X-Edentica':'1'},body:JSON.stringify({name:'Методист',email:'methodist@test.invalid',password:'password-test-long'})});cookie=auth.headers.get('set-cookie').split(';')[0];
  const created=await req('create',{request:'Курс Python на 16 часов'}),id=created.data.id;assert.equal(created.status,201);
  assert.equal((await req('get',{id},'session=unknown')).status,401);
  assert.equal((await req('generate',{id})).status,422);
  await req('analyze',{id});let p=await wait(id);assert.equal(p.state,'clarification');assert.equal(p.questions.length,1);
  assert.equal((await req('skeleton',{id})).status,422);
  await req('analyze',{id,answers:{level:'Начальный'}});p=await wait(id);assert.equal(p.state,'ready_for_skeleton');
  await req('skeleton',{id});p=await wait(id);assert.equal(p.state,'skeleton_review');assert.equal(p.job.state,'completed');
  assert.equal((await req('approve',{id,confirm:true,expectedRevision:0})).status,422);
  assert.equal((await req('approve',{id,confirm:true,expectedRevision:p.revision})).status,200);
  await req('generate',{id});p=await wait(id);assert.equal(p.job.state,'completed',p.job.error);assert.equal(p.report.passed,true);assert.equal(moduleCalls,3);assert.ok(p.usage.inputTokens>0);assert.ok(p.sources.every(x=>x.verification.status==='unverified'));
  const untouched=JSON.stringify(p.materials['М2']);
  await req('revise_module',{id,moduleId:'М1',instruction:'Обновить пояснение'});p=await wait(id);assert.equal(p.materials['М1'].summary,'Точечно обновлённое содержание');assert.equal(JSON.stringify(p.materials['М2']),untouched);assert.equal(moduleCalls,4);
  assert.notEqual(p.history.at(-1).materials['М1'].summary,p.materials['М1'].summary,'Предыдущая версия должна оставаться неизменной');
  assert.equal((await req('export',{id,format:'gift'})).status,200);assert.match((await req('export',{id,format:'gift'})).data,/::/);
  assert.ok((await req('export',{id,format:'json'})).data.report.coverage.length);
  assert.equal((await req('verify_source',{id,sourceId:p.sources[0].id,status:'confirmed',evidence:'проверено'})).status,422);
  await req('verify_source',{id,sourceId:p.sources[0].id,status:'confirmed',evidence:'https://docs.python.org/3/tutorial/ — проверено содержание'});p=(await req('get',{id})).data;assert.equal(p.sources[0].verification.status,'confirmed');
  const plan=structuredClone(p.skeleton);plan.goal+=' Проверка изменения.';await req('edit_skeleton',{id,expectedRevision:p.revision,skeleton:plan});p=(await req('get',{id})).data;assert.equal(p.approval,null);assert.deepEqual(p.materials,{});assert.ok(p.history.length>=2);
  assert.equal((await fetch(base+'/api/ai/status',{headers:{Cookie:cookie}})).status,410);
  assert.equal((await req('create',{request:'Задача',referenceIds:['чужой-файл']})).status,422);
 }finally{await new Promise(r=>server.close(r));db.close()}
});

test('Проверка URL не следует редиректам и не обращается к локальной сети',async()=>{
 let called=0;const fetchImpl=async(url,options)=>{called++;assert.equal(options.redirect,'manual');return new Response(null,{status:302,headers:{Location:'http://127.0.0.1/'}})};
 assert.equal((await probeSource({url:'https://127.0.0.1/secret'},{fetchImpl})).access,'manual_review');assert.equal(called,0);
 const result=await probeSource({url:'https://docs.python.org/3/'},{fetchImpl});assert.equal(called,1);assert.equal(result.access,'redirect_requires_review');assert.equal(result.status,'unverified');
});

test('DOCX собирается из шаблона АЦР; GIFT экранирует управляющие символы',async()=>{
 const f=demonstration();const p={...f,sections:Object.fromEntries(templateSections.general.map(x=>[x,'Описание раздела'])),templateSections:templateSections.general,demo:true};p.report=inspectProgram(p);
 const buffer=await programDocx(p);assert.equal(buffer.subarray(0,2).toString(),'PK');
 const python=process.env.PYTHON_PATH||join(process.env.USERPROFILE||'','.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe');
 const inspected=spawnSync(python,['-c',"import sys,io,zipfile,json; from docx import Document; b=sys.stdin.buffer.read(); d=Document(io.BytesIO(b)); t=' '.join(p.text for p in d.paragraphs); print(json.dumps({'tables':len(d.tables),'title':'Первые шаги в Python' in t,'draft':'ЧЕРНОВИК' in t,'blank':'Приказ № ______' in t}))"],{input:buffer,windowsHide:true});
 assert.equal(inspected.status,0);const doc=JSON.parse(inspected.stdout.toString('utf8'));assert.equal(doc.title,true);assert.equal(doc.draft,true);assert.equal(doc.blank,true);assert.ok(doc.tables>=5);
 p.materials['М1'].questions[0].text='a = {b} ~ #';const text=gift(p);assert.match(text,/\\=/);assert.match(text,/\\\{/);assert.match(text,/\\~/);
});
