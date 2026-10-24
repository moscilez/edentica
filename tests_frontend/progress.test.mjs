import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../public/program-studio.js',import.meta.url),'utf8');
const context=vm.createContext({});
vm.runInContext(source.slice(source.indexOf('function projectStep('),source.indexOf('function renderProject(')),context);
const step=p=>context.projectStep(p);
test('ready and published-ready materials complete all four steps',()=>{
 assert.equal(step({state:'draft_ready',approval:{},report:{passed:true},materials:{M1:{}}}),4);
 assert.equal(step({state:'approved',approval:{},report:{passed:true},materials:{M1:{}}}),4);
 assert.equal(step({state:'approved',approval:{},materials:{}}),3);
 assert.equal(step({state:'skeleton_review',skeleton:{},materials:{}}),2);
 assert.equal(step({state:'needs_revision',approval:{},materials:{M1:{}}}),3);
 assert.equal(step({state:'draft_ready',approval:{},report:{passed:false},materials:{M1:{}}}),3);
 assert.equal(step({job:{state:'running',kind:'generate'},approval:{}}),3);
});
