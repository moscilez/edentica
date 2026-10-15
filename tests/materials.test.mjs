import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../server.mjs';
import {execFileSync} from 'node:child_process';
import {readFileSync,existsSync} from 'node:fs';
import {join} from 'node:path';
test('Private material import preserves Cyrillic; unsafe formats and cross-user reads rejected',async()=>{
 const {server,db}=createApp(':memory:');await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;
 const call=async(p,b,cookie='')=>{const r=await fetch(base+'/api'+p,{method:b?'POST':'GET',headers:{Cookie:cookie,'X-Edentica':'1','Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return {status:r.status,data:await r.json(),cookie:r.headers.get('set-cookie')?.split(';')[0]}};
 try{const author=(await call('/auth/register',{name:'Author',email:'source@test.local',password:'long-password'})).cookie;const other=(await call('/auth/register',{name:'Other',email:'other@test.local',password:'long-password'})).cookie;
  const text='Проверяем первоисточник и контекст.';const material=await call('/materials',{name:'источник.txt',data:Buffer.from(text,'utf8').toString('base64')},author);assert.equal(material.status,201);assert.equal(material.data.text,text);
  assert.equal((await call('/materials/'+material.data.id,undefined,other)).status,404);
  assert.equal((await call('/materials',{name:'program.exe',data:'QUJD'},author)).status,400);
  assert.equal((await call('/materials',{name:'fake.pdf',data:Buffer.from('not pdf').toString('base64')},author)).status,400);
  const bundled=join(process.env.USERPROFILE||'','.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe');
  const python=process.env.PYTHON_PATH||(existsSync(bundled)?bundled:process.platform==='win32'?'python':'python3');
  const fixtures=JSON.parse(execFileSync(python,['-c',`import io,json,base64
from docx import Document
from reportlab.pdfgen import canvas
doc=Document();doc.add_paragraph('Source document for import validation.');word=io.BytesIO();doc.save(word)
pdf=io.BytesIO();c=canvas.Canvas(pdf);c.drawString(72,720,'Source document for import validation.');c.save()
print(json.dumps({'docx':base64.b64encode(word.getvalue()).decode(),'pdf':base64.b64encode(pdf.getvalue()).decode()}))`],{encoding:'utf8',windowsHide:true}));
  for(const [kind,data]of Object.entries(fixtures)){const r=await call('/materials',{name:'source.'+kind,data},author);assert.equal(r.status,201);assert.match(r.data.text,/Source document/)}
  const deck=readFileSync(new URL('./fixtures/source.pptx',import.meta.url));const imported=await call('/materials',{name:'source.pptx',data:deck.toString('base64')},author);assert.equal(imported.status,201);assert.match(imported.data.text,/Критическое мышление/);
  assert.equal((await call('/materials/'+material.data.id+'/remove',{confirm:false},author)).status,400);
  assert.equal((await call('/materials/'+material.data.id+'/remove',{confirm:true},author)).status,200);
 }finally{await new Promise(r=>server.close(r));db.close()}
});
