"""Actual Tk event-loop integration, using only a temporary synthetic workspace."""
import os,sys,tempfile,time,json
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from folderpilot.gui import App
from tkinter import messagebox
errors=[]
messagebox.showerror=lambda title,message,**kwargs:errors.append(str(message))
from folderpilot.engine import execute,recover
from folderpilot.selftest import snapshot
@contextmanager
def working_directory(path):
    previous=Path.cwd();os.chdir(path)
    try:yield
    finally:os.chdir(previous)

with tempfile.TemporaryDirectory(prefix='folderpilot-gui-') as tmp, working_directory(tmp):
    app=App(demo=True);start=time.monotonic();state={'stage':0,'ticks':0,'ok':False};original={}
    def tick():
        state['ticks']+=1
        if errors or time.monotonic()-start>90:
            print('GUI diagnostics:',state,'errors:',errors,'status:',app.status.get(),flush=True)
            app.destroy();return
        if app.plan and not app.busy and state['stage']==0:
            original.update(snapshot(Path('demo-work/inbox')))
            assert len(app.plan.actions)==5 and app.table.get_children()
            plan=app.plan;state['stage']=1
            app.task(lambda:execute(plan,'demo-work/records',False,True),'done')
        elif app.last_run and not app.busy and state['stage']==1:
            run=app.last_run;record=json.loads((run/'journal.json').read_text(encoding='utf-8'))
            assert record['status']=='completed'
            state['stage']=2;app.task(lambda:recover(run/'journal.json',str(Path('demo-work/inbox').resolve()),str(Path('demo-work/inbox').resolve()),True),'done')
        elif app.last_run and not app.busy and state['stage']==2:
            assert snapshot(Path('demo-work/inbox'))==original
            state['ok']=True;app.destroy();return
        app.after(50,tick)
    app.after(50,tick);app.mainloop()
    assert state['ok'],f'GUI preview/execute/recover did not finish: {errors}'
    print(f'GUI integration PASS: real Tk preview, worker execution and recovery; {state["ticks"]} event-loop ticks')
