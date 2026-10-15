import {awardLearningXP} from './reputation.mjs';
import {randomUUID} from 'node:crypto';
const manualTypes=new Set(['essay','practical','case']);
const types=new Set(['single','multiple','truefalse','matching','ordering','short',...manualTypes]);
const fail=message=>{throw Object.assign(Error(message),{status:400})};
const text=(v,max)=>{if(typeof v!=='string'||!v.trim()||v.length>max||/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v))fail('Проверьте текст задания');return v.trim()};
const indices=(v,n,permutation=false)=>Array.isArray(v)&&v.length>0&&v.every(i=>Number.isInteger(i)&&i>=0&&i<n)&&new Set(v).size===v.length&&(!permutation||v.length===n);
export function normalizeQuestions(questions){
 if(!Array.isArray(questions)||!questions.length||questions.length>30)fail('В тесте должно быть от 1 до 30 вопросов');
 return questions.map(q=>{const type=q.type||'single';if(!types.has(type))fail('Неизвестный тип вопроса');const points=q.points??1;if(!Number.isInteger(points)||points<1||points>10)fail('Баллы за вопрос: от 1 до 10');const result={type,text:text(q.text,1000),points};
  if(type==='short'||manualTypes.has(type)){result.options=[];result.answer=text(q.answer,3000);return result}
  if(!Array.isArray(q.options)||q.options.length<2||q.options.length>6)fail('От 2 до 6 вариантов ответа');result.options=q.options.map(o=>text(o,500));
  if(type==='single'||type==='truefalse'){if(!Number.isInteger(q.answer)||q.answer<0||q.answer>=q.options.length)fail('Выберите правильный ответ');if(type==='truefalse'&&q.options.length!==2)fail('Для верно/неверно нужно два варианта')}
  else if(!indices(q.answer,q.options.length,type==='ordering'||type==='matching'))fail('Проверьте правильные ответы или последовательность');
  if(type==='matching'){if(!Array.isArray(q.prompts)||q.prompts.length!==q.options.length)fail('Число понятий и определений должно совпадать');result.prompts=q.prompts.map(p=>text(p,500))}
  result.answer=q.answer;return result;
 });
}
export function gradeAssessment(questions,answers){
 if(!Array.isArray(answers)||answers.length!==questions.length)fail('Ответьте на все вопросы');let earned=0,total=0,manualMax=0;const normalized=normalizeQuestions(questions);
 normalized.forEach((q,i)=>{const value=answers[i];total+=q.points;if(manualTypes.has(q.type)){text(value,10000);manualMax+=q.points;return}
  let correct=false;
  if(q.type==='short'){correct=text(value,3000).normalize('NFKC').toLowerCase().replace(/\s+/g,' ')===q.answer.normalize('NFKC').toLowerCase().replace(/\s+/g,' ')}
  else if(q.type==='single'||q.type==='truefalse'){if(!Number.isInteger(value)||value<0||value>=q.options.length)fail('Выберите ответ');correct=value===q.answer}
  else{if(!indices(value,q.options.length,q.type==='ordering'||q.type==='matching'))fail('Ответы должны быть заполнены без повторений');correct=q.type==='multiple'?value.length===q.answer.length&&value.every(v=>q.answer.includes(v)):value.every((v,j)=>q.answer[j]===v)}
  if(correct)earned+=q.points;
 });
 return {score:Math.round(100*earned/total),pending:manualMax>0,earned,total,manualMax,questions:normalized};
}
export function migrateAssessments(db){db.exec(`CREATE TABLE IF NOT EXISTS manual_assessments(attempt_id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),course_id TEXT REFERENCES courses(id),module_id TEXT REFERENCES modules(id),kind TEXT NOT NULL,questions TEXT NOT NULL,answers TEXT NOT NULL,earned INTEGER NOT NULL,total INTEGER NOT NULL,manual_max INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'pending',feedback TEXT NOT NULL DEFAULT '',created TEXT DEFAULT CURRENT_TIMESTAMP);`)}
export function queueReview(db,{attemptId,userId,courseId,moduleId=null,kind,graded,answers}){
 if(!graded.pending)return;
 db.prepare('INSERT INTO manual_assessments(attempt_id,user_id,course_id,module_id,kind,questions,answers,earned,total,manual_max) VALUES(?,?,?,?,?,?,?,?,?,?)').run(attemptId,userId,courseId,moduleId,kind,JSON.stringify(graded.questions),JSON.stringify(answers),graded.earned,graded.total,graded.manualMax);
}
export function reviewRoutes({p,req,body,u,db,login,owner,send,fail,required}){
 const list=p.match(/^\/api\/courses\/([^/]+)\/grading$/);
 if(list){login();owner(list[1],u);send(db.prepare("SELECT a.*,u.name FROM manual_assessments a JOIN users u ON u.id=a.user_id WHERE a.course_id=? AND a.state='pending' ORDER BY a.created").all(list[1]).map(a=>({...a,questions:JSON.parse(a.questions),answers:JSON.parse(a.answers)})));return true}
 const review=p.match(/^\/api\/grading\/([^/]+)$/);if(!review)return false;login();const a=db.prepare('SELECT * FROM manual_assessments WHERE attempt_id=?').get(review[1]);if(!a)fail('Работа не найдена',404);owner(a.course_id,u);if(a.state!=='pending')fail('Работа уже проверена',409);if(!Number.isInteger(body.points)||body.points<0||body.points>a.manual_max)fail('Проверьте выставленные баллы');const feedback=required(body.feedback,3000);
 const threshold=a.kind==='module'?db.prepare('SELECT threshold FROM modules WHERE id=?').get(a.module_id).threshold:db.prepare('SELECT threshold FROM final_exams WHERE course_id=?').get(a.course_id).threshold;
 const score=Math.round(100*(a.earned+body.points)/a.total),passed=score>=threshold;
 db.exec('BEGIN');try{
  db.prepare("UPDATE manual_assessments SET state='reviewed',feedback=? WHERE attempt_id=?").run(feedback,a.attempt_id);
  db.prepare(`UPDATE ${a.kind==='module'?'attempts':'final_attempts'} SET score=?,passed=? WHERE id=?`).run(score,+passed,a.attempt_id);
  if(passed){if(a.kind==='module')db.prepare('INSERT INTO progress VALUES(?,?,?) ON CONFLICT(user_id,module_id) DO UPDATE SET score=max(score,excluded.score)').run(a.user_id,a.module_id,score);awardLearningXP(db,a.user_id,a.course_id,a.kind,a.module_id)}
  db.prepare('INSERT INTO notifications(id,user_id,text) VALUES(?,?,?)').run(randomUUID(),a.user_id,'Работа проверена: '+score+'%. '+feedback);db.prepare('INSERT INTO audit_logs(id,user_id,action,target) VALUES(?,?,?,?)').run(randomUUID(),u.id,'assessment.review',a.attempt_id);
  db.exec('COMMIT');
 }catch(e){db.exec('ROLLBACK');throw e}send({score,passed});return true;
}
