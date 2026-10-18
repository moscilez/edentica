"""Operator tool: upload a source bundle and run Docker without Git.

Reads SSH passwords from JSON stdin (never arguments); requires optional paramiko.
No credentials are copied to the bundle. VM model credentials are read on the VM.
"""
import base64
import io
import json
from pathlib import Path
import shlex
import sys
import tarfile
from datetime import datetime, timezone

import paramiko
sys.stdout.reconfigure(encoding='utf-8',errors='replace')

ROOT=Path(__file__).resolve().parent.parent


def bundle():
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w:gz') as archive:
        files=['Dockerfile','compose.yaml','package.json','requirements.txt','requirements-dev.txt','requirements-lock.txt','.env.docker.example','.dockerignore']
        for directory in ('backend','public','src','scripts','templates','deploy','tests_python','docs'):
            files.extend(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
        for name in files:
            archive.add(ROOT/name,arcname=Path(name).as_posix(),recursive=False)
    return data.getvalue()


def main():
    config=json.load(sys.stdin)
    clients=[]
    known=ROOT/'data/vm_known_hosts'
    known.parent.mkdir(exist_ok=True)
    def client():
        c=paramiko.SSHClient()
        if known.exists():c.load_host_keys(str(known))
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        clients.append(c)
        return c
    try:
        jump=client();jump.connect(config['jumpHost'],username=config['jumpUser'],password=config['jumpPassword'],timeout=12,auth_timeout=12,allow_agent=False,look_for_keys=False)
        jump.save_host_keys(str(known))
        channel=jump.get_transport().open_channel('direct-tcpip',(config['host'],22),('127.0.0.1',0),timeout=12)
        team=client();team.connect(config['host'],username=config['user'],password=config['password'],sock=channel,timeout=12,auth_timeout=12,allow_agent=False,look_for_keys=False)
        team.save_host_keys(str(known))
        def run(cmd,timeout=30):
            _,out,err=team.exec_command(cmd,timeout=timeout)
            stdout=out.read().decode(errors='replace');stderr=err.read().decode(errors='replace')
            code=out.channel.recv_exit_status()
            return code,stdout,stderr
        if config.get('action')=='install-compose':
            code,out,err=run("mkdir -p ~/.docker/cli-plugins && curl -fSL --connect-timeout 15 --max-time 90 https://github.com/docker/compose/releases/download/v2.39.4/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose && chmod 755 ~/.docker/cli-plugins/docker-compose && docker compose version",timeout=110)
            print(out[:1000]);print(err[-800:]);return
        if config.get('action')=='inspect':
            code,out,err=run("docker compose version; docker compose ls --format json; ss -ltn '( sport = :8000 )' | head -3; df -h . | tail -1; ls -A ~/project | head -15")
            print(out[:3500]);print(err[:1200]);return
        state_path=ROOT/'data/vm-release.json'
        if config.get('action')=='stage':
            stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
            release='project/edentica-release-'+stamp
            run('mkdir -p '+shlex.quote(release)+'/logs')
            sftp=team.open_sftp()
            with sftp.open(release+'/source.tar.gz','wb') as f:f.write(bundle())
            sftp.close()
            script='''import os,tarfile,secrets,base64,shlex
from pathlib import Path
root=Path.cwd()
with tarfile.open('source.tar.gz') as t:t.extractall('.',filter='data')
config={}
for line in Path('/opt/hackathon/ai.env').read_text().splitlines():
    line=line.strip().removeprefix('export ')
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1)
        try:config[k]=shlex.split(v)[0]
        except (ValueError,IndexError):continue
settings={'POSTGRES_PASSWORD':secrets.token_hex(32),'APP_ENCRYPTION_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),'PUBLIC_URL':os.environ['DEMO_URL'],'BIND_ADDRESS':'0.0.0.0','HTTP_PORT':'8000','COOKIE_SECURE':'1','LLM_BASE_URL':config.get('OPENAI_BASE_URL',''),'LLM_API_KEY':config.get('OPENAI_API_KEY',''),'LLM_MODEL':'GigaChat/GigaChat-3-Pro'}
persistent=Path.home()/'.config/edentica/runtime.env'
persistent.parent.mkdir(parents=True,exist_ok=True)
if not persistent.exists():
    persistent.write_text(''.join(k+'='+shlex.quote(v)+'\\n' for k,v in settings.items()))
    persistent.chmod(0o600)
with open('.env.docker','x') as f:f.write(persistent.read_text())
os.chmod('.env.docker',0o600)
print('Release staged; model credentials loaded on VM only.')
'''
            command='cd '+shlex.quote(release)+' && DEMO_URL='+shlex.quote(config['publicUrl'])+' python3 -c '+shlex.quote(script)
            code,out,err=run(command)
            if code:raise RuntimeError('Stage failed: '+err[:500])
            state_path.write_text(json.dumps({'path':release,'project':'edentica','publicUrl':config['publicUrl']}),encoding='utf-8')
            print(out);print('Release: '+release)
            return
        state=json.loads(state_path.read_text(encoding='utf-8'))
        prefix='cd '+shlex.quote(state['path'])+' && docker compose --env-file .env.docker '
        actions={
            'build':prefix+'--profile test build >logs/build.log 2>&1',
            'test':prefix+'--profile test run --rm test >logs/test.log 2>&1',
            'start':prefix+'up -d --wait >logs/start.log 2>&1',
            'status':prefix+'ps --format json',
            'stop-test':prefix+'--profile test stop test-db',
            'pause-frontend':prefix+'stop frontend',
            'http-smoke':"python3 -c "+shlex.quote("import urllib.request,json; urls=['http://127.0.0.1:8000/','http://127.0.0.1:8000/api/health']; results=[]\nfor url in urls:\n r=urllib.request.urlopen(url,timeout=10); b=r.read(200000); results.append({'path':url.split(':8000')[-1],'status':r.status,'bytes':len(b),'edentica':('Эдентика'.encode() in b),'body':b.decode() if url.endswith('/api/health') else None})\nprint(json.dumps(results,ensure_ascii=False))"),
            'logs':'cd '+shlex.quote(state['path'])+' && tail -60 logs/build.log; tail -45 '+shlex.quote(state['path'])+'/logs/test.log',
        }
        actions['release']='cd '+shlex.quote(state['path'])+' && docker compose --env-file .env.docker --profile test build >logs/build.log 2>&1 && docker compose --env-file .env.docker --profile test run --rm test >logs/test.log 2>&1 && docker compose --env-file .env.docker up -d --wait >logs/start.log 2>&1'
        actions['verify-gateway']=prefix+'exec -T backend python - --provider gateway < scripts/verify-codex-generation.py >logs/gateway-check.log 2>&1'
        action=config['action']
        if action in ('build','test','start','release','verify-gateway'):
            if action in ('start','release'):
                code,out,err=run('mkdir -p ~/.config/edentica && if [ ! -e ~/.config/edentica/runtime.env ]; then cp '+shlex.quote(state['path'])+'/.env.docker ~/.config/edentica/runtime.env; chmod 600 ~/.config/edentica/runtime.env; fi')
            logfile=action+'.log'
            cmd='cd '+shlex.quote(state['path'])+' && nohup sh -c '+shlex.quote(actions[action])+' </dev/null >/dev/null 2>&1 &'
            # The inner action uses a home-relative directory; start from home.
            cmd='nohup sh -c '+shlex.quote(actions[action])+' </dev/null >/dev/null 2>&1 &'
            code,out,err=run(cmd)
            print(json.dumps({'action':action,'dispatched':code==0,'path':state['path']}))
        elif action=='progress':
            task=config.get('task','build')
            code,out,err=run('cd '+shlex.quote(state['path'])+' && tail -45 logs/'+shlex.quote(task)+'.log')
            print(out[-6500:]);print(err[:300])
        elif action=='patch':
            sftp=team.open_sftp()
            for relative in config['files']:
                local=(ROOT/relative).resolve()
                if not local.is_relative_to(ROOT) or (relative.startswith(('.env','data/','output/','.git')) and relative not in ('.env.docker.example','.env.example')):raise ValueError('Forbidden path')
                sftp.put(str(local),state['path']+'/'+relative)
            sftp.close();print('Source patch uploaded.')
        elif action=='smoke-model':
            source="import asyncio,json;from backend.cloudru import complete;r=asyncio.run(complete('Return only a JSON object with ok set to true.',{}));print(json.dumps({'ok':r['value'].get('ok') is True,'model':r['model'],'usage':r['usage']}))"
            code,out,err=run(prefix+'exec -T backend python -c '+shlex.quote(source),timeout=160)
            print(out[:1000]);print(err[-1000:])
        elif action=='backup-db':
            name='logs/db-before-usage-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.dump'
            code,out,err=run(prefix+'exec -T db pg_dump -U edentica -d edentica -Fc > '+shlex.quote(name))
            if code:raise RuntimeError('Database backup failed')
            code,out,err=run(prefix+'exec -T db pg_restore --list < '+shlex.quote(name)+' > /dev/null')
            if code:raise RuntimeError('Database backup validation failed')
            print('Database backup verified: '+state['path']+'/'+name)
        elif action=='verify-runtime':
            import hashlib
            names=['backend/app.py','backend/programs.py','backend/models.py','backend/cloudru.py',
                   'backend/codex_provider.py','backend/usage.py','backend/schema.sql',
                   'public/usage.js','public/workspace.js','public/workspace.css','public/program-studio.js']
            expected={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
            source="import json,hashlib;from pathlib import Path;expected="+repr(expected)+";bad=[n for n,h in expected.items() if hashlib.sha256(Path(n).read_bytes()).hexdigest()!=h];print(json.dumps({'checkedFiles':len(expected),'mismatches':bad}))"
            code,out,err=run(prefix+'exec -T backend python -c '+shlex.quote(source))
            print(out);print(err[:500])
            source="import urllib.request,hashlib,json;r=urllib.request.urlopen('http://127.0.0.1:8000/usage.js',timeout=10);print(json.dumps({'usageAssetStatus':r.status,'usageAssetMatches':hashlib.sha256(r.read()).hexdigest()=="+repr(expected['public/usage.js'])+"}))"
            code,out,err=run('python3 -c '+shlex.quote(source));print(out);print(err[:500])
        elif action=='uptime-status':
            code,out,err=run('systemctl is-enabled docker; systemctl is-active docker')
            print('Docker service: '+out.strip());print(err[:300])
            code,out,err=run(prefix+'ps -q backend frontend db')
            ids=out.split()
            if len(ids)!=3:raise RuntimeError('Expected three running services')
            code,out,err=run('docker inspect '+ ' '.join(shlex.quote(x) for x in ids))
            for item in json.loads(out):
                print(json.dumps({'container':item['Name'],'restartPolicy':item['HostConfig']['RestartPolicy']['Name'],
                                  'running':item['State']['Running'],'health':item['State'].get('Health',{}).get('Status')}))
        elif action=='user-count':
            source="import os,json,psycopg;from psycopg.rows import dict_row\nwith psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:\n rows=c.execute('SELECT role,count(*) AS count FROM users GROUP BY role ORDER BY role').fetchall()\n print(json.dumps({'total':sum(r['count'] for r in rows),'byRole':rows}))"
            code,out,err=run(prefix+'exec -T backend python -c '+shlex.quote(source));print(out);print(err[:500])
        elif action=='model-access-status':
            source="import os,json;print(json.dumps({'provider':os.getenv('LLM_PROVIDER'),'model':os.getenv('LLM_MODEL') or os.getenv('CLOUDRU_MODEL'),'configured':bool((os.getenv('LLM_API_KEY') or os.getenv('CLOUDRU_API_KEY')) and (os.getenv('LLM_MODEL') or os.getenv('CLOUDRU_MODEL'))),'sharedAccess':os.getenv('SYSTEM_LLM_SHARED_ACCESS')=='1','allowedAccountCount':len([v for v in os.getenv('SYSTEM_LLM_ALLOWED_USERS','').split(',') if v.strip()])}))"
            code,out,err=run(prefix+'exec -T backend python -c '+shlex.quote(source));print(out);print(err[:500])
        elif action=='enable-shared-model':
            source="from pathlib import Path;p=Path('.env.docker');s=p.read_text();s='\\n'.join(x for x in s.splitlines() if not x.startswith('SYSTEM_LLM_SHARED_ACCESS='))+'\\nSYSTEM_LLM_SHARED_ACCESS=1\\n';p.write_text(s);p.chmod(0o600);saved=Path.home()/'.config/edentica/runtime.env';saved.write_text(s);saved.chmod(0o600);print('Shared model access enabled; keys remain server-side.')"
            code,out,err=run('cd '+shlex.quote(state['path'])+' && python3 -c '+shlex.quote(source))
            if code:raise RuntimeError('Could not update shared model access')
            print(out)
            command=prefix+'up -d --no-deps --force-recreate --wait backend frontend >logs/shared-access.log 2>&1'
            code,out,err=run('nohup sh -c '+shlex.quote(command)+' </dev/null >/dev/null 2>&1 &')
            print(json.dumps({'restartDispatched':code==0}))
        elif action=='verify-shared-model':
            source='''import os,json,secrets,urllib.request,psycopg
from http.cookies import SimpleCookie
login='vm-access-check-'+secrets.token_hex(8)
headers={'Host':'localhost','X-Edentica':'1','Content-Type':'application/json'}
def request(path,data=None):
    return urllib.request.urlopen(urllib.request.Request('http://frontend:8000/api'+path,headers=headers,data=json.dumps(data).encode() if data is not None else None),timeout=10)
account=None
try:
    response=request('/auth/register',{'login':login,'name':'Проверка доступа на ВМ','password':secrets.token_urlsafe(24),'role':'methodist'})
    account=json.load(response);cookie=SimpleCookie();cookie.load(response.headers['Set-Cookie']);headers['Cookie']='session='+cookie['session'].value
    status=json.load(request('/agent',{'action':'status'}));usage=json.load(request('/usage?days=7&timezone=Europe/Moscow'))
    print(json.dumps({'newAccountModelConfigured':status['configured'],'model':status.get('model'),'usageDays':len(usage['days']),'hasPersonalConnection':bool(status.get('personal'))}))
finally:
    if account:
        with psycopg.connect(os.environ['DATABASE_URL']) as c:
            c.execute('DELETE FROM users WHERE id=%s AND login=%s',(account['id'],login))
'''
            code,out,err=run(prefix+'exec -T backend python -c '+shlex.quote(source));print(out);print(err[-1000:])
        elif action=='allow-internal-gateway':
            source="from pathlib import Path; p=Path('.env.docker'); s=p.read_text(); flag='SYSTEM_LLM_ALLOW_PRIVATE_NETWORK=1'; s='\\n'.join(x for x in s.splitlines() if not x.startswith('SYSTEM_LLM_ALLOW_PRIVATE_NETWORK='))+'\\n'+flag+'\\n'; p.write_text(s); (Path.home()/'.config/edentica/runtime.env').write_text(s); print('Administrator-configured gateway private-network access enabled.')"
            code,out,err=run('cd '+shlex.quote(state['path'])+' && python3 -c '+shlex.quote(source))
            print(out);print(err[:500])
        elif action in actions:
            code,out,err=run(actions[action])
            if action=='status':
                for line in out.splitlines():
                    item=json.loads(line)
                    print(json.dumps({k:item.get(k) for k in ('Service','State','Health','Ports')}))
            else:print(out[:4500])
            print(err[:1000])
    finally:
        for c in reversed(clients):c.close()


if __name__=='__main__':main()
