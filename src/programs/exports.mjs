import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {exportSlides,canExportPptx} from '../presentations.mjs';
export {canExportPptx};
export function gift(p){
 const escape=s=>String(s).replace(/[\\~=#{}:]/g,'\\$&').replace(/\r?\n/g,' ');
 return Object.values(p.materials||{}).flatMap(m=>m.questions.map(q=>`// ${q.competencyIds.join(', ')}; тема ${q.topicId}\n::${escape(m.moduleId+' '+q.id)}::${escape(q.text)} {\n${q.options.map((x,i)=>(i===q.answer?'=':'~')+escape(x)).join('\n')}\n#### ${escape(q.explanation)}\n}`)).join('\n\n');
}
export async function programPptx(p,moduleId,outputDir){
 if(!canExportPptx())throw Object.assign(Error('PPTX требует установленный @oai/artifact-tool. Настройте ARTIFACT_NODE_MODULES в среде развёртывания.'),{status:503});
 const modules=moduleId?[p.materials[moduleId]]:Object.values(p.materials||{});
 if(modules.some(m=>!m))throw Object.assign(Error('Материалы модуля ещё не готовы'),{status:409});
 const slides=modules.flatMap(m=>m.lectures.flatMap(l=>l.slides));
 if(!slides.length||slides.length>300)throw Object.assign(Error('Выгружайте отдельный модуль: допустимо 1–300 слайдов'),{status:422});
 return (await exportSlides([{title:p.skeleton.title,text:'Черновик для экспертной проверки. '+p.skeleton.audience,notes:'Содержание требует утверждения человеком.'},...slides],outputDir)).buffer;
}
export function programDocx(p){return new Promise((resolve,reject)=>{
 const runtime=join(process.env.USERPROFILE||'','.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe');
 const child=spawn(process.env.PYTHON_PATH||(existsSync(runtime)?runtime:process.platform==='win32'?'python':'python3'),[fileURLToPath(new URL('../../scripts/export-program.py',import.meta.url))],{windowsHide:true,stdio:['pipe','pipe','pipe']});
 const chunks=[];let size=0;const timer=setTimeout(()=>{child.kill();reject(Error('Истекло время экспорта DOCX'))},60000);
 child.stdout.on('data',chunk=>{size+=chunk.length;if(size>20000000){child.kill();reject(Error('Слишком большой документ'))}else chunks.push(chunk)});child.stderr.resume();child.stdin.on('error',()=>{});
 child.on('error',e=>{clearTimeout(timer);reject(e)});child.on('close',code=>{clearTimeout(timer);if(code!==0)reject(Error('Не удалось собрать DOCX. Проверьте Python и python-docx.'));else resolve(Buffer.concat(chunks))});child.stdin.end(JSON.stringify(p));
})}
