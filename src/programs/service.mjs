import {randomUUID} from 'node:crypto';
import {createCloudClient,cloudStatus} from './cloudru.mjs';
import {skills} from './skills.mjs';
import {assert,text,digest,inspectSkeleton,inspectModule,inspectProgram,templateSections} from './validation.mjs';
import {demonstration} from './demo.mjs';
import {gift,programPptx,programDocx,canExportPptx} from './exports.mjs';
import {join} from 'node:path';
import {probeSource} from './sources.mjs';

export function configurePrograms(db,{complete=createCloudClient(),allowUnconfigured=false}={}){
 db.exec(`CREATE TABLE IF NOT EXISTS program_projects(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES users(id),document TEXT NOT NULL,updated TEXT DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS program_events(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES program_projects(id),owner TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);`);
 // A restarted worker must not leave a project permanently locked.
 for(const row of db.prepare('SELECT id,document FROM program_projects').all()){const p=JSON.parse(row.document);if(p.job?.state==='running'||p.job?.state==='queued'){p.job.state='interrupted';p.job.error='Сервер перезапущен. Готовые модули сохранены; запустите продолжение.';db.prepare('UPDATE program_projects SET document=? WHERE id=?').run(JSON.stringify(p),row.id)}}
 let closed=false;const controllers=new Map();
 const load=(id,owner)=>{const row=db.prepare('SELECT document FROM program_projects WHERE id=? AND owner=?').get(id,owner);assert(row,'Программа не найдена');return JSON.parse(row.document)};
 const save=p=>{p.updatedAt=new Date().toISOString();db.prepare('UPDATE program_projects SET document=?,updated=? WHERE id=?').run(JSON.stringify(p),p.updatedAt,p.id)};
 const event=(p,action,detail={})=>db.prepare('INSERT INTO program_events VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)').run(randomUUID(),p.id,p.owner,action,JSON.stringify(detail));
 const revision=p=>{p.history=(p.history||[]).concat([structuredClone({revision:p.revision,skeleton:p.skeleton,materials:p.materials,sections:p.sections,finalAssessment:p.finalAssessment,sources:p.sources,approval:p.approval,at:new Date().toISOString()})]).slice(-15);p.revision++};
 const idle=p=>assert(!['running','queued'].includes(p.job?.state),'Дождитесь завершения текущей задачи или отмените её');
 const bumpUsage=(p,result)=>{const u=result.usage||{};p.usage.inputTokens+=u.inputTokens||0;p.usage.outputTokens+=u.outputTokens||0;p.usage.calls++;p.usage.model=result.model||cloudStatus().model;p.usage.estimatedRubles=process.env.CLOUDRU_INPUT_RUB_PER_MILLION&&process.env.CLOUDRU_OUTPUT_RUB_PER_MILLION?(p.usage.inputTokens*Number(process.env.CLOUDRU_INPUT_RUB_PER_MILLION)+p.usage.outputTokens*Number(process.env.CLOUDRU_OUTPUT_RUB_PER_MILLION))/1e6:null};
 const call=async(p,skill,payload,signal)=>{const result=await complete(skills[skill],payload,{signal});bumpUsage(p,result);return result.value};
 const references=p=>p.referenceIds.map(id=>db.prepare('SELECT name,text,truncated FROM learning_materials WHERE id=? AND user_id=?').get(id,p.owner)).filter(Boolean).map(x=>({...x,text:x.text.slice(0,22000),trust:'untrusted-reference'}));
 const launch=(p,kind,work)=>{
  idle(p);assert(controllers.size<2,'Сейчас выполняются две задачи. Повторите после завершения.');
  const controller=new AbortController();controllers.set(p.id,controller);p.job={id:randomUUID(),kind,state:'running',step:'Подготовка',completed:0,total:1,startedAt:new Date().toISOString()};save(p);event(p,'job_started',{kind});
  const timeout=setTimeout(()=>controller.abort(Error('Превышен лимит времени задачи')),kind==='skeleton'?175000:1180000);
  const persist=()=>{if(controller.signal.aborted||closed)throw Error('Задача отменена');save(p)};
  setImmediate(async()=>{try{await work(p,controller.signal,persist);persist();p.job.state='completed';p.job.completed=p.job.total;if(!closed)event(p,'job_completed',{kind})}catch(e){p.job.state=controller.signal.aborted?'cancelled':'failed';p.job.error=e.message.slice(0,500);if(p.state==='generating')p.state='needs_revision';if(!closed)event(p,'job_failed',{kind,error:p.job.error})}finally{clearTimeout(timeout);p.job.finishedAt=new Date().toISOString();p.job.elapsedSeconds=Math.round((Date.now()-Date.parse(p.job.startedAt))/1000);controllers.delete(p.id);if(!closed)save(p)}});
  return p;
 };
 const addSources=(p,sources)=>{for(const source of sources||[]){if(!text(source.title,2000))continue;const match=p.sources.find(x=>x.url&&x.url===source.url||x.title===source.title);if(!match)p.sources.push({id:randomUUID(),title:source.title,url:typeof source.url==='string'?source.url.slice(0,3000):'',kind:source.kind||'literature',verification:{status:'unverified'}})}};
 const routes=async({p:path,req,body,u,send,login,required,res})=>{
  if(path!=='/api/agent')return false;login();
  const action=req.method==='GET'?'status':required(body.action,40);
  if(action==='status'){send({...cloudStatus(),pptx:canExportPptx(),skills:Object.keys(skills),humanApprovalRequired:true,foreignProvidersEnabled:false});return true}
  if(action==='list'){send(db.prepare('SELECT document FROM program_projects WHERE owner=? ORDER BY updated DESC').all(u.id).map(row=>{const p=JSON.parse(row.document);return {id:p.id,title:p.skeleton?.title||p.request.slice(0,90),state:p.state,revision:p.revision,updatedAt:p.updatedAt,demo:p.demo,job:p.job}}));return true}
  if(action==='create'||action==='demo'){
   assert(db.prepare('SELECT count(*) n FROM program_projects WHERE owner=?').get(u.id).n<100,'Лимит: 100 программ');
   const request=action==='demo'?'Демонстрационный пример Python для школьников':required(body.request,20000),referenceIds=body.referenceIds||[];
   assert(Array.isArray(referenceIds)&&referenceIds.length<=5,'Добавьте не более пяти референсов');for(const id of referenceIds)assert(db.prepare('SELECT 1 FROM learning_materials WHERE id=? AND user_id=?').get(id,u.id),'Референс недоступен');
   const p={id:randomUUID(),owner:u.id,request,referenceIds,state:'brief',revision:1,requirements:{},questions:[],notes:[],materials:{},sections:{},sources:[],history:[],usage:{inputTokens:0,outputTokens:0,calls:0,estimatedRubles:null},createdAt:new Date().toISOString(),demo:action==='demo',job:null,approval:null};
   if(p.demo){const fixture=demonstration();Object.assign(p,fixture,{state:'skeleton_review',sections:Object.fromEntries(templateSections.general.map(t=>[t,'Демонстрационное заполнение раздела «'+t+'». Для реальной программы используйте генерацию Cloud.ru и экспертную проверку.']))});p.notes=['Это заранее подготовленный пример для проверки интерфейса. Он не сгенерирован моделью.'];}
   db.prepare('INSERT INTO program_projects(id,owner,document) VALUES(?,?,?)').run(p.id,u.id,JSON.stringify(p));event(p,'created',{demo:p.demo});send(p,201);return true;
  }
  const p=load(required(body.id,80),u.id);
  if(action==='get'){send({...p,report:p.skeleton?inspectProgram(p):null,events:db.prepare('SELECT action,detail,created FROM program_events WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 30').all(p.id)});return true}
  if(action==='cancel'){const c=controllers.get(p.id);assert(c,'Активной задачи нет');c.abort();send({ok:true});return true}
  if(action==='analyze'||action==='skeleton'){
   assert(!p.demo,'Демонстрационный пример не вызывает модель. Создайте новую программу.');assert(allowUnconfigured||cloudStatus().configured,'Cloud.ru не настроен. Добавьте CLOUDRU_API_KEY и CLOUDRU_MODEL.');
   if(action==='analyze'){
    assert(!p.approval,'После согласования редактируйте каркас с новым утверждением');
    assert(!body.answers||typeof body.answers==='object'&&!Array.isArray(body.answers)&&JSON.stringify(body.answers).length<12000,'Проверьте ответы');p.answers={...p.answers,...body.answers};
    send(launch(p,'intake',async(p,signal,persist)=>{p.job.step='Уточнение требований';const data=await call(p,'intake',{request:p.request,answers:p.answers,references:references(p)},signal);assert(data.requirements&&Array.isArray(data.questions)&&data.questions.length<=5&&data.questions.every(q=>text(q.question,2000)&&text(q.field,80)),'Некорректный разбор запроса');p.requirements=data.requirements;p.questions=data.questions;p.notes=data.notes||[];
     const count=p.request.match(/(?:на\s+|из\s+)?(\d{1,3})\s+вопрос/iu);if(count)p.requirements.testQuestionCount=Number(count[1]);
     const needed=['type','totalHours','audience','entryLevel','format','assessment'];const missing=needed.filter(k=>!p.requirements[k]);
     for(const field of missing)if(!p.questions.some(x=>x.field===field)&&p.questions.length<5)p.questions.push({field,question:({type:'Какой тип программы: повышение квалификации или общеразвивающая?',totalHours:'Какой точный объём в академических часах?',audience:'Для кого программа?',entryLevel:'Что слушатели уже знают?',format:'Какая форма обучения и итоговой аттестации?',assessment:'Как проходит итоговая аттестация?'})[field]});
     p.state=p.questions.length||missing.length?'clarification':'ready_for_skeleton';persist();}));return true;
   }
   assert(p.state==='ready_for_skeleton'||p.state==='skeleton_review','Сначала заполните и уточните требования');
   send(launch(p,'skeleton',async(p,signal,persist)=>{p.job.step='Карта компетенций и часы';let candidate,issues;
    for(let attempt=0;attempt<2;attempt++){candidate=await call(p,'skeleton',{request:p.request,requirements:p.requirements,references:references(p),previous:candidate,validationErrors:issues},signal);issues=inspectSkeleton(candidate,p.requirements).errors;if(!issues.length)break}
    assert(!issues.length,'Каркас не прошёл проверку: '+issues.slice(0,3).map(x=>x.message).join('; '));revision(p);p.skeleton=candidate;p.materials={};p.sections={};p.finalAssessment=null;p.approval=null;p.state='skeleton_review';persist();}));return true;
  }
  if(action==='edit_skeleton'){
   idle(p);assert(body.expectedRevision===p.revision,'Версия изменилась. Обновите программу.');const report=inspectSkeleton(body.skeleton,p.requirements);assert(!report.errors.length,report.errors.map(x=>x.message).join('; '));
   const previous=p.skeleton,next=body.skeleton,kept={};
   const globalChange=['type','goal','audience','entryLevel','format','assessment','selfStudyOnly'].some(k=>digest(previous?.[k])!==digest(next[k]));
   if(!globalChange)for(const m of next.modules){const old=previous?.modules.find(x=>x.id===m.id);const ids=new Set(m.topics.flatMap(t=>t.competencyIds));if(old&&digest(old)===digest(m)&&digest(previous.competencies.filter(c=>ids.has(c.id)))===digest(next.competencies.filter(c=>ids.has(c.id)))&&p.materials[m.id])kept[m.id]=p.materials[m.id]}
   revision(p);p.skeleton=next;p.approval=null;p.materials=kept;p.sections={};p.finalAssessment=null;p.state='skeleton_review';save(p);event(p,'skeleton_edited',{preservedModules:Object.keys(kept)});send(p);return true;
  }
  if(action==='approve'){
   idle(p);assert(p.skeleton,'Нет каркаса');assert(body.expectedRevision===p.revision,'Версия изменилась. Обновите программу.');assert(body.confirm===true,'Подтвердите цель, компетенции и часы');const r=inspectSkeleton(p.skeleton,p.requirements);assert(!r.errors.length,r.errors.map(x=>x.message).join('; '));p.approval={by:u.id,at:new Date().toISOString(),digest:digest(p.skeleton),revision:p.revision};p.state='approved';save(p);event(p,'skeleton_approved',{revision:p.revision,digest:p.approval.digest});send(p);return true;
  }
  if(action==='generate'||action==='revise_module'){
   assert(p.approval?.digest===digest(p.skeleton),'Методист должен утвердить текущую цель, компетенции и часы');assert(!p.demo,'Демо не вызывает модель');assert(allowUnconfigured||cloudStatus().configured,'Cloud.ru не настроен');
   const target=action==='revise_module'?p.skeleton.modules.find(m=>m.id===body.moduleId):null;if(action==='revise_module'){assert(target,'Модуль не найден');assert(p.materials[target.id],'Сначала создайте комплект модуля');required(body.instruction,6000)}
   send(launch(p,action,async(p,signal,persist)=>{
    p.job.total=target?1:p.skeleton.modules.length+1;p.state='generating';
    for(const [i,m]of (target?[target]:p.skeleton.modules).entries()){
     p.job.step='Материалы: '+m.title;p.job.completed=i;persist();
     if(!target&&p.materials[m.id]&&!inspectModule(p.materials[m.id],m,p.skeleton).length)continue;
     let candidate,issues;for(let attempt=0;attempt<2;attempt++){candidate=await call(p,target?'revise':'module',{request:p.request,requirements:p.requirements,skeleton:p.skeleton,module:m,questionQuota:p.requirements.testQuestionCount?Math.floor(p.requirements.testQuestionCount/p.skeleton.modules.length)+(p.skeleton.modules.findIndex(x=>x.id===m.id)<p.requirements.testQuestionCount%p.skeleton.modules.length?1:0):null,referenceExcerpts:references(p),previous:target?p.materials[m.id]:candidate,instruction:body.instruction,validationErrors:issues},signal);issues=inspectModule(candidate,m,p.skeleton);if(!issues.length)break}
     assert(!issues.length,'Модуль не прошёл проверку: '+issues.slice(0,3).map(x=>x.message).join('; '));if(target)revision(p);p.materials[m.id]=candidate;addSources(p,candidate.sources);persist();
    }
    if(!target){p.job.step='Разделы шаблона и итоговая аттестация';persist();const data=await call(p,'sections',{skeleton:p.skeleton,sectionTitles:templateSections[p.skeleton.type],requirements:p.requirements,knownSources:p.sources},signal);assert(data.sections&&data.finalAssessment,'Модель не заполнила разделы');p.sections=data.sections;p.finalAssessment=data.finalAssessment;addSources(p,data.sources);persist()}
    p.state=inspectProgram(p).passed?'draft_ready':'needs_revision';persist();
   }));return true;
  }
  if(action==='validate'){send(inspectProgram(p));return true}
  if(action==='check_sources'){
   idle(p);send(launch(p,'sources',async(p,signal,persist)=>{p.job.total=p.sources.length;for(const [i,source] of p.sources.entries()){if(signal.aborted)break;p.job.step='Проверка URL: '+source.title;p.job.completed=i;source.accessCheck=await probeSource(source);persist()}}));return true;
  }
  if(action==='verify_source'){
   idle(p);const source=p.sources.find(x=>x.id===body.sourceId);assert(source,'Источник не найден');assert(['confirmed','rejected'].includes(body.status),'Выберите статус');const evidence=required(body.evidence,4000);assert(/^https:\/\//.test(evidence),'Укажите HTTPS ссылку на первоисточник и сведения о проверке');source.verification={status:body.status,evidence,by:u.id,at:new Date().toISOString(),method:'human_review'};save(p);event(p,'source_reviewed',{sourceId:source.id,status:body.status});send(p);return true;
  }
  if(action==='restore'){
   idle(p);const snapshot=p.history.find(x=>x.revision===body.revision);assert(snapshot,'Версия не найдена');revision(p);for(const k of ['skeleton','materials','sections','finalAssessment','sources'])p[k]=snapshot[k];p.approval=null;p.state='skeleton_review';save(p);event(p,'restored',{revision:body.revision});send(p);return true;
  }
  if(action==='export'){
   assert(p.skeleton,'Нет каркаса для выгрузки');const report=inspectProgram(p);let bytes,mime,ext;
   if(body.format==='json'){bytes=Buffer.from(JSON.stringify({...p,report},null,2));mime='application/json';ext='json'}
   else{
    assert(p.approval?.digest===digest(p.skeleton),'Перед выгрузкой комплекта согласуйте каркас');assert(report.passed,'Исправьте ошибки автопроверки перед выгрузкой комплекта');
    if(body.format==='gift'){bytes=Buffer.from(gift(p));mime='text/plain; charset=utf-8';ext='gift'}
    else if(body.format==='docx'){bytes=await programDocx({...p,report,templateSections:templateSections[p.skeleton.type]});mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document';ext='docx'}
    else if(body.format==='pptx'){bytes=await programPptx(p,body.moduleId,join(process.cwd(),'output/programs',p.id));mime='application/vnd.openxmlformats-officedocument.presentationml.presentation';ext='pptx'}else assert(false,'Неизвестный формат');
   }
   event(p,'export',{format:ext});res.writeHead(200,{'Content-Type':mime,'Content-Disposition':`attachment; filename="edentica-draft-${p.id}.${ext}"`});res.end(bytes);return true;
  }
  assert(false,'Неизвестная команда агента');
 };
 return {routes,close(){closed=true;for(const controller of controllers.values())controller.abort();controllers.clear()}};
}
