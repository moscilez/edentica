export function migrateReputation(db){db.exec(`CREATE TABLE IF NOT EXISTS course_lineages(course_id TEXT PRIMARY KEY REFERENCES courses(id),lineage_id TEXT NOT NULL);INSERT OR IGNORE INTO course_lineages SELECT id,id FROM courses;`)}
export function awardLearningXP(db,userId,courseId,kind,moduleId=null){
 const course=db.prepare('SELECT owner FROM courses WHERE id=?').get(courseId);if(!course||course.owner===userId)return;
 const root=db.prepare('SELECT lineage_id FROM course_lineages WHERE course_id=?').get(courseId)?.lineage_id||courseId;
 let event=kind+':'+root,points=kind==='exam'?300:500;
 if(kind==='module'){
  const module=db.prepare('SELECT position FROM modules WHERE id=? AND course_id=?').get(moduleId,courseId);if(!module)return;event='module:'+root+':'+module.position;points=100;
  const original=db.prepare('SELECT id FROM modules WHERE course_id=? AND position=?').get(root,module.position);
  if(original&&db.prepare('SELECT 1 FROM xp WHERE user_id=? AND event=?').get(userId,'module:'+original.id))return;
 }
 db.prepare('INSERT OR IGNORE INTO xp VALUES(?,?,?)').run(userId,event,points);
}
