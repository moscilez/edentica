import {unlockedModules} from './learning-access.mjs';
import {randomBytes} from 'node:crypto';
import {lectureSlides,exportSlides,canExportPptx} from './presentations.mjs';
import {fileURLToPath} from 'node:url';
export function migrateWebsites(db){db.exec(`CREATE TABLE IF NOT EXISTS course_websites(course_id TEXT PRIMARY KEY REFERENCES courses(id),slug TEXT UNIQUE NOT NULL,color TEXT NOT NULL DEFAULT '#226454',intro TEXT NOT NULL DEFAULT '',faq TEXT NOT NULL DEFAULT '[]',template TEXT NOT NULL DEFAULT 'classic');`)}
export async function websiteRoutes(ctx){
 const {p,req,res,body,u,db,send,login,fail,required,owner,access,mods}=ctx;
 const one=(s,...v)=>db.prepare(s).get(...v),run=(s,...v)=>db.prepare(s).run(...v);
 const publicSite=p.match(/^\/api\/sites\/([a-z0-9-]+)(?:\/(theme.css))?$/);if(publicSite){const s=one('SELECT * FROM course_websites WHERE slug=?',publicSite[1]);if(!s)fail('Страница не найдена',404);const c=access(s.course_id,u);if(publicSite[2]){const rgb=[1,3,5].map(i=>parseInt(s.color.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4),luminance=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];res.writeHead(200,{'Content-Type':'text/css; charset=utf-8'});res.end(`.course-site button{background:${s.color};color:${luminance>.179?'#000000':'#ffffff'}}.course-site .eyebrow{color:${luminance<.15?s.color:'#203733'}}`);return true}send({...s,faq:JSON.parse(s.faq),course:{id:c.id,title:c.title,description:c.description,category:c.category,author:one('SELECT name FROM users WHERE id=?',c.owner).name},modules:mods(c.id).map(m=>({title:m.title}))});return true}
 const match=p.match(/^\/api\/courses\/([^/]+)\/(website|presentation)$/);if(!match)return false;const [,id,action]=match;
 if(action==='website'){login();owner(id,u);if(req.method==='GET'){const s=one('SELECT * FROM course_websites WHERE course_id=?',id);send(s?{...s,faq:JSON.parse(s.faq)}:null);return true}
  if(!/^#[0-9a-f]{6}$/i.test(body.color))fail('Цвет должен быть в формате #226454');if(!Array.isArray(body.faq)||body.faq.length>10)fail('До 10 вопросов FAQ');const faq=body.faq.map(q=>({question:required(q.question,200),answer:required(q.answer,1000)}));const intro=required(body.intro,3000);let slug=one('SELECT slug FROM course_websites WHERE course_id=?',id)?.slug||'course-'+randomBytes(6).toString('hex');run('INSERT INTO course_websites(course_id,slug,color,intro,faq,template) VALUES(?,?,?,?,?,?) ON CONFLICT(course_id) DO UPDATE SET color=excluded.color,intro=excluded.intro,faq=excluded.faq,template=excluded.template',id,slug,body.color,intro,JSON.stringify(faq),body.template==='minimal'?'minimal':'classic');send({slug});return true
 }
 if(action==='presentation'){const c=access(id,u);login();const available=unlockedModules(db,id,u.id);if(c.owner!==u.id&&!available.length)fail('Запишитесь на курс для доступа к презентации',403);const slides=lectureSlides(c,available);if(req.method==='GET'){send({slides,pptxAvailable:canExportPptx(),method:'extractive',note:'Слайды составлены из текста курса. Это автоматическое разбиение, а не дополнительная AI-генерация.'});return true}
  login();owner(id,u);if(!canExportPptx())fail('PPTX runtime не установлен. Доступны просмотр и печать презентации.',503);const result=await exportSlides(slides,fileURLToPath(new URL('../data/presentations/',import.meta.url)));res.writeHead(200,{'Content-Type':'application/vnd.openxmlformats-officedocument.presentationml.presentation','Content-Disposition':`attachment; filename="edentica-course.pptx"`});res.end(result.buffer);return true
 }
 return false;
}
