import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../server.mjs';
import {awardLearningXP} from '../src/reputation.mjs';
import {rejectCredentials} from '../src/secret-guard.mjs';
test('Learning XP excludes own courses and repeated course editions',()=>{
 const {db}=createApp(':memory:');
 try{
  for(const id of ['author','student'])db.prepare('INSERT INTO users(id,name,email,password) VALUES(?,?,?,?)').run(id,id,id+'@test.local','fixture');
  for(const id of ['original','edition'])db.prepare('INSERT INTO courses(id,owner,title,description,category) VALUES(?,?,?,?,?)').run(id,'author','Course','Description','AI');
  db.prepare('INSERT INTO course_lineages VALUES(?,?)').run('edition','original');
  for(const [id,course]of [['first','original'],['second','edition']])db.prepare('INSERT INTO modules VALUES(?,?,?,?,?,?,?,?)').run(id,course,0,'Module','Content','[]',70,3);
  awardLearningXP(db,'author','original','module','first');assert.equal(db.prepare('SELECT count(*) n FROM xp').get().n,0);
  awardLearningXP(db,'student','original','module','first');awardLearningXP(db,'student','edition','module','second');assert.equal(db.prepare('SELECT sum(points) n FROM xp').get().n,100);
  assert.throws(()=>rejectCredentials('API key: sk-'+ 'a'.repeat(30)));assert.doesNotThrow(()=>rejectCredentials('API key: YOUR_API_KEY'));
 }finally{db.close()}
});
