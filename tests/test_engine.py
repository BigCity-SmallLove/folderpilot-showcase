import json
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path
import pytest
from folderpilot.engine import (Rules,PilotError,Cancelled,build_plan,execute,recover,recovery_preview,digest,Watcher,export_preview,safe_name)

@pytest.fixture
def area(tmp_path):
    for n in ('source','target','records'):(tmp_path/n).mkdir()
    return tuple(tmp_path/n for n in ('source','target','records'))

def put(root,name,data=b'example'):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p

def snapshot(root):return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}

def run(plan,records):return execute(plan,records,dry_run=False,confirmed=True)

def test_preview_and_default_execute_never_write(area):
    src,target,records=area;put(src,'draft.txt');before=snapshot(src.parent)
    p=build_plan(src,Rules(find='draft',replace='final'))
    result=execute(p,records)
    assert result['dry_run'] and snapshot(src.parent)==before
    with pytest.raises(PilotError,match='confirmation'):execute(p,records,dry_run=False)
    assert snapshot(src.parent)==before

def test_rename_regex_number_and_recover(area):
    src,target,records=area;put(src,'draft_2026.txt',b'abc');put(src,'sub/draft_2027.csv',b'def')
    original=snapshot(src)
    p=build_plan(src,Rules(find=r'draft_(\d+)',replace=r'report_\1',regex=True,prefix='client_',number=True,start=7,padding=3))
    assert p.actions[0].destination=='client_report_2026_007.txt'
    folder,record=run(p,records);assert record['status']=='completed'
    assert (src/'client_report_2026_007.txt').read_bytes()==b'abc'
    recover(folder/'journal.json',src,src,confirmed=True)
    assert snapshot(src)==original
    assert len(list((folder/'recovered-files').iterdir()))==2
    receipt=json.loads((folder/'journal.json').read_text(encoding='utf-8'))
    assert all((folder/e['archive_path']).is_file() for e in receipt['entries'])
    assert 'Recovery archive' in (folder/'report.html').read_text(encoding='utf-8')
    # Repeat recovery is safe and does not add another archive.
    recover(folder/'journal.json',src,src,confirmed=True)
    assert len(list((folder/'recovered-files').iterdir()))==2

@pytest.mark.parametrize('mode',['type','date','size'])
def test_organize(area,mode):
    src,target,records=area;file=put(src,'report.txt',b'x');os.utime(file,(1704067200,1704067200))
    p=build_plan(src,Rules(mode='organize',organize_by=mode));assert len(p.actions)==1
    folder,rec=run(p,records);assert rec['status']=='completed'
    dest=src/p.actions[0].destination;assert dest.stat().st_mtime_ns==1704067200000000000
    assert build_plan(src,Rules(mode='organize',organize_by=mode)).unchanged==1
    recover(folder/'journal.json',src,src,confirmed=True);assert file.read_bytes()==b'x'

def test_extension_size_date_and_recursion_filters(area):
    src,target,records=area
    a=put(src,'a.txt',b'12345');put(src,'b.csv',b'12345');put(src,'sub/c.txt',b'12345');put(src,'small.txt',b'1')
    for p in src.rglob('*'):
        if p.is_file():os.utime(p,(1704067200,1704067200))
    p=build_plan(src,Rules(prefix='ok_',extensions='txt',min_bytes=3,max_bytes=8,since='2024-01-01',until='2024-01-01',recursive=False))
    assert [a.source for a in p.actions]==['a.txt']

def test_duplicates_read_only(area):
    src,target,records=area;put(src,'a',b'x');put(src,'b',b'x');put(src,'c',b'y');before=snapshot(src.parent)
    p=build_plan(src,Rules(mode='duplicates'));assert p.duplicates==[['a','b']]
    assert snapshot(src.parent)==before
    with pytest.raises(PilotError):run(p,records)
    report=export_preview(p,records);assert 'a = b' in (report/'report.html').read_text(encoding='utf-8')
    assert snapshot(src)=={'a':b'x','b':b'x','c':b'y'}

def test_backup_verification_and_recovery_archives_copies(area):
    src,target,records=area;put(src,'a',b'x'*1024);original=snapshot(src)
    p=build_plan(src,Rules(mode='backup'),target);folder,rec=run(p,records)
    copied=target/p.actions[0].destination
    assert digest(copied)==digest(src/'a') and snapshot(src)==original
    recover(folder/'journal.json',src,target,confirmed=True)
    assert not copied.exists() and snapshot(src)==original
    assert next((folder/'recovered-files').iterdir()).read_bytes()==b'x'*1024

def test_incremental_sync_preserves_existing_data(area):
    src,target,records=area;put(src,'a.txt',b'first');p=build_plan(src,Rules(mode='sync'),target);run(p,records)
    assert build_plan(src,Rules(mode='sync'),target).unchanged==1
    put(src,'a.txt',b'updated');p=build_plan(src,Rules(mode='sync'),target)
    assert '.fp-' in p.actions[0].destination
    run(p,records);assert (target/'a.txt').read_bytes()==b'first'
    assert (target/p.actions[0].destination).read_bytes()==b'updated'
    assert build_plan(src,Rules(mode='sync'),target).unchanged==1

@pytest.mark.parametrize('kind',['existing','duplicate','case'])
def test_destination_conflicts_block_entire_execution(area,kind):
    src,target,records=area;put(src,'a.txt',b'a')
    if kind=='existing':put(src,'x_a.txt',b'other');rules=Rules(prefix='x_')
    elif kind=='duplicate':put(src,'b.txt',b'b');rules=Rules(find='[ab]',replace='same',regex=True)
    else:rules=Rules(find='a',replace='A')
    p=build_plan(src,rules)
    if kind=='case' and os.name!='nt':pytest.skip('Windows case-insensitive collision')
    assert p.conflicts;before=snapshot(src.parent)
    with pytest.raises(PilotError):run(p,records)
    assert snapshot(src.parent)==before

def test_stale_plan_and_destination_race(area):
    src,target,records=area;put(src,'a.txt');p=build_plan(src,Rules(prefix='x_'));put(src,'a.txt',b'changed')
    with pytest.raises(PilotError,match='changed'):run(p,records)
    p=build_plan(src,Rules(prefix='x_'));put(src,'x_a.txt',b'new')
    with pytest.raises(PilotError,match='conflict'):run(p,records)
    assert (src/'x_a.txt').read_bytes()==b'new'

def test_cancel_before_and_during_execution(area):
    src,target,records=area;put(src,'a');put(src,'b');p=build_plan(src,Rules(prefix='x_'));cancel=threading.Event();cancel.set()
    with pytest.raises(Cancelled):execute(p,records,False,True,cancel)
    assert not list(records.iterdir())
    cancel.clear();folder,rec=execute(p,records,False,True,cancel,lambda n:cancel.set())
    assert rec['status']=='cancelled' and len(rec['entries'])==1
    recover(folder/'journal.json',src,src,confirmed=True)
    assert snapshot(src)=={'a':b'example','b':b'example'}

def test_corrupt_copy_is_not_accepted_and_original_remains(area,monkeypatch):
    import folderpilot.engine as eng
    src,target,records=area;put(src,'a',b'original');p=build_plan(src,Rules(prefix='x_'))
    real=eng.digest
    def bad(path,cancel=None):return '0'*64 if Path(path).name=='x_a' else real(path,cancel)
    monkeypatch.setattr(eng,'digest',bad)
    folder,rec=run(p,records);assert rec['status']=='incomplete'
    assert (src/'a').read_bytes()==b'original'
    assert rec['entries'][0]['state']=='created'
    _,items=recovery_preview(folder/'journal.json',src,src)
    assert 'manual review' in items[0][2]

def test_recovery_never_overwrites_changed_original_or_destination(area):
    src,target,records=area;put(src,'a',b'original');p=build_plan(src,Rules(prefix='x_'));folder,_=run(p,records)
    put(src,'a',b'new original')
    recover(folder/'journal.json',src,src,confirmed=True)
    assert (src/'a').read_bytes()==b'new original' and (src/'x_a').exists()
    (src/'a').unlink();put(src,'x_a',b'changed destination')
    recover(folder/'journal.json',src,src,confirmed=True)
    assert (src/'x_a').read_bytes()==b'changed destination' and not (src/'a').exists()

def test_scopes_and_tampered_relative_paths_rejected(area):
    src,target,records=area;put(src,'a')
    with pytest.raises(PilotError):build_plan('',Rules())
    with pytest.raises(PilotError):build_plan(src,Rules(mode='sync'),src)
    p=build_plan(src,Rules(prefix='x_'))
    with pytest.raises(PilotError):execute(p,src,False,True)
    p.actions[0].destination='../outside'
    with pytest.raises(PilotError,match='escapes'):run(p,records)

def test_symlink_is_not_followed(area):
    src,target,records=area;outside=put(target,'private.txt',b'outside')
    try:(src/'link').symlink_to(target,target_is_directory=True)
    except OSError:pytest.skip('Windows symlink privilege unavailable')
    p=build_plan(src,Rules(mode='duplicates'))
    assert p.scanned==0 and p.warnings
    with pytest.raises(PilotError):build_plan(src/'link',Rules())

@pytest.mark.parametrize('name',['CON.txt','NUL','a/b','../escape','bad.','bad ','x:y','a'*256])
def test_windows_filename_restrictions(name):
    with pytest.raises(PilotError):safe_name(name)

@pytest.mark.parametrize('kwargs',[{'watch_seconds':1},{'max_bytes':-1},{'padding':0},{'since':'bad'},{'since':'2026-01-02','until':'2026-01-01'},{'regex':True,'find':'['},{'mode':'delete'}])
def test_invalid_rules(kwargs):
    with pytest.raises(PilotError):Rules(**kwargs).validate()

def test_rules_saved_exclusively_and_html_escapes_paths(area):
    src,target,records=area;p=records/'rules.json';r=Rules(prefix='x_');r.save(p);assert Rules.load(p)==r
    with pytest.raises(FileExistsError):r.save(p)
    put(src,'a&b.txt');plan=build_plan(src,r);report=export_preview(plan,records)
    assert 'a&amp;b' in (report/'report.html').read_text(encoding='utf-8')

def test_watcher_only_notifies_and_stops(area):
    src,target,records=area;events=[];ready=threading.Event();changed=threading.Event()
    def callback(e):
        events.append(e)
        if 'baseline' in e:ready.set()
        if e.get('changed'):changed.set()
    w=Watcher(src,Rules(watch_seconds=2),callback);w.start()
    try:
        assert ready.wait(5);put(src,'new.txt',b'new');assert changed.wait(6)
        assert snapshot(src)=={'new.txt':b'new'} and not list(records.iterdir())
    finally:w.stop();w.thread.join(5)
    assert not w.thread.is_alive()

def test_collision_after_preflight_not_owned_for_recovery(area,monkeypatch):
    import folderpilot.engine as eng
    src,target,records=area;put(src,'a');plan=build_plan(src,Rules(prefix='x_'))
    real=eng.make_parents
    def race(path,root):real(path,root);put(src,'x_a',b'example')
    monkeypatch.setattr(eng,'make_parents',race)
    folder,rec=run(plan,records)
    assert rec['status']=='incomplete' and rec['entries'][0]['state']=='pending'
    recover(folder/'journal.json',src,src,confirmed=True)
    assert (src/'x_a').read_bytes()==b'example' and (src/'a').exists()


def test_hard_links_skipped(area):
    src,target,records=area;original=put(target,'original',b'keep')
    os.link(original,src/'linked')
    plan=build_plan(src,Rules(prefix='x_'))
    assert plan.scanned==0 and plan.warnings and original.read_bytes()==b'keep'

@pytest.mark.skipif(os.name!='nt',reason='Windows junction test')
def test_windows_junction_not_scanned(area):
    import subprocess
    src,target,records=area;put(target,'outside.txt',b'not selected')
    result=subprocess.run(['cmd','/c','mklink','/J',str(src/'junction'),str(target)],capture_output=True)
    if result.returncode:pytest.skip('Junction creation unavailable')
    plan=build_plan(src,Rules(mode='duplicates'))
    assert plan.scanned==0 and plan.warnings


def test_bundled_examples_match_expected_preview():
    base=Path(__file__).resolve().parents[1]/'examples'
    expected=json.loads((base/'expected_preview.json').read_text(encoding='utf-8'))
    plan=build_plan(base/'inbox',Rules.load(base/'rename_rules.json'))
    assert len(plan.actions)==expected['fresh_demo_file_count']
    assert {a.source.replace('\\','/'):a.destination.replace('\\','/') for a in plan.actions}==expected['rename_examples']
    groups=build_plan(base/'inbox',Rules(mode='duplicates')).duplicates
    assert groups==expected['duplicate_groups']


def test_recovery_archive_names_do_not_expand_long_filenames(area):
    src,target,records=area;name='x'*80+'.txt';put(src,name,b'original bytes')
    plan=build_plan(src,Rules(prefix='new_'));folder,_=run(plan,records)
    recover(folder/'journal.json',src,src,confirmed=True)
    assert (src/name).read_bytes()==b'original bytes'
    archived=list((folder/'recovered-files').iterdir())
    assert len(archived)==1 and len(archived[0].name)<64
    assert archived[0].read_bytes()==b'original bytes'


@pytest.mark.skipif(os.name!='nt',reason='Windows short-path aliases')
def test_recovery_accepts_canonical_equivalent_windows_paths(area):
    import ctypes
    src,target,records=area;put(src,'draft.txt',b'original')
    buffer=ctypes.create_unicode_buffer(32768)
    n=ctypes.windll.kernel32.GetShortPathNameW(str(src),buffer,len(buffer))
    if not n:pytest.skip('8.3 aliases unavailable')
    short=buffer.value
    plan=build_plan(short,Rules(find='draft',replace='final'))
    assert Path(plan.source_root)==src.resolve()
    folder,record=run(plan,records)
    assert record['status']=='completed'
    recover(folder/'journal.json',src.resolve(),src.resolve(),confirmed=True)
    assert (src/'draft.txt').read_bytes()==b'original'


@pytest.mark.parametrize('location',['source','source_child','target','target_child','parent'])
def test_export_preview_rejects_overlapping_scope_without_writing(area,location):
    src,target,records=area;put(src,'sample.txt',b'unchanged')
    (src/'child').mkdir();(target/'child').mkdir()
    plan=build_plan(src,Rules(mode='sync'),target)
    candidate={'source':src,'source_child':src/'child','target':target,'target_child':target/'child','parent':src.parent}[location]
    before={str(p.relative_to(src.parent)):(p.read_bytes() if p.is_file() else None) for p in src.parent.rglob('*')}
    with pytest.raises(PilotError,match='separate'):export_preview(plan,candidate)
    after={str(p.relative_to(src.parent)):(p.read_bytes() if p.is_file() else None) for p in src.parent.rglob('*')}
    assert before==after
