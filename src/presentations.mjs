import {createRequire} from 'node:module';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {mkdir,readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {existsSync} from 'node:fs';
const runtime=join(process.env.USERPROFILE||'', '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
export function canExportPptx(){return existsSync(join(process.env.ARTIFACT_NODE_MODULES||runtime,'@oai/artifact-tool/package.json'))}
export function lectureSlides(course,modules){
 const slides=[{title:course.title,text:course.description.slice(0,650),notes:course.description}];
 for(const m of modules){
  const paragraphs=m.content.split(/\n\s*\n/).filter(s=>s.trim());
  for(let i=0;i<paragraphs.length;i++){
   const paragraph=paragraphs[i];const sentences=paragraph.match(/[^.!?]+[.!?]+|[^.!?]+$/g)||[paragraph];let chunk='';
   for(const sentence of sentences){if(chunk.length+sentence.length>650&&chunk){slides.push({title:m.title,text:chunk.trim(),notes:paragraph});chunk=''}if(sentence.length>650){for(let j=0;j<sentence.length;j+=650)slides.push({title:m.title,text:sentence.slice(j,j+650),notes:paragraph})}else chunk+=sentence}
   if(chunk.trim())slides.push({title:m.title,text:chunk.trim(),notes:paragraph});
  }
 }
 if(slides.length>100)throw Object.assign(Error('Курс содержит более 100 слайдов. Сократите материалы или разделите курс.'),{status:400});
 return slides;
}
export async function exportSlides(slides,outputDir,{render=false}={}){
 const require=createRequire(join(process.env.ARTIFACT_NODE_MODULES||runtime,'package.json'));
 const {Presentation,PresentationFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
 const deck=Presentation.create({slideSize:{width:1280,height:720}});
 for(const s of slides){const slide=deck.slides.add();slide.background.fill='#F4F7F5';
  if(s.notes)slide.speakerNotes.text=s.notes;
  const title=slide.shapes.add({geometry:'textbox',position:{left:70,top:70,width:1140,height:140},fill:'none',line:{fill:'none',width:0}});title.text=s.title;title.text.style={typeface:'Arial',fontSize:s.title.length>100?32:44,bold:true,color:'#203733'};
  const body=slide.shapes.add({geometry:'textbox',position:{left:70,top:230,width:1140,height:410},fill:'none',line:{fill:'none',width:0}});body.text=s.text;body.text.style={typeface:'Arial',fontSize:28,color:'#36594B'};
 }
 await mkdir(outputDir,{recursive:true});const id=randomUUID(),path=join(outputDir,id+'.pptx');await(await PresentationFile.exportPptx(deck)).save(path);
 if(render){for(const [i,slide]of deck.slides.items.entries()){const png=await deck.export({slide,format:'png',scale:.65});const {writeFile}=await import('node:fs/promises');await writeFile(join(outputDir,`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()))}}
 return {path,buffer:await readFile(path),slides:slides.length};
}
