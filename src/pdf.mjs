import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
const bundled=join(process.env.USERPROFILE||'', '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe');
export function certificatePDF(data){
 return new Promise((resolve,reject)=>{
  const python=process.env.PYTHON_PATH||(existsSync(bundled)?bundled:process.platform==='win32'?'python':'python3');
  const p=spawn(python,[fileURLToPath(new URL('../scripts/certificate.py',import.meta.url))],{stdio:['pipe','pipe','pipe'],windowsHide:true});
  const chunks=[];let bytes=0;const timer=setTimeout(()=>{p.kill();reject(Error('PDF generation timed out'))},15000);
  p.stdout.on('data',b=>{bytes+=b.length;if(bytes>5000000){p.kill();reject(Error('PDF too large'))}else chunks.push(b)});
  p.stderr.resume();p.on('error',e=>{clearTimeout(timer);reject(e)});p.on('close',code=>{clearTimeout(timer);code===0?resolve(Buffer.concat(chunks)):reject(Error('PDF runtime unavailable'))});
  p.stdin.on('error',()=>{});p.stdin.end(JSON.stringify(data));
 });
}
