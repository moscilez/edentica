export function unlockedModules(db,courseId,userId){
 const c=db.prepare('SELECT owner FROM courses WHERE id=?').get(courseId);
 const modules=db.prepare('SELECT * FROM modules WHERE course_id=? ORDER BY position').all(courseId);
 if(c?.owner===userId)return modules;
 if(!userId||!db.prepare('SELECT 1 FROM enrollments WHERE user_id=? AND course_id=?').get(userId,courseId))return [];
 const completed=new Set(db.prepare('SELECT p.module_id FROM progress p JOIN modules m ON m.id=p.module_id WHERE p.user_id=? AND m.course_id=?').all(userId,courseId).map(p=>p.module_id));
 let open=true;return modules.filter(m=>{const available=open;open=open&&completed.has(m.id);return available});
}
