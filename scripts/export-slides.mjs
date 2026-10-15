import {programPptx} from '../src/programs/exports.mjs';
import {join} from 'node:path';
const chunks=[];for await(const chunk of process.stdin)chunks.push(chunk);
const {program,moduleId}=JSON.parse(Buffer.concat(chunks));
const bytes=await programPptx(program,moduleId,join(process.cwd(),'output/programs',program.id));
process.stdout.write(bytes);
