"""Packaged acceptance probe. Operates only inside its own temporary directory."""
import json
import tempfile
from pathlib import Path
from .engine import Rules,build_plan,execute,recover,digest
from .samples import create_demo

def snapshot(root):return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}

def run():
    with tempfile.TemporaryDirectory(prefix='folderpilot-selftest-') as tmp:
        root=create_demo(tmp);src=root/'inbox';target=root/'backup';records=root/'records';before=snapshot(src)
        plan=build_plan(src,Rules(find='draft',replace='final',number=True));assert len(plan.actions)==5
        assert execute(plan,records)['dry_run'] and snapshot(src)==before
        folder,rec=execute(plan,records,False,True);assert rec['status']=='completed'
        recover(folder/'journal.json',src,src,True);assert snapshot(src)==before
        backup=build_plan(src,Rules(mode='backup'),target);folder,rec=execute(backup,records,False,True)
        assert rec['status']=='completed'
        assert all(digest(target/a.destination)==digest(src/a.source) for a in backup.actions)
        groups=build_plan(src,Rules(mode='duplicates')).duplicates;assert len(groups)==1
        assert snapshot(src)==before
    return {'preview':'PASS','rename_and_recovery':'PASS','verified_backup':'PASS','sha256_duplicates':'PASS','scope':'temporary synthetic workspace only'}
