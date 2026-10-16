import {readdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
const files=[];
function scan(directory){for(const entry of readdirSync(directory,{withFileTypes:true})){const path=join(directory,entry.name);if(entry.isDirectory())scan(path);else if(/\.(mjs|js)$/.test(path))files.push(path)}}
for(const directory of ['src','public','scripts','tests'])scan(directory);files.push('server.mjs');
for(const file of files){const r=spawnSync(process.execPath,['--check',resolve(file)],{stdio:'inherit',windowsHide:true});if(r.status!==0)process.exit(r.status||1)}
console.log('JavaScript syntax checked: '+files.length+' files');
const r=spawnSync(process.execPath,['scripts/python.mjs','-m','pytest','-q','tests_python'],{stdio:'inherit',windowsHide:true});process.exitCode=r.status??1;
