export function migrateEnrollmentSources(db){db.exec(`CREATE TABLE IF NOT EXISTS enrollment_sources(user_id TEXT REFERENCES users(id),course_id TEXT REFERENCES courses(id),kind TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(user_id,course_id,kind,source));INSERT OR IGNORE INTO enrollment_sources SELECT e.user_id,e.course_id,'direct','legacy' FROM enrollments e WHERE NOT EXISTS(SELECT 1 FROM enrollment_sources s WHERE s.user_id=e.user_id AND s.course_id=e.course_id);`)}
export function grantEnrollment(db,userId,courseId,kind='direct',source='direct'){
 db.prepare('INSERT OR IGNORE INTO enrollments VALUES(?,?)').run(userId,courseId);
 db.prepare('INSERT OR IGNORE INTO enrollment_sources VALUES(?,?,?,?)').run(userId,courseId,kind,source);
}
export function removeOrganizationMember(db,orgId,userId){
 const courses=db.prepare("SELECT course_id FROM enrollment_sources WHERE user_id=? AND kind='organization' AND source=?").all(userId,orgId);
 db.prepare("DELETE FROM enrollment_sources WHERE user_id=? AND kind='organization' AND source=?").run(userId,orgId);
 db.prepare('DELETE FROM organization_members WHERE organization_id=? AND user_id=?').run(orgId,userId);
 for(const c of courses)if(!db.prepare('SELECT 1 FROM enrollment_sources WHERE user_id=? AND course_id=?').get(userId,c.course_id))db.prepare('DELETE FROM enrollments WHERE user_id=? AND course_id=?').run(userId,c.course_id);
}
