# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import asyncio, hashlib, json, os, re, secrets, shutil, sqlite3, subprocess, time, uuid
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

ROOT=Path(os.environ.get('AI_SANDBOX_ROOT','/srv/ai-sandbox/users'))
DB=os.environ.get('AI_SANDBOX_DB','/var/lib/ai-sandbox/state.db')
TOKEN=os.environ.get('AI_SANDBOX_TOKEN','')
if not TOKEN and os.environ.get('AI_SANDBOX_TOKEN_FILE'):
    TOKEN=Path(os.environ['AI_SANDBOX_TOKEN_FILE']).read_text(encoding='ascii').strip()
IMAGE=os.environ.get('AI_SANDBOX_IMAGE','docker.io/library/python@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4')
TRUSTED_CLIENTS={item.strip() for item in os.environ.get('AI_SANDBOX_TRUSTED_CLIENTS','127.0.0.1').split(',') if item.strip()}
QUOTA_MOUNT=os.environ.get('AI_SANDBOX_QUOTA_MOUNT','/srv/ai-sandbox')
RUNNER_NAME=os.environ.get('AI_SANDBOX_RUNNER','sandbox-runner')
RUNNER_UID=int(os.environ.get('AI_SANDBOX_RUNNER_UID','1001'))
PROJECT_MIN=int(os.environ.get('AI_SANDBOX_PROJECT_MIN','20001'))
PROJECT_MAX=int(os.environ.get('AI_SANDBOX_PROJECT_MAX','20010'))
TIMEOUT_SECONDS=int(os.environ.get('AI_SANDBOX_TIMEOUT_SECONDS','60'))
NAME=re.compile(r'^[A-Za-z0-9_.-]{1,64}$'); FILE=re.compile(r'^[A-Za-z0-9_.-]{1,96}\.py$')
job_lock=asyncio.Lock(); app=FastAPI(docs_url=None,redoc_url=None)

class UserBody(BaseModel): username:str=Field(min_length=1,max_length=64)
class SaveBody(UserBody): filename:str=Field(min_length=4,max_length=99); content:str=Field(max_length=1_048_576)
class RunBody(UserBody): filename:str=Field(min_length=4,max_length=99); args:list[str]=Field(default_factory=list,max_length=16)

def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def auth(request:Request, authorization:str|None):
    if request.client is None or request.client.host not in TRUSTED_CLIENTS: raise HTTPException(403,'client non autorizzato')
    if len(TOKEN)<32 or not authorization or not secrets.compare_digest(authorization,f'Bearer {TOKEN}'): raise HTTPException(401,'token non valido')
def clean_user(value:str)->str:
    if value.casefold()=='guest': raise HTTPException(403,'Guest non può usare script')
    if not NAME.fullmatch(value): raise HTTPException(400,'utente non valido')
    return value
def clean_file(value:str)->str:
    if not FILE.fullmatch(value): raise HTTPException(400,'file Python non valido')
    return value
def setup():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    with conn() as c:
        c.executescript('''PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,project_id INTEGER UNIQUE,path TEXT,created_at INTEGER); CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at INTEGER,username TEXT,action TEXT,status TEXT,detail TEXT);''')
setup()

def ensure_user(username:str):
    username=clean_user(username)
    with conn() as c:
        row=c.execute('select * from users where username=?',(username,)).fetchone()
        if row:return dict(row)
        used={int(r[0]) for r in c.execute('select project_id from users')}
        pid=next((candidate for candidate in range(PROJECT_MIN,PROJECT_MAX+1) if candidate not in used),None)
        if pid is None: raise HTTPException(409,'capienza account sandbox esaurita')
        path=ROOT/hashlib.sha256(username.encode()).hexdigest()[:24]
        path.mkdir(mode=0o750); os.chown(path,RUNNER_UID,RUNNER_UID)
        subprocess.run(['chattr','-p',str(pid),str(path)],check=True)
        subprocess.run(['setquota','-P',str(pid),'2097152','2097152','20000','20000',QUOTA_MOUNT],check=True)
        c.execute('insert into users values(?,?,?,?)',(username,pid,str(path),int(time.time())))
        c.execute('insert into audit(at,username,action,status,detail) values(?,?,?,?,?)',(int(time.time()),username,'ensure','ok','quota=2GiB,inodes=20000'))
        return {'username':username,'project_id':pid,'path':str(path)}

@app.get('/healthz')
def health(): return {'status':'ok','mode':'python-rootless-network-none','busy':job_lock.locked()}
@app.post('/v1/users/ensure')
def ensure(body:UserBody,request:Request,authorization:str|None=Header(None)):
    auth(request,authorization); ensure_user(body.username); return {'ok':True,'quota_bytes':2*1024**3,'inode_limit':20000}
@app.delete('/v1/users/{username}')
def remove_user(username:str,request:Request,authorization:str|None=Header(None)):
    auth(request,authorization); username=clean_user(username)
    if job_lock.locked(): raise HTTPException(409,'sandbox occupata')
    with conn() as c:
        row=c.execute('select * from users where username=?',(username,)).fetchone()
        if not row:return {'ok':True,'deleted':False}
        project_id=int(row['project_id']); path=Path(row['path'])
        root=ROOT.resolve()
        if path.parent.resolve()!=root or path.is_symlink() or not (PROJECT_MIN<=project_id<=PROJECT_MAX):
            raise HTTPException(409,'workspace non cancellabile in sicurezza')
        if path.exists():shutil.rmtree(path)
        subprocess.run(['setquota','-P',str(project_id),'0','0','0','0',QUOTA_MOUNT],check=True)
        c.execute('delete from users where username=?',(username,))
        c.execute('insert into audit(at,username,action,status,detail) values(?,?,?,?,?)',(int(time.time()),username,'delete','ok',f'project_id={project_id}'))
        return {'ok':True,'deleted':True}
@app.get('/v1/scripts')
def listing(username:str,request:Request,authorization:str|None=Header(None)):
    auth(request,authorization); row=ensure_user(username); return {'scripts':sorted(p.name for p in Path(row['path']).glob('*.py'))}
@app.post('/v1/scripts')
def save(body:SaveBody,request:Request,authorization:str|None=Header(None)):
    auth(request,authorization); row=ensure_user(body.username); name=clean_file(body.filename); data=body.content.encode()
    if len(data)>1_048_576: raise HTTPException(413,'script troppo grande')
    target=Path(row['path'])/name; tmp=target.with_suffix('.tmp'); tmp.write_bytes(data); os.chown(tmp,RUNNER_UID,RUNNER_UID); os.chmod(tmp,0o640); os.replace(tmp,target)
    return {'ok':True,'filename':name,'bytes':len(data)}
@app.delete('/v1/scripts/{filename}')
def delete(filename:str,username:str,request:Request,authorization:str|None=Header(None)):
    auth(request,authorization); row=ensure_user(username); target=Path(row['path'])/clean_file(filename); target.unlink(missing_ok=True); return {'ok':True}
@app.post('/v1/run')
async def run(body:RunBody,request:Request,authorization:str|None=Header(None)):
    auth(request,authorization); row=ensure_user(body.username); name=clean_file(body.filename); target=Path(row['path'])/name
    if not target.is_file(): raise HTTPException(404,'script non trovato')
    if job_lock.locked(): raise HTTPException(409,'sandbox occupata')
    for arg in body.args:
        if len(arg)>256 or '\x00' in arg: raise HTTPException(400,'argomento non valido')
    async with job_lock:
        job='r740-'+uuid.uuid4().hex[:12]
        cmd=['runuser','-u',RUNNER_NAME,'--','/bin/sh','-c','cd / && exec "$@"','sandbox-exec','env',f'XDG_RUNTIME_DIR=/run/user/{RUNNER_UID}',f'HOME=/home/{RUNNER_NAME}','podman','run','--rm','--name',job,'--network','none','--read-only','--pids-limit','64','--memory','512m','--cpus','1','--cap-drop','all','--security-opt','no-new-privileges','--user','0:0','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=64m','-v',f"{row['path']}:/workspace:rw,nosuid,nodev,noexec",IMAGE,'python',f'/workspace/{name}',*body.args]
        started=time.monotonic()
        try:
            p=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            out,err=await asyncio.wait_for(p.communicate(),timeout=TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            subprocess.run(['runuser','-u',RUNNER_NAME,'--','env',f'XDG_RUNTIME_DIR=/run/user/{RUNNER_UID}',f'HOME=/home/{RUNNER_NAME}','podman','rm','-f',job],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); raise HTTPException(408,f'tempo massimo {TIMEOUT_SECONDS} secondi')
        limit=65536
        if len(out)>limit or len(err)>limit: raise HTTPException(413,'output oltre 64 KiB')
        return {'exit_code':p.returncode,'stdout':out.decode('utf-8','replace'),'stderr':err.decode('utf-8','replace'),'elapsed_ms':int((time.monotonic()-started)*1000)}
