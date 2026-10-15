import {unlockedModules} from './learning-access.mjs';
import {rejectCredentials} from './secret-guard.mjs';
import {randomUUID} from 'node:crypto';
export function configureMedia(db,{env=process.env,fetchImpl=fetch}={}){
 db.exec(`CREATE TABLE IF NOT EXISTS media_jobs(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),course_id TEXT REFERENCES courses(id),module_id TEXT REFERENCES modules(id) ON DELETE SET NULL,kind TEXT NOT NULL,request_key TEXT NOT NULL,script TEXT NOT NULL,state TEXT NOT NULL,estimate REAL NOT NULL,provider_id TEXT,output_url TEXT,audio BLOB,error TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(user_id,request_key));`);
 db.prepare("UPDATE media_jobs SET state='error',error='Сервер перезапущен. Не повторяйте операцию до проверки списаний у провайдера.' WHERE state IN ('queued','processing')").run();
 const controllers=new Map();let busy=false,closed=false;
 const budgetReady=()=>Number(env.AI_DAILY_BUDGET_USD)>0&&Number(env.AI_GLOBAL_DAILY_BUDGET_USD)>0;
 const ttsReady=()=>!!(budgetReady()&&env.OPENAI_API_KEY&&['tts-1','tts-1-hd'].includes(env.TTS_MODEL)&&env.TTS_VOICE&&Number(env.TTS_USD_PER_MILLION_CHARACTERS)>0);
 const videoReady=()=>!!(budgetReady()&&env.HEYGEN_API_KEY&&env.HEYGEN_STOCK_AVATAR_ID&&env.HEYGEN_STOCK_VOICE_ID&&env.HEYGEN_STOCK_RIGHTS_CONFIRMED==='1'&&Number(env.VIDEO_USD_PER_MINUTE)>0);
 const safe=j=>{if(!j)return null;const {audio,script,request_key,user_id,...rest}=j;return rest};
 async function pump(){if(busy||closed)return;busy=true;try{while(!closed){const j=db.prepare("SELECT * FROM media_jobs WHERE state='queued' ORDER BY created LIMIT 1").get();if(!j)break;const controller=new AbortController();controllers.set(j.id,controller);const timer=setTimeout(()=>controller.abort(),120000);db.prepare("UPDATE media_jobs SET state='processing' WHERE id=?").run(j.id);
  try{
   if(j.kind==='speech'){
    const r=await fetchImpl('https://api.openai.com/v1/audio/speech',{method:'POST',headers:{Authorization:'Bearer '+env.OPENAI_API_KEY,'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({model:env.TTS_MODEL,voice:env.TTS_VOICE,input:j.script,response_format:'mp3'})});
    if(!r.ok)throw Error('Провайдер речи: HTTP '+r.status);const bytes=Buffer.from(await r.arrayBuffer());if(bytes.length>10000000)throw Error('Аудиофайл превышает лимит');
    db.prepare("UPDATE media_jobs SET state='ready',audio=? WHERE id=? AND state='processing'").run(bytes,j.id);
   }else{
    const r=await fetchImpl('https://api.heygen.com/v2/video/generate',{method:'POST',headers:{'X-Api-Key':env.HEYGEN_API_KEY,'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({video_inputs:[{character:{type:'avatar',avatar_id:env.HEYGEN_STOCK_AVATAR_ID,avatar_style:'normal'},voice:{type:'text',input_text:j.script,voice_id:env.HEYGEN_STOCK_VOICE_ID}}],dimension:{width:1280,height:720},caption:true,title:'Edentica AI lecture'})});
    if(!r.ok)throw Error('Видеопровайдер: HTTP '+r.status);const data=await r.json();if(!data.data?.video_id)throw Error('Провайдер не вернул ID видео');db.prepare("UPDATE media_jobs SET state='provider_processing',provider_id=? WHERE id=? AND state='processing'").run(data.data.video_id,j.id);
   }
  }catch(e){db.prepare("UPDATE media_jobs SET state='error',error=? WHERE id=? AND state='processing'").run(e.name==='AbortError'?'Истекло время ожидания. Проверьте расходы провайдера.':e.message,j.id)}finally{clearTimeout(timer);controllers.delete(j.id)}
 }}finally{busy=false}}
 async function refresh(j){if(j.state!=='provider_processing'||!j.provider_id)return j;
  const r=await fetchImpl('https://api.heygen.com/v1/video_status.get?video_id='+encodeURIComponent(j.provider_id),{headers:{'X-Api-Key':env.HEYGEN_API_KEY},signal:AbortSignal.timeout(15000)});if(!r.ok)return j;const data=(await r.json()).data;
  if(data?.status==='completed'){let url;try{url=new URL(data.video_url);if(url.protocol!=='https:')throw Error()}catch{throw Error('Некорректный адрес готового видео')};db.prepare("UPDATE media_jobs SET state='ready',output_url=? WHERE id=? AND state='provider_processing'").run(url.href,j.id)}else if(data?.status==='failed')db.prepare("UPDATE media_jobs SET state='error',error='Провайдер не завершил видео' WHERE id=? AND state='provider_processing'").run(j.id);
  return db.prepare('SELECT * FROM media_jobs WHERE id=?').get(j.id)
 }
 return {close(){closed=true;for(const c of controllers.values())c.abort()},async routes({p,req,res,body,u,send,login,fail,required,owner,access,mods}){
  if(p==='/api/media/status'){send({speech:ttsReady(),video:videoReady(),speechRate:Number(env.TTS_USD_PER_MILLION_CHARACTERS)||null,videoRate:Number(env.VIDEO_USD_PER_MINUTE)||null,providers:{speech:'OpenAI',video:'HeyGen'},identity:'Только разрешённые библиотечные аватары и стандартные голоса. Клонирование личности не включено.'});return true}
  const match=p.match(/^\/api\/courses\/([^/]+)\/media$/);
  if(match){login();const id=match[1];access(id,u);if(req.method==='GET'){const isOwner=db.prepare('SELECT owner FROM courses WHERE id=?').get(id).owner===u.id;const available=new Set(unlockedModules(db,id,u.id).map(m=>m.id));send(db.prepare('SELECT * FROM media_jobs WHERE course_id=? ORDER BY created DESC').all(id).filter(j=>isOwner||j.state==='ready'&&available.has(j.module_id)).map(safe));return true}
   owner(id,u);const kind=body.kind;if(kind!=='speech'&&kind!=='video')fail('Неизвестный вид генерации');if(kind==='speech'?!ttsReady():!videoReady())fail('Настройте провайдера, тарифы, права и бюджет media-генерации',503);
   const key=required(body.requestKey,100);const existing=db.prepare('SELECT * FROM media_jobs WHERE user_id=? AND request_key=?').get(u.id,key);if(existing){send(safe(existing));return true}
   const module=mods(id).find(m=>m.id===body.moduleId);if(!module)fail('Модуль не найден',404);const script=required(body.script,3000);rejectCredentials(script);if(body.confirmCost!==true||body.confirmTransfer!==true)fail('Подтвердите расходы и передачу сценария выбранному провайдеру');
   const estimate=kind==='speech'?script.length*Number(env.TTS_USD_PER_MILLION_CHARACTERS)/1000000:Math.ceil(script.length/300)*Number(env.VIDEO_USD_PER_MINUTE);
   const spent=['media_jobs','generation_jobs','assistant_requests'].reduce((n,t)=>n+db.prepare(`SELECT coalesce(sum(estimate),0) total FROM ${t} WHERE user_id=? AND date(created)=date('now')`).get(u.id).total,0);
   const global=['media_jobs','generation_jobs','assistant_requests'].reduce((n,t)=>n+db.prepare(`SELECT coalesce(sum(estimate),0) total FROM ${t} WHERE date(created)=date('now')`).get().total,0);
   if(spent+estimate>Number(env.AI_DAILY_BUDGET_USD)||global+estimate>Number(env.AI_GLOBAL_DAILY_BUDGET_USD))fail('Дневной бюджет исчерпан',429);
   if(db.prepare("SELECT 1 FROM media_jobs WHERE user_id=? AND state IN ('queued','processing','provider_processing')").get(u.id))fail('Дождитесь текущей media-генерации',409);
   const jid=randomUUID();db.prepare("INSERT INTO media_jobs(id,user_id,course_id,module_id,kind,request_key,script,state,estimate) VALUES(?,?,?,?,?,?,?,'queued',?)").run(jid,u.id,id,module.id,kind,key,script,estimate);send(safe(db.prepare('SELECT * FROM media_jobs WHERE id=?').get(jid)),202);setImmediate(()=>pump());return true
  }
  const job=p.match(/^\/api\/media\/([^/]+)(?:\/(audio|cancel))?$/);if(!job)return false;login();let j=db.prepare('SELECT * FROM media_jobs WHERE id=?').get(job[1]);if(!j)fail('Не найдено',404);access(j.course_id,u);
  if(job[2]==='audio'){if(db.prepare('SELECT owner FROM courses WHERE id=?').get(j.course_id).owner!==u.id&&!unlockedModules(db,j.course_id,u.id).some(m=>m.id===j.module_id))fail('Модуль ещё не открыт',403);if(j.state!=='ready'||j.kind!=='speech')fail('Аудио ещё не готово',404);res.writeHead(200,{'Content-Type':'audio/mpeg','Content-Length':j.audio.length});res.end(j.audio);return true}
  if(j.user_id!==u.id)fail('Нет доступа',403);
  if(job[2]==='cancel'){db.prepare("UPDATE media_jobs SET state='cancelled' WHERE id=? AND state IN ('queued','processing','provider_processing')").run(j.id);controllers.get(j.id)?.abort();send({ok:true,warning:'Отмена скрывает результат. Уже запущенная операция у провайдера может продолжиться и быть оплачена.'});return true}
  j=await refresh(j);send(safe(j));return true
 }};
}
