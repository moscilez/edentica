// Disposable UI QA only. Uses an in-memory DB and a clearly labelled demo.
import {createApp} from '../server.mjs';
const {server,db}=createApp(':memory:',{hackathon:true});
await new Promise(resolve=>server.listen(3001,'127.0.0.1',resolve));
await fetch('http://127.0.0.1:3001/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json','X-Edentica':'1'},body:JSON.stringify({name:'Проверка интерфейса',email:'qa@example.test',password:'edentica-qa-only'})});
console.log('Temporary UI QA http://localhost:3001 — qa@example.test / edentica-qa-only. In-memory data only.');
process.on('SIGINT',()=>server.close(()=>{db.close();process.exit()}));
