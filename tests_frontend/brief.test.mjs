import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the shipped handlers, including the browser clearing currentTarget
// as soon as an async listener returns its first promise. No LLM calls.
const source=fs.readFileSync(new URL('../public/program-studio.js',import.meta.url),'utf8');
const handlers=source.slice(source.indexOf('async function newProgram('),source.indexOf('function skillPage('));
async function setup({similar=[],references=[]}={}){
 const form={dataset:{},values:{request:'Курс Python на 16 часов',visibility:'private'}};
 const button={disabled:false},input={disabled:false,dataset:{},value:'file.txt',files:[]};
 let checked=references.map(x=>x.id),rows=references.map(x=>({...x})),html='';
 const refs={querySelectorAll:()=>checked.map(value=>({value})),get innerHTML(){return html},set innerHTML(value){html=value;checked=[...value.matchAll(/value="([^"]+)" checked/g)].map(m=>m[1])}};
 const elements={'#brief':form,'#brief-submit':button,'#reference-file':input,'#references':refs};
 const errors=[],created=[],navigation=[],removed=[],searches=[];
 const context=vm.createContext({app:{innerHTML:''},viewVersion:0,user:{id:'test'},status:{configured:false},examples:[],
  document:{querySelector:selector=>elements[selector]},esc:String,breadcrumb(){},bind(){},requireUser:()=>true,
  toast:message=>errors.push(message),window:{confirm:()=>true},navigate:hash=>navigation.push(hash),
  FormData:class{constructor(element){this.values=element.values}get(name){return this.values[name]}},
  FileReader:class{readAsDataURL(){this.result='data:text/plain;base64,dGV4dA==';queueMicrotask(()=>this.onload())}},
  workspace:{similar:async query=>{searches.push(query);return similar}},
  request:async(path,body)=>{
   if(path==='/materials'&&body){const value={id:'new',name:body.name};rows.push(value);return{json:async()=>value}}
   if(path==='/materials')return{json:async()=>rows};
   if(path.endsWith('/remove')){removed.push(path);rows=rows.filter(x=>path!=='/materials/'+x.id+'/remove');return{}}
   throw Error('Unexpected request '+path);
  },agent:async(action,payload)=>{assert.equal(action,'create');created.push(payload);return{id:'created'}},
 });
 vm.runInContext(handlers,context);await vm.runInContext('newProgram()',context);
 const dispatch=async(target,handler,extra={})=>{const event={currentTarget:target,target,preventDefault(){},...extra};const pending=handler(event);event.currentTarget=null;await pending};
 return{form,button,input,refs,errors,created,navigation,removed,searches,submit:()=>dispatch(form,form.onsubmit),
  upload:()=>dispatch(input,input.onchange),remove:id=>dispatch(refs,refs.onclick,{target:{closest:()=>({dataset:{removeReference:id},disabled:false})}})};
}
test('create survives asynchronous similarity search clearing event.currentTarget',async()=>{
 const ui=await setup();await ui.submit();
 assert.deepEqual(ui.errors,[]);assert.equal(ui.created.length,1);
 assert.equal(ui.created[0].request,ui.form.values.request);assert.equal(ui.navigation[0],'#program/created');assert.equal(ui.button.disabled,false);
});
test('similar courses require an explicit second submission and preserve the query',async()=>{
 const ui=await setup({similar:[{id:'similar'}]});await ui.submit();
 assert.equal(ui.created.length,0);assert.equal(ui.form.dataset.checkedQuery,ui.form.values.request);
 await ui.submit();assert.equal(ui.created.length,1);assert.equal(ui.searches.length,1);assert.deepEqual(ui.errors,[]);
});
test('upload preserves previous selections; delete and replace exclude the wrong file',async()=>{
 const ui=await setup({references:[{id:'keep',name:'Keep.txt'}]});
 ui.input.files=[{name:'Wrong.txt',size:10}];await ui.upload();
 assert.match(ui.refs.innerHTML,/value="keep" checked/);assert.match(ui.refs.innerHTML,/value="new" checked/);
 await ui.remove('new');assert.equal(ui.removed.length,1);assert.doesNotMatch(ui.refs.innerHTML,/Wrong.txt/);
 ui.input.files=[{name:'Correct.txt',size:10}];await ui.upload();await ui.submit();
 assert.match(ui.refs.innerHTML,/Correct.txt/);assert.deepEqual(Array.from(ui.created[0].referenceIds),['keep','new']);assert.equal(ui.input.value,'');
});
test('submission waits for an uploading file instead of silently dropping it',async()=>{
 const ui=await setup();ui.input.files=[{name:'Reference.txt',size:10}];
 const uploading=ui.upload();await ui.submit();await uploading;
 assert.equal(ui.created.length,0);assert.match(ui.errors[0],/Дождитесь/);
 await ui.submit();assert.deepEqual(Array.from(ui.created[0].referenceIds),['new']);
});
