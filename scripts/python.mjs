import {existsSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {join} from 'node:path';
const candidate=join(process.cwd(),'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python=process.env.PYTHON_PATH||(existsSync(candidate)?candidate:process.platform==='win32'?'python':'python3');
const child=spawn(python,process.argv.slice(2),{stdio:'inherit',windowsHide:true});
child.on('error',()=>{console.error('Создайте .venv и установите requirements.txt');process.exitCode=1});
child.on('exit',code=>{process.exitCode=code??1});
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>child.kill(signal));
