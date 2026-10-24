import test from 'node:test';
import assert from 'node:assert/strict';
import {contentBlocks,renderLearning,renderSlide} from '../public/learning-content.js';
test('learning content renders structure without executing model HTML',()=>{
 const text='## Понятие\n\n<script>alert(1)</script>\n\n- Первый\n- Второй\n\n```js\n  value < 3\n```';
 const html=renderLearning(text);
 assert.match(html,/<h3>Понятие<\/h3>/);assert.match(html,/<ul>/);assert.match(html,/<pre><code>  value &lt; 3/);
 assert.ok(!html.includes('<script>'));assert.match(html,/&lt;script&gt;/);
 assert.ok(contentBlocks(('Предложение с пояснением. ').repeat(80)).length>1);
 assert.match(renderSlide({title:'Шаги',text:'- Один\n- Два',layout:'steps'}),/slide-steps/);
});
