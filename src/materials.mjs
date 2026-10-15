import {randomUUID} from 'node:crypto';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
const runtime=join(process.env.USERPROFILE||'','.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe');
let imports=0;
function extract(bytes,type){return new Promise((resolve,reject)=>{
 const p=spawn(process.env.PYTHON_PATH||(existsSync(runtime)?runtime:process.platform==='win32'?'python':'python3'),[fileURLToPath(new URL('../scripts/extract-material.py',import.meta.url)),type],{windowsHide:true,stdio:['pipe','pipe','pipe']});
 const chunks=[];let size=0;const timer=setTimeout(()=>{p.kill();reject(Error('Время обработки файла истекло'))},20000);p.stderr.resume();p.stdout.on('data',b=>{size+=b.length;if(size>300000){p.kill();reject(Error('Слишком большой результат извлечения'))}else chunks.push(b)});p.on('error',e=>{clearTimeout(timer);reject(e)});p.on('close',code=>{clearTimeout(timer);if(code!==0){reject(Error('Не удалось прочитать файл. Проверьте формат, шифрование и наличие текста.'));return}try{resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')))}catch{reject(Error('Ошибка извлечения текста'))}});p.stdin.on('error',()=>{});p.stdin.end(bytes);
})}
export function migrateMaterials(db){db.exec(`CREATE TABLE IF NOT EXISTS learning_materials(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),name TEXT NOT NULL,kind TEXT NOT NULL,size INTEGER NOT NULL,text TEXT NOT NULL,truncated INTEGER NOT NULL DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP);`)}
export async function materialRoutes({p,req,body,u,db,send,login,required,fail}){
 if(p==='/api/materials'){login();if(req.method==='GET'){send(db.prepare('SELECT id,name,kind,size,truncated,created FROM learning_materials WHERE user_id=? ORDER BY created DESC').all(u.id));return true}
  if(imports>=2)fail('Сейчас обрабатываются другие файлы. Повторите позже.',429);if(db.prepare('SELECT count(*) n FROM learning_materials WHERE user_id=?').get(u.id).n>=30)fail('Лимит библиотеки: 30 материалов');const name=required(body.name,200),kind=name.split('.').at(-1).toLowerCase();if(!['pdf','docx','pptx','txt'].includes(kind))fail('Поддерживаются PDF, DOCX, PPTX и UTF-8 TXT');if(typeof body.data!=='string'||!body.data||!/^[A-Za-z0-9+/]*={0,2}$/.test(body.data))fail('Некорректный файл');const bytes=Buffer.from(body.data,'base64');if(bytes.length>5000000)fail('Файл до 5 МБ');imports++;let content;try{content=await extract(bytes,kind)}catch(e){fail(e.message,400)}finally{imports--}const id=randomUUID();db.prepare('INSERT INTO learning_materials(id,user_id,name,kind,size,text,truncated) VALUES(?,?,?,?,?,?,?)').run(id,u.id,name,kind,bytes.length,content.text,+content.truncated);send({id,text:content.text,truncated:content.truncated},201);return true
 }
 const route=p.match(/^\/api\/materials\/([^/]+)(?:\/(remove))?$/);if(!route)return false;login();const material=db.prepare('SELECT * FROM learning_materials WHERE id=? AND user_id=?').get(route[1],u.id);if(!material)fail('Материал не найден',404);
 if(route[2]){if(body.confirm!==true)fail('Подтвердите удаление материала');db.prepare('DELETE FROM learning_materials WHERE id=? AND user_id=?').run(material.id,u.id);send({ok:true})}else send(material);return true;
}
