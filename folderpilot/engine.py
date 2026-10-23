"""Conservative local file plans, exclusive verified copies and durable recovery records."""
from __future__ import annotations
import hashlib
import html
import json
import os
import re
import stat
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

class PilotError(ValueError):
    pass

class Cancelled(Exception):
    pass


def check(cancel=None):
    if cancel and cancel.is_set():
        raise Cancelled('Cancelled. Review the run record before recovery or retry.')


def plain(path):
    """Reject symbolic links, junctions and other reparse points, including parents."""
    p=Path(os.path.abspath(path))
    for part in [*reversed(p.parents),p]:
        try:s=part.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:
            raise PilotError(f'Links and reparse points are not supported: {part}')
    return p.resolve(strict=False)


def within(path,root):
    p=plain(path);r=plain(root)
    if not p.is_relative_to(r):raise PilotError('Path escapes the selected directory.')
    return p


def safe_name(name):
    if not name or name in ('.','..') or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith((' ','.')):
        raise PilotError(f'Invalid Windows filename: {name!r}')
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise PilotError(f'Reserved Windows filename: {name}')
    if len(name.encode('utf-16-le'))//2>255:raise PilotError('Filename exceeds 255 UTF-16 code units.')
    return name


def digest(path,cancel=None):
    p=plain(path)
    before=p.stat()
    if not stat.S_ISREG(before.st_mode):raise PilotError(f'Not a regular file: {p}')
    h=hashlib.sha256()
    with p.open('rb') as f:
        while chunk:=f.read(1024*1024):check(cancel);h.update(chunk)
    after=p.stat()
    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
        raise PilotError(f'File changed while reading: {p.name}')
    return h.hexdigest()

@dataclass
class Rules:
    version:int=1
    mode:str='rename'
    recursive:bool=True
    extensions:str=''
    min_bytes:int=0
    max_bytes:int=0
    since:str=''
    until:str=''
    find:str=''
    replace:str=''
    regex:bool=False
    prefix:str=''
    suffix:str=''
    number:bool=False
    start:int=1
    padding:int=3
    organize_by:str='type'
    watch_seconds:int=5

    def validate(self):
        if self.version!=1 or self.mode not in ('rename','organize','duplicates','backup','sync'):raise PilotError('Unsupported rule version or mode.')
        for name in ('recursive','regex','number'):
            if type(getattr(self,name)) is not bool:raise PilotError(f'{name} must be a boolean.')
        for name in ('min_bytes','max_bytes','start','padding','watch_seconds'):
            if type(getattr(self,name)) is not int:raise PilotError(f'{name} must be an integer.')
        if min(self.min_bytes,self.max_bytes,self.start)<0 or not 1<=self.padding<=12 or not 2<=self.watch_seconds<=3600:
            raise PilotError('Sizes/start must be non-negative; padding 1–12; watch interval 2–3600 seconds.')
        if self.max_bytes and self.max_bytes<self.min_bytes:raise PilotError('Maximum size is below minimum size.')
        for name in ('extensions','since','until','find','replace','prefix','suffix','organize_by'):
            if not isinstance(getattr(self,name),str):raise PilotError(f'{name} must be text.')
        for val in (self.since,self.until):
            if val:
                try:datetime.strptime(val,'%Y-%m-%d')
                except ValueError:raise PilotError('Dates must use YYYY-MM-DD.')
        if self.since and self.until and self.since>self.until:raise PilotError('Date range is reversed.')
        if self.organize_by not in ('type','date','size'):raise PilotError('Organize by type, date or size.')
        if self.regex:
            if len(self.find)>256:raise PilotError('Regex pattern is limited to 256 characters.')
            try:re.compile(self.find).sub(self.replace,'sample')
            except re.error as exc:raise PilotError(f'Invalid regex rule: {exc}') from exc

    def save(self,path):
        self.validate()
        with Path(path).open('x',encoding='utf-8') as f:json.dump(asdict(self),f,indent=2)

    @classmethod
    def load(cls,path):
        try:r=cls(**json.loads(Path(path).read_text(encoding='utf-8')));r.validate();return r
        except (TypeError,ValueError,OSError) as e:raise PilotError(f'Cannot load rules: {e}') from e

@dataclass
class Action:
    source:str
    destination:str
    kind:str
    sha256:str
    size:int
    mtime_ns:int

@dataclass
class Plan:
    source_root:str
    target_root:str
    rules:Rules
    actions:list[Action]=field(default_factory=list)
    duplicates:list[list[str]]=field(default_factory=list)
    warnings:list[str]=field(default_factory=list)
    conflicts:list[str]=field(default_factory=list)
    scanned:int=0
    unchanged:int=0


def inventory(source,rules,cancel=None,warnings=None):
    if not str(source).strip():raise PilotError('Select a source directory explicitly.')
    rules.validate();root=plain(source)
    if not root.is_dir():raise PilotError('Select an existing source directory.')
    warnings=warnings if warnings is not None else []
    extensions={'.'+v.strip().lower().lstrip('.') for v in rules.extensions.split(',') if v.strip()}
    def fail(error):raise PilotError(f'Cannot scan selected directory: {error}')
    for base,dirs,files in os.walk(root,followlinks=False,onerror=fail):
        check(cancel);dirs.sort(key=str.casefold)
        for d in list(dirs):
            try:plain(Path(base)/d)
            except PilotError as e:dirs.remove(d);warnings.append(str(e))
        if not rules.recursive:dirs.clear()
        for name in sorted(files,key=str.casefold):
            check(cancel);p=Path(base)/name
            try:
                plain(p);s=p.stat()
                if not stat.S_ISREG(s.st_mode):continue
                if s.st_nlink>1: warnings.append(f'Hard-linked file skipped: {p.relative_to(root)}');continue
                day=datetime.fromtimestamp(s.st_mtime,timezone.utc).strftime('%Y-%m-%d')
                if extensions and p.suffix.lower() not in extensions:continue
                if s.st_size<rules.min_bytes or (rules.max_bytes and s.st_size>rules.max_bytes):continue
                if (rules.since and day<rules.since) or (rules.until and day>rules.until):continue
                yield p,s
            except (OSError,PilotError) as exc:warnings.append(f'Skipped {p.name}: {exc}')


def build_plan(source,rules=None,target='',cancel=None,progress=None):
    if not str(source).strip():raise PilotError('Select a source directory explicitly.')
    rules=rules or Rules();rules.validate();root=plain(source)
    target_root=plain(target) if rules.mode in ('backup','sync') and target else root
    if rules.mode in ('backup','sync'):
        if not target or not target_root.is_dir():raise PilotError('Select an existing backup/sync destination.')
        if target_root.is_relative_to(root) or root.is_relative_to(target_root):raise PilotError('Source and destination must be separate, non-overlapping directories.')
    plan=Plan(str(root),str(target_root),Rules(**asdict(rules)))
    seen={};targets=set();snapshot='backup-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    number=rules.start
    for p,s in inventory(root,rules,cancel,plan.warnings):
        check(cancel);plan.scanned+=1;rel=p.relative_to(root)
        try:h=digest(p,cancel)
        except (OSError,PilotError) as e:plan.warnings.append(f'Cannot hash {rel}: {e}');continue
        if rules.mode=='duplicates':seen.setdefault((s.st_size,h),[]).append(str(rel));continue
        if rules.mode=='rename':
            stem=p.stem
            if rules.find:stem=re.sub(rules.find,rules.replace,stem) if rules.regex else stem.replace(rules.find,rules.replace)
            if rules.number:stem=f'{stem}_{number:0{rules.padding}d}';number+=1
            dst=p.with_name(safe_name(rules.prefix+stem+rules.suffix+p.suffix))
        elif rules.mode=='organize':
            group=(p.suffix.lower().lstrip('.') or 'no-extension') if rules.organize_by=='type' else datetime.fromtimestamp(s.st_mtime,timezone.utc).strftime('%Y-%m') if rules.organize_by=='date' else 'small-under-1MiB' if s.st_size<1024**2 else 'medium-under-100MiB' if s.st_size<100*1024**2 else 'large-100MiB-plus'
            dst=root/safe_name(group)/p.name
        elif rules.mode=='backup':dst=target_root/snapshot/rel
        else:
            dst=target_root/rel
            if dst.exists():
                if dst.is_file() and digest(dst,cancel)==h:plan.unchanged+=1;continue
                dst=dst.with_name(safe_name(dst.stem+'.fp-'+h[:16]+dst.suffix))
                if dst.is_file() and digest(dst,cancel)==h:plan.unchanged+=1;continue
        if str(p)==str(dst):plan.unchanged+=1;continue
        within(dst,target_root)
        key=str(dst).casefold()
        if key in targets or os.path.lexists(dst):plan.conflicts.append(f'Destination exists or repeats: {dst.relative_to(target_root)}')
        targets.add(key)
        plan.actions.append(Action(str(rel),str(dst.relative_to(target_root)),'move' if rules.mode in ('rename','organize') else 'copy',h,s.st_size,s.st_mtime_ns))
        if progress and plan.scanned%100==0:progress(plan.scanned)
    if rules.mode=='duplicates':plan.duplicates=[v for v in seen.values() if len(v)>1]
    return plan


def paths(plan,action):
    return within(Path(plan.source_root)/action.source,plan.source_root),within(Path(plan.target_root)/action.destination,plan.target_root)


def verify_source(src,action,cancel=None):
    s=plain(src).stat()
    if s.st_size!=action.size or s.st_mtime_ns!=action.mtime_ns or digest(src,cancel)!=action.sha256:
        raise PilotError(f'Source changed since preview. Preview again: {src.name}')


def make_parents(path,root):
    root=plain(root);path=within(path,root)
    relative=path.relative_to(root);current=root
    for part in relative.parts:
        safe_name(part);current=current/part
        try:current.mkdir()
        except FileExistsError:pass
        plain(current)
        if not current.is_dir():raise PilotError(f'Not a directory: {current}')


def copy_verified(src,dst,expected,cancel=None,on_created=None):
    # Exclusive creation prevents overwrites, including races after the preview.
    plain(src);plain(dst)
    with src.open('rb') as source,dst.open('xb') as output:
        if on_created:on_created()
        while chunk:=source.read(1024*1024):
            check(cancel);output.write(chunk)
        output.flush();os.fsync(output.fileno())
    if digest(dst,cancel)!=expected or digest(src,cancel)!=expected:
        raise PilotError('Copy integrity verification failed; originals and recovery record retained.')
    source_stat=src.stat();os.utime(dst,ns=(source_stat.st_atime_ns,source_stat.st_mtime_ns))


def durable_json(path,data):
    # Replacing our own metadata is permitted; user file paths never use replace().
    temp=path.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8') as f:json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def write_report(run,record):
    rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in (e['action']['kind'],e['action']['source'],e['action']['destination'],e['state'],e.get('archive_path','')))+'</tr>' for e in record['entries'])
    msg=html.escape(record.get('message',''))
    (run/'report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>FolderPilot run</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;color:#19334c}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #ccd5dd;text-align:left}</style><h1>FolderPilot execution record</h1><p>'+html.escape(record['status'])+' — '+msg+'</p><p>No existing destination files were overwritten. Keep this directory for recovery.</p><table><tr><th>Operation</th><th>Source</th><th>Destination</th><th>State</th><th>Recovery archive</th></tr>'+rows+'</table></html>',encoding='utf-8')


def execute(plan,records_folder,dry_run=True,confirmed=False,cancel=None,progress=None):
    if dry_run:return {'dry_run':True,'operations':len(plan.actions),'conflicts':list(plan.conflicts)}
    if not confirmed:raise PilotError('Execution requires explicit confirmation after Dry Run.')
    if plan.rules.mode=='duplicates':raise PilotError('Duplicate detection is read-only. Nothing to execute.')
    if plan.conflicts:raise PilotError('Resolve all destination conflicts and preview again.')
    records=plain(records_folder)
    if not records.is_dir():raise PilotError('Select an existing records folder.')
    for scope in (Path(plan.source_root),Path(plan.target_root)):
        if records.is_relative_to(scope) or scope.is_relative_to(records):raise PilotError('Records folder must be separate from source and destination.')
    plan.rules.validate()
    # Verify the entire plan before the first mutation, and each source again before copying.
    destinations=set()
    for action in plan.actions:
        check(cancel);src,dst=paths(plan,action)
        if action.kind not in ('copy','move'):raise PilotError('Invalid operation in plan.')
        verify_source(src,action,cancel)
        key=str(dst).casefold()
        if os.path.lexists(dst) or key in destinations:raise PilotError(f'Destination conflict: {dst.name}')
        destinations.add(key)
    run=records/('run-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);run.mkdir()
    record={'version':1,'source_root':plan.source_root,'target_root':plan.target_root,'rules':asdict(plan.rules),'status':'running','message':'','entries':[]}
    journal=run/'journal.json';durable_json(journal,record)
    try:
        for action in plan.actions:
            check(cancel);src,dst=paths(plan,action);verify_source(src,action,cancel)
            entry={'action':asdict(action),'state':'pending'};record['entries'].append(entry);durable_json(journal,record)
            make_parents(dst.parent,Path(plan.target_root))
            def owned():
                entry['state']='created';durable_json(journal,record)
            copy_verified(src,dst,action.sha256,cancel,on_created=owned)
            entry['state']='copied';durable_json(journal,record)
            if action.kind=='move':
                check(cancel);verify_source(src,action,cancel)
                src.unlink()  # A SHA-256 verified second copy already exists at dst.
            entry['state']='done';durable_json(journal,record)
            if progress:progress(len(record['entries']))
        record['status']='completed'
    except Exception as exc:
        record['status']='cancelled' if isinstance(exc,Cancelled) else 'incomplete'
        record['message']=str(exc)
    finally:
        durable_json(journal,record);write_report(run,record)
    return run,record


def recovery_preview(journal,source_root,target_root):
    path=plain(journal)
    try:record=json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError) as exc:raise PilotError(f'Cannot read recovery record: {exc}') from exc
    if record.get('version')!=1 or not record.get('source_root') or not record.get('target_root') or plain(record['source_root'])!=plain(source_root) or plain(record['target_root'])!=plain(target_root):
        raise PilotError('Select the original source and destination directories before recovery.')
    record['source_root']=str(plain(record['source_root']));record['target_root']=str(plain(record['target_root']))
    result=[]
    for i,entry in enumerate(record['entries']):
        action=Action(**entry['action']);plan=Plan(record['source_root'],record['target_root'],Rules())
        src,dst=paths(plan,action)
        status='ready'
        if entry['state']=='recovered':status='already recovered'
        elif entry['state']=='pending':status='ownership uncertain; manual review'
        elif not dst.is_file():status='destination missing; manual review'
        elif digest(dst)!=action.sha256:status='destination changed or partial; manual review'
        elif action.kind=='move' and src.exists():
            status='source already present; duplicate copy will be archived' if digest(src)==action.sha256 else 'source conflict; manual review'
        if action.kind not in ('move','copy'):raise PilotError('Invalid recovery operation.')
        result.append((i,action,status))
    return record,result


def recover(journal,source_root,target_root,confirmed=False,cancel=None):
    if not confirmed:raise PilotError('Recovery requires explicit confirmation after preview.')
    journal=plain(journal);record,items=recovery_preview(journal,source_root,target_root)
    archive=journal.parent/'recovered-files'
    for i,action,status in reversed(items):
        check(cancel)
        if status not in ('ready','source already present; duplicate copy will be archived'):continue
        src,dst=paths(Plan(str(plain(source_root)),str(plain(target_root)),Rules()),action)
        if digest(dst,cancel)!=action.sha256:continue
        archive.mkdir(exist_ok=True);plain(archive)
        saved=archive/(f'{i:06d}-'+uuid.uuid4().hex[:8]+'.recovered')
        copy_verified(dst,saved,action.sha256,cancel)
        if action.kind=='move' and not src.exists():
            make_parents(src.parent,Path(source_root));copy_verified(dst,src,action.sha256,cancel)
        # Archive first; do not permanently discard any output during recovery.
        if digest(dst,cancel)!=action.sha256:raise PilotError('Destination changed during recovery; review manually.')
        dst.unlink()
        record['entries'][i]['archive_path']=str(saved.relative_to(journal.parent))
        record['entries'][i]['state']='recovered';durable_json(journal,record)
    record['status']='recovery reviewed';durable_json(journal,record);write_report(journal.parent,record)
    return journal.parent,record


def export_preview(plan,folder):
    folder=plain(folder)
    if not folder.is_dir():raise PilotError('Select an existing report folder.')
    for scope in (plain(plan.source_root),plain(plan.target_root)):
        if folder.is_relative_to(scope) or scope.is_relative_to(folder):
            raise PilotError('Report folder must be separate from source and destination.')
    run=folder/('preview-'+uuid.uuid4().hex[:10]);run.mkdir()
    durable_json(run/'plan.json',asdict(plan))
    rows=''.join(f'<tr><td>{html.escape(a.kind)}</td><td>{html.escape(a.source)}</td><td>{html.escape(a.destination)}</td></tr>' for a in plan.actions)
    groups=''.join('<li>'+html.escape(' = '.join(g))+'</li>' for g in plan.duplicates)
    notes=''.join('<li>'+html.escape(x)+'</li>' for x in plan.warnings+plan.conflicts)
    (run/'report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>FolderPilot Dry Run</title><style>body{font:16px system-ui;margin:40px;color:#19334c}td{padding:10px;border:1px solid #ccc}</style><h1>FolderPilot — Dry Run</h1><p>No source or destination files were modified.</p><table>'+rows+'</table><h2>Duplicate groups (read-only)</h2><ul>'+groups+'</ul><h2>Warnings / conflicts</h2><ul>'+notes+'</ul></html>',encoding='utf-8')
    return run


class Watcher:
    """Polling notifications only. Never execute a rule automatically."""
    def __init__(self,source,rules,callback):
        self.source=str(plain(source));self.rules=Rules(**asdict(rules));self.rules.validate()
        self.callback=callback;self.stop_event=threading.Event();self.thread=None

    def snapshot(self):
        warnings=[]
        data={str(p.relative_to(self.source)):(s.st_size,s.st_mtime_ns) for p,s in inventory(self.source,self.rules,self.stop_event,warnings)}
        return data,warnings

    def start(self):
        if self.thread and self.thread.is_alive():raise PilotError('Watcher already running.')
        self.stop_event.clear();self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()

    def _run(self):
        try:
            previous,warnings=self.snapshot();self.callback({'baseline':len(previous),'warnings':warnings})
            while not self.stop_event.wait(self.rules.watch_seconds):
                current,warnings=self.snapshot()
                changes=sorted(k for k in previous.keys()|current.keys() if previous.get(k)!=current.get(k))
                if changes or warnings:self.callback({'changed':changes,'warnings':warnings})
                previous=current
        except Cancelled:pass
        except Exception as exc:self.callback({'error':str(exc)})

    def stop(self):self.stop_event.set()
