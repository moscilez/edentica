import {createHash} from 'node:crypto';

export const digest = value => createHash('sha256').update(JSON.stringify(value??null)).digest('hex');
export const workKinds = ['lecture','practice','lab','self'];
export const templateNames = {dpp:'Повышение квалификации',general:'Общеразвивающая программа'};
export const templateSections = {
 dpp:['Аннотация программы','Цель реализации программы','Планируемые результаты обучения','Программа разработана на основе','Перечень профессиональных компетенций','Требования к слушателям','Форма обучения','Объём программы','Выдаваемый документ','Учебный план','Учебно-тематический план','Календарный учебный график','Рабочая программа учебных дисциплин','Оценка качества освоения программы','Материально-техническое обеспечение','Учебно-методическое и информационное обеспечение','Организация образовательного процесса','Кадровое обеспечение'],
 general:['Пояснительная записка','Актуальность программы','Категории обучающихся','Цель и задачи программы','Сроки реализации','Планируемые результаты обучения','Календарный учебный график','Содержание программы','Учебный план','Учебно-тематический план','Оценочные материалы','Методические материалы','Организационно-педагогические условия реализации программы','Материально-технические условия реализации программы','Учебно-методическое и информационное обеспечение программы','Литература','Основная литература','Дополнительная литература','Интернет-ресурсы','Кадровое обеспечение программы']
};
export function assert(condition,message){if(!condition)throw Object.assign(Error(message),{status:422})}
export function text(value,max=10000){return typeof value==='string'&&value.trim().length>0&&value.length<=max&&!/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)}
export const sumHours = h => workKinds.reduce((n,k)=>n+(Number.isInteger(h?.[k])?h[k]:0),0);
export function inspectSkeleton(s,requirements={}){
 try{return inspectSkeletonInternal(s,requirements)}catch{return {errors:[{code:'schema',path:'skeleton',message:'Неверная структура каркаса: проверьте массивы компетенций, модулей, тем и календаря'}],warnings:[]}}
}
function inspectSkeletonInternal(s,requirements={}){
 const errors=[],warnings=[]; const error=(code,path,message)=>errors.push({code,path,message});
 if(!s||typeof s!=='object')return {errors:[{code:'schema',path:'',message:'Ожидается объект каркаса'}],warnings};
 if(!templateNames[s.type])error('template','type','Выберите один из двух шаблонов АЦР');
 for(const key of ['title','goal','audience','entryLevel','format','assessment'])if(!text(s[key],4000))error('required',key,'Не заполнено поле '+key);
 if(!Number.isInteger(s.totalHours)||s.totalHours<16||s.totalHours>10000)error('hours','totalHours','Объём: целое число от 16 до 10000 академических часов');
 if(requirements.totalHours&&s.totalHours!==requirements.totalHours)error('requested_hours','totalHours','Объём не совпадает с запросом');
 if(requirements.type&&s.type!==requirements.type)error('requested_type','type','Шаблон не совпадает с запросом');
 if(requirements.selfStudyOnly&&!s.selfStudyOnly)error('requested_delivery','selfStudyOnly','Запрошена стажировка без контактной работы');
 if(!Array.isArray(s.competencies)||s.competencies.length<1||s.competencies.length>40)error('competencies','competencies','Нужно от 1 до 40 результатов обучения');
 const ids=new Set();
 for(const [i,c] of (Array.isArray(s.competencies)?s.competencies:[]).entries()){
  if(!text(c.id,80)||ids.has(c.id))error('id',`competencies.${i}`,'Код компетенции должен быть уникальным');ids.add(c.id);
  for(const k of ['title','knowledge','abilities','skills'])if(!text(c[k],3000))error('competency',`competencies.${i}.${k}`,'Заполните результат и знания, умения, навыки');
  if(s.type==='general'&&c.standard)error('standard',`competencies.${i}.standard`,'Общеразвивающая программа не требует трудовых функций');
  if(s.type==='dpp'&&(!c.standard?.code||!c.standard?.functionCode))warnings.push({code:'standard_missing',path:`competencies.${i}`,message:'Профстандарт и код трудовой функции требуют подтверждения методистом'});
 }
 let total=0,practical=0;const topicIds=new Set(),moduleIds=new Set(),covered=new Set();
 if(!Array.isArray(s.modules)||!s.modules.length||s.modules.length>40)error('modules','modules','Нужно от 1 до 40 модулей');
 for(const [mi,m]of (Array.isArray(s.modules)?s.modules:[]).entries()){
  if(!text(m.id,80)||moduleIds.has(m.id))error('id',`modules.${mi}.id`,'Уникальный код модуля обязателен');moduleIds.add(m.id);
  if(!text(m.title,300))error('title',`modules.${mi}.title`,'Название модуля обязательно');
  if(!Array.isArray(m.topics)||!m.topics.length||m.topics.length>30)error('topics',`modules.${mi}.topics`,'Нужно от 1 до 30 тем');
  let moduleTotal=0;
  for(const [ti,t]of (Array.isArray(m.topics)?m.topics:[]).entries()){
   const path=`modules.${mi}.topics.${ti}`;
   if(!text(t.id,80)||topicIds.has(t.id))error('id',path,'Уникальный код темы обязателен');topicIds.add(t.id);
   if(!text(t.title,300))error('title',path,'Название темы обязательно');
   for(const k of workKinds)if(!Number.isInteger(t.hours?.[k])||t.hours[k]<0)error('hours',path+'.hours.'+k,'Часы — неотрицательные целые числа');
   const n=sumHours(t.hours);if(!n)error('hours',path,'Тема не может иметь нулевой объём');
   if(t.totalHours!==n)error('topic_sum',path,`Сумма видов работы ${n} не равна объёму темы ${t.totalHours}`);
   if(!Array.isArray(t.competencyIds)||!t.competencyIds.length)error('coverage',path,'Свяжите тему с результатом обучения');
   for(const id of t.competencyIds||[])if(!ids.has(id))error('reference',path,'Неизвестная компетенция '+id);else covered.add(id);
   if(s.selfStudyOnly&&(t.hours?.lecture||t.hours?.practice||t.hours?.lab))error('internship_contact',path,'В стажировке без контактной работы лекции, практики и лабораторные должны быть равны нулю');
   if(t.delivery){if(!Number.isInteger(t.delivery.inPerson)||t.delivery.inPerson<0||!Number.isInteger(t.delivery.remote)||t.delivery.remote<0||t.delivery.inPerson+t.delivery.remote!==(t.hours?.lecture||0)+(t.hours?.practice||0)+(t.hours?.lab||0))error('delivery',path,'Очная и дистанционная контактная работа должны в сумме равняться лекциям, практикам и лабораторным');}
   else if(/заочн|дистанц/i.test(s.format||''))error('delivery',path,'Для смешанной формы укажите delivery.inPerson и delivery.remote');
   moduleTotal+=n;practical+=(t.hours?.practice||0)+(t.hours?.lab||0);
  }
  if(m.totalHours!==moduleTotal)error('module_sum',`modules.${mi}`,`Сумма тем ${moduleTotal} не равна объёму модуля ${m.totalHours}`);total+=moduleTotal;
 }
 if(!Number.isInteger(s.finalHours)||s.finalHours<1||s.finalHours>s.totalHours)error('final','finalHours','Укажите часы итоговой аттестации');
 if(total+(s.finalHours||0)!==s.totalHours)error('total_sum','totalHours',`Модули ${total} + аттестация ${s.finalHours} ≠ ${s.totalHours}`);
 for(const id of ids)if(!covered.has(id))error('coverage',id,'Компетенция не раскрыта ни в одной теме');
 if(requirements.minPracticeHours&&practical<requirements.minPracticeHours)error('practice','modules','Недостаточно практических часов');
 const calendar=s.calendar;
 if(!calendar||!Number.isInteger(calendar.weeks)||calendar.weeks<1||!Array.isArray(calendar.sessions)||!calendar.sessions.length||calendar.sessions.length>1000)error('calendar','calendar','Укажите недели и занятия календарного графика');
 else{
  if(calendar.sessions.reduce((n,x)=>n+(x.hours||0),0)!==s.totalHours)error('calendar_sum','calendar','Сумма часов календарного графика не равна объёму программы');
  for(const x of calendar.sessions)if(!Number.isInteger(x.hours)||x.hours<1||!Number.isInteger(x.week)||x.week<1||x.week>calendar.weeks||!Array.isArray(x.topicIds)||x.topicIds.some(id=>!topicIds.has(id)&&id!=='final'))error('calendar_reference','calendar','Проверьте часы, недели и ссылки на темы календаря');
  const allocated=new Map();for(const x of calendar.sessions){if(x.topicIds?.length!==1)error('calendar_allocation','calendar','Каждая строка календаря относится к одной теме; разделите строку при нескольких темах');else allocated.set(x.topicIds[0],(allocated.get(x.topicIds[0])||0)+x.hours)}
  for(const t of (s.modules||[]).flatMap(m=>m.topics||[]))if(allocated.get(t.id)!==t.totalHours)error('calendar_topic','calendar','Календарные часы темы '+t.id+' не совпадают с тематическим планом');
  if(allocated.get('final')!==s.finalHours)error('calendar_final','calendar','Часы итоговой аттестации в календаре не совпадают');
  if(requirements.weeks&&calendar.weeks!==requirements.weeks)error('calendar_weeks','calendar','Число недель не совпадает с запросом');
 }
 if(s.type==='dpp')warnings.push({code:'legal_499',path:'legal',message:'В ТЗ указан приказ № 499. С 01.09.2025 его заменил приказ Минобрнауки № 266 от 24.03.2025. Нормативную базу проверяет методист.'});
 return {errors,warnings,totalHours:total+(s.finalHours||0),practicalHours:practical};
}
export function inspectModule(content,module,skeleton){
 try{return inspectModuleInternal(content,module,skeleton)}catch{return [{code:'schema',path:module.id,message:'Некорректная структура материалов модуля'}]}
}
function inspectModuleInternal(content,module,skeleton){
 const errors=[];const bad=message=>errors.push({code:'content',path:module.id,message});
 if(!content||content.moduleId!==module.id){bad('Ответ относится к другому модулю');return errors}
 const topicIds=new Set(module.topics.map(t=>t.id)),competencyIds=new Set(module.topics.flatMap(t=>t.competencyIds));
 for(const k of ['summary','methodology'])if(!text(content[k],30000))bad('Не заполнено '+k);
 for(const kind of ['questions','seminars','lectures']){
  if(!Array.isArray(content[kind])||!content[kind].length||content[kind].length>150){bad('Не заполнены '+kind);continue}
  const ids=new Set();
  for(const item of content[kind]){
   if(!text(item.id,80)||ids.has(item.id))bad('Повтор или отсутствие кода материала');ids.add(item.id);
   if(!topicIds.has(item.topicId))bad('Материал ссылается на тему вне модуля');
   if(!Array.isArray(item.competencyIds)||!item.competencyIds.length||item.competencyIds.some(id=>!competencyIds.has(id)))bad('Неверная привязка к результату обучения');
   if(kind==='questions'&&(!text(item.text,4000)||!Array.isArray(item.options)||item.options.length<2||item.options.length>6||item.options.some(x=>!text(x,2000))||!Number.isInteger(item.answer)||item.answer<0||item.answer>=item.options.length||!text(item.explanation,4000)))bad('Тест требует вариантов ответа, корректного ключа и объяснения');
   if(kind==='seminars'&&(!text(item.title,300)||!text(item.task,20000)||!text(item.deliverable,6000)||!Array.isArray(item.criteria)||item.criteria.length<2||item.criteria.some(c=>!text(c.title,1000)||!Number.isInteger(c.points)||c.points<1)||item.criteria.reduce((n,c)=>n+c.points,0)!==100))bad('Задание требует результата и критериев суммарно на 100 баллов');
   if(kind==='lectures'&&(!text(item.title,300)||!text(item.plan,20000)||!Array.isArray(item.slides)||!item.slides.length||item.slides.length>20||item.slides.some(s=>!text(s.title,180)||!text(s.text,650)||!text(s.notes,10000))))bad('Лекция требует плана и слайдов с заметками');
  }
 }
 for(const t of module.topics){if(!content.lectures?.some(x=>x.topicId===t.id))bad('Нет плана изучения темы '+t.id)}
 return errors;
}
export function inspectProgram(p){
 const report=inspectSkeleton(p.skeleton,p.requirements),s=p.skeleton;
 const coverage=(s?.competencies||[]).map(c=>({id:c.id,title:c.title,topics:(s.modules||[]).flatMap(m=>m.topics).filter(t=>t.competencyIds.includes(c.id)).map(t=>t.id),questions:[],assignments:[]}));
 for(const m of s?.modules||[]){const content=p.materials?.[m.id];if(!content){report.errors.push({code:'missing_module',path:m.id,message:'Комплект модуля ещё не подготовлен'});continue}report.errors.push(...inspectModule(content,m,s));
  for(const c of coverage){c.questions.push(...content.questions.filter(q=>q.competencyIds.includes(c.id)).map(q=>m.id+':'+q.id));c.assignments.push(...content.seminars.filter(q=>q.competencyIds.includes(c.id)).map(q=>m.id+':'+q.id))}
 }
 if(p.requirements?.testQuestionCount&&Object.values(p.materials||{}).reduce((n,m)=>n+(m.questions?.length||0),0)!==p.requirements.testQuestionCount)report.errors.push({code:'question_count',path:'materials',message:'Количество тестовых вопросов не совпадает с запросом: '+p.requirements.testQuestionCount});
 for(const c of coverage)if(c.questions.length+c.assignments.length<2||!c.questions.length||!c.assignments.length)report.errors.push({code:'assessment_coverage',path:c.id,message:'Нужны как минимум один тестовый вопрос и одно задание на каждый результат'});
 for(const title of templateSections[s?.type]||[])if(!text(p.sections?.[title],30000))report.errors.push({code:'section',path:title,message:'Не заполнен раздел шаблона'});
 const sources=(p.sources||[]).map(source=>({...source,status:source.verification?.status||'unverified'}));
 for(const source of sources)if(source.status!=='confirmed')report.warnings.push({code:'source_unverified',path:source.id,message:'Источник не подтверждён: '+source.title});
 if(!sources.length)report.warnings.push({code:'sources_missing',path:'sources',message:'Список литературы не заполнен'});
 for(const c of s?.competencies||[])if(c.standard)report.warnings.push({code:'standard_review',path:c.id,message:'Точность кода трудовой функции и актуальность профстандарта требуют проверки по первоисточнику'});
 if(!p.finalAssessment||!text(p.finalAssessment.task,20000)||!Array.isArray(p.finalAssessment.criteria)||p.finalAssessment.criteria.reduce((n,c)=>n+(c.points||0),0)!==100)report.errors.push({code:'final_assessment',path:'finalAssessment',message:'Нужны итоговое задание и критерии на 100 баллов'});
 return {...report,coverage,sources,checkedAt:new Date().toISOString(),passed:report.errors.length===0,draft:true};
}
