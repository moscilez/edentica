import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
export function database(path) {
  mkdirSync(dirname(path), {recursive:true});
  const db=new DatabaseSync(path);
  db.exec(`PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL;
  CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),expires INTEGER NOT NULL);
  CREATE TABLE IF NOT EXISTS courses(id TEXT PRIMARY KEY,owner TEXT REFERENCES users(id),title TEXT NOT NULL,description TEXT NOT NULL,category TEXT NOT NULL,visibility TEXT NOT NULL DEFAULT 'public',published INTEGER NOT NULL DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS modules(id TEXT PRIMARY KEY,course_id TEXT REFERENCES courses(id),position INTEGER NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL,questions TEXT NOT NULL,threshold INTEGER NOT NULL DEFAULT 70,attempt_limit INTEGER NOT NULL DEFAULT 3,UNIQUE(course_id,position));
  CREATE TABLE IF NOT EXISTS enrollments(user_id TEXT REFERENCES users(id),course_id TEXT REFERENCES courses(id),PRIMARY KEY(user_id,course_id));
  CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),module_id TEXT REFERENCES modules(id),score INTEGER NOT NULL,passed INTEGER NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS progress(user_id TEXT REFERENCES users(id),module_id TEXT REFERENCES modules(id),score INTEGER NOT NULL,PRIMARY KEY(user_id,module_id));
  CREATE TABLE IF NOT EXISTS xp(user_id TEXT REFERENCES users(id),event TEXT NOT NULL,points INTEGER NOT NULL,PRIMARY KEY(user_id,event));
  CREATE TABLE IF NOT EXISTS invitations(token TEXT PRIMARY KEY,course_id TEXT REFERENCES courses(id),expires INTEGER NOT NULL,max_uses INTEGER NOT NULL,uses INTEGER NOT NULL DEFAULT 0,revoked INTEGER NOT NULL DEFAULT 0);
  CREATE TABLE IF NOT EXISTS certificates(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),course_id TEXT REFERENCES courses(id),name TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(user_id,course_id));
  CREATE TABLE IF NOT EXISTS course_versions(id TEXT PRIMARY KEY,course_id TEXT REFERENCES courses(id),snapshot TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE INDEX IF NOT EXISTS attempt_lookup ON attempts(user_id,module_id);
  CREATE INDEX IF NOT EXISTS module_lookup ON modules(course_id,position);`);
  db.exec(`CREATE INDEX IF NOT EXISTS course_catalog ON courses(published,visibility,created);
  CREATE INDEX IF NOT EXISTS course_owner ON courses(owner);
  CREATE INDEX IF NOT EXISTS enrollment_course ON enrollments(course_id,user_id);
  CREATE INDEX IF NOT EXISTS certificate_course ON certificates(course_id,user_id);`);
  return db;
}
