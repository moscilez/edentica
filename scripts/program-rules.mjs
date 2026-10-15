// Pure, previously tested rules reused by the Python API. No database or network.
import {createInterface} from 'node:readline';
import {digest,inspectSkeleton,inspectModule,inspectProgram,templateSections} from '../src/programs/validation.mjs';
import {demonstration} from '../src/programs/demo.mjs';
import {skills} from '../src/programs/skills.mjs';
const operations={digest,inspectSkeleton,inspectModule,inspectProgram,demonstration,
 config:()=>({skills,templateSections})};
for await(const line of createInterface({input:process.stdin})){
 try{const {operation,args=[]}=JSON.parse(line);if(!Object.hasOwn(operations,operation))throw Error('Unknown rule');console.log(JSON.stringify({value:operations[operation](...args)}))}
 catch(e){console.log(JSON.stringify({error:e.message}))}
}
