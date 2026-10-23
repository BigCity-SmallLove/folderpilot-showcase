"""English Tk desktop UI. Preview is mandatory; watchers only notify."""
import json
import os
import queue
import sys
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog,messagebox,ttk
from .engine import Rules,PilotError,build_plan,execute,export_preview,recovery_preview,recover,Watcher

class App(tk.Tk):
    def __init__(self,demo=False):
        super().__init__();self.title('FolderPilot | Safe Windows File Automation');self.geometry('1120x790');self.minsize(960,680)
        self.events=queue.Queue();self.cancel=threading.Event();self.busy=False;self.plan=None;self.plan_key=None;self.last_run=None;self.watcher=None
        style=ttk.Style(self);style.theme_use('clam');style.configure('.',font=('Segoe UI',10));style.configure('TFrame',background='#eff4f7');style.configure('TLabel',background='#eff4f7',foreground='#18344a');style.configure('Title.TLabel',font=('Segoe UI',25,'bold'));style.configure('Accent.TButton',background='#126b79',foreground='white',padding=7);style.configure('Treeview',rowheight=25)
        outer=ttk.Frame(self,padding=20);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='FolderPilot',style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer,text='Preview every change. Keep originals protected. Recover from a verified operation record.').pack(anchor='w',pady=(0,10))
        paths=ttk.Frame(outer);paths.pack(fill='x');self.source=tk.StringVar();self.target=tk.StringVar();self.records=tk.StringVar()
        for i,(label,var) in enumerate([('Selected source folder',self.source),('Backup / sync destination',self.target),('Run records folder',self.records)]):
            ttk.Label(paths,text=label).grid(row=i,column=0,sticky='w',pady=3);ttk.Entry(paths,textvariable=var).grid(row=i,column=1,sticky='ew',padx=10)
            ttk.Button(paths,text='Browse',command=lambda v=var:self.browse(v)).grid(row=i,column=2)
        paths.columnconfigure(1,weight=1)
        self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True,pady=12)
        preview=ttk.Frame(self.tabs,padding=8);tab=ttk.Frame(self.tabs);self.tabs.add(preview,text='  Dry Run & results  ');self.tabs.add(tab,text='  Rules & monitoring  ')
        self.summary=tk.StringVar(value='Choose only the folder you want to scan, then click Preview. No automatic changes.')
        ttk.Label(preview,textvariable=self.summary,wraplength=1000).pack(anchor='w',pady=(0,8))
        holder=ttk.Frame(preview);holder.pack(fill='both',expand=True)
        self.table=ttk.Treeview(holder,columns=('op','source','target'),show='headings',height=6)
        for key,label,width in [('op','Action / status',155),('source','Source / group',350),('target','Proposed destination / details',480)]:self.table.heading(key,text=label);self.table.column(key,width=width,minwidth=90)
        ys=ttk.Scrollbar(holder,orient='vertical',command=self.table.yview);xs=ttk.Scrollbar(holder,orient='horizontal',command=self.table.xview);self.table.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
        self.table.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns');xs.grid(row=1,column=0,sticky='ew');holder.rowconfigure(0,weight=1);holder.columnconfigure(0,weight=1)
        ttk.Label(preview,text='No overwrites • Duplicate detection is read-only • Recovery archives output copies • Watchers never execute changes',wraplength=1000).pack(anchor='w',pady=8)
        canvas=tk.Canvas(tab,height=280,bg='#eff4f7',highlightthickness=0);sb=ttk.Scrollbar(tab,orient='vertical',command=canvas.yview);sb.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True);canvas.configure(yscrollcommand=sb.set)
        rules=ttk.Frame(canvas,padding=12);window=canvas.create_window((0,0),window=rules,anchor='nw');rules.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        self.vars={};defaults=Rules()
        fields=[('mode','Task',('rename','organize','duplicates','backup','sync')),('find','Find text / regex',None),('replace','Replace with',None),('prefix','Filename prefix',None),('suffix','Filename suffix (before extension)',None),('start','Numbering starts at',None),('padding','Number padding',None),('organize_by','Organize by',('type','date','size')),('extensions','Include extensions (comma-separated; blank = all)',None),('min_bytes','Minimum file size (bytes)',None),('max_bytes','Maximum bytes (0 = no limit)',None),('since','Modified since, UTC (YYYY-MM-DD)',None),('until','Modified until, UTC (YYYY-MM-DD)',None),('watch_seconds','Watch interval (seconds, 2–3600)',None)]
        for i,(key,label,choices) in enumerate(fields):
            ttk.Label(rules,text=label).grid(row=i,column=0,sticky='w',pady=3);var=tk.StringVar(value=str(getattr(defaults,key)));self.vars[key]=var
            widget=ttk.Combobox(rules,textvariable=var,values=choices,state='readonly') if choices else ttk.Entry(rules,textvariable=var)
            widget.grid(row=i,column=1,sticky='ew',padx=12)
        rules.columnconfigure(1,weight=1)
        for i,(key,label) in enumerate([('recursive','Include subfolders (links and junctions are skipped)'),('regex','Use Python regular expression for the filename stem'),('number','Add sequential numbers before the extension')],len(fields)):
            var=tk.BooleanVar(value=getattr(defaults,key));self.vars[key]=var;ttk.Checkbutton(rules,text=label,variable=var).grid(row=i,column=0,columnspan=2,sticky='w',pady=4)
        ttk.Label(rules,text='Sync is one-way and version-preserving: changed files receive .fp-HASH names; existing destination files stay untouched.',wraplength=980).grid(row=20,column=0,columnspan=2,sticky='w',pady=10)
        bar=ttk.Frame(outer);bar.pack(fill='x');self.buttons=[]
        for label,fn,accent in [('Preview (Dry Run)',self.preview,True),('Execute reviewed plan…',self.apply,False),('Save rules',self.save_rules,False),('Load rules',self.load_rules,False),('Export HTML',self.export,False),('Recover…',self.restore,False)]:
            b=ttk.Button(bar,text=label,command=fn,style='Accent.TButton' if accent else 'TButton');b.pack(side='left',padx=(0,6));self.buttons.append(b)
        watchbar=ttk.Frame(outer);watchbar.pack(fill='x',pady=10)
        ttk.Button(watchbar,text='Start watch (notify only)',command=self.start_watch).pack(side='left');ttk.Button(watchbar,text='Stop watch',command=self.stop_watch).pack(side='left',padx=6);ttk.Button(watchbar,text='Open last report folder',command=self.open_last).pack(side='left')
        self.cancel_button=ttk.Button(watchbar,text='Cancel task',command=self.cancel.set,state='disabled');self.cancel_button.pack(side='right')
        self.progress=ttk.Progressbar(watchbar,mode='indeterminate',length=150);self.progress.pack(side='right',padx=12)
        self.status=tk.StringVar(value='Ready • Dry Run is the default • No startup task or system service')
        ttk.Label(outer,textvariable=self.status,wraplength=1030).pack(anchor='w')
        self.after(100,self.poll);self.protocol('WM_DELETE_WINDOW',self.close)
        if demo:self.after(200,self.load_demo)

    def rules(self):
        data={k:v.get() for k,v in self.vars.items()}
        for key in ('min_bytes','max_bytes','start','padding','watch_seconds'):
            try:data[key]=int(data[key])
            except ValueError:raise PilotError(f'{key} must be an integer.')
        r=Rules(**data);r.validate();return r

    def fingerprint(self):return json.dumps([self.source.get(),self.target.get(),asdict(self.rules())],sort_keys=True)

    def guard(self,fn):
        try:fn()
        except Exception as exc:messagebox.showerror('FolderPilot',str(exc));self.status.set(str(exc))

    def browse(self,var):
        if self.busy:return
        path=filedialog.askdirectory()
        if path:var.set(path);self.plan=None;self.stop_watch()

    def task(self,fn,kind):
        if self.busy:return
        self.busy=True;self.cancel.clear();self.progress.start();self.cancel_button.configure(state='normal')
        for b in self.buttons:b.configure(state='disabled')
        def worker():
            try:self.events.put((kind,fn()))
            except Exception as exc:self.events.put(('error',exc))
            finally:self.events.put(('idle',None))
        threading.Thread(target=worker,daemon=True).start()

    def preview(self):
        def start():
            if not self.source.get().strip():raise PilotError('Select a source folder first.')
            cfg=self.rules();src=self.source.get();dst=self.target.get();self.plan_key=self.fingerprint();self.plan=None
            self.status.set('Scanning only the selected source. Building a read-only plan…');self.tabs.select(0)
            self.task(lambda:build_plan(src,cfg,dst,self.cancel,lambda n:self.events.put(('progress',f'Hashed {n:,} files…'))),'plan')
        self.guard(start)

    def render_plan(self,plan):
        self.table.delete(*self.table.get_children())
        for a in plan.actions[:2000]:self.table.insert('','end',values=(a.kind,a.source,a.destination))
        for i,group in enumerate(plan.duplicates,1):
            for name in group:self.table.insert('','end',values=('duplicate (read-only)',f'Group {i}',name))
        for msg in plan.conflicts:self.table.insert('','end',values=('CONFLICT','',msg))
        for msg in plan.warnings:self.table.insert('','end',values=('WARNING','',msg))
        self.summary.set(f'DRY RUN • {plan.scanned:,} selected files • {len(plan.actions):,} proposed changes • {plan.unchanged:,} unchanged • {len(plan.duplicates):,} duplicate groups • {len(plan.conflicts)} conflicts • {len(plan.warnings)} warnings')
        self.status.set('Preview complete. Review the plan before execution. Table shows up to 2,000 actions; export includes the full plan.')

    def checked_plan(self):
        if not self.plan or self.plan_key!=self.fingerprint():raise PilotError('Preview the current source, destination and rules before proceeding.')
        return self.plan

    def apply(self):
        def start():
            plan=self.checked_plan()
            if plan.rules.mode=='duplicates':raise PilotError('Duplicates are read-only; export the detection report.')
            if not plan.actions:raise PilotError('There are no changes to execute.')
            if plan.conflicts:raise PilotError('Resolve all conflicts and preview again.')
            records=self.records.get()
            if not records:raise PilotError('Select an existing run records folder.')
            if not messagebox.askyesno('Confirm file changes',f'Execute {len(plan.actions)} reviewed {plan.rules.mode} operations?\n\nSource: {plan.source_root}\nDestination: {plan.target_root}\nRecords: {records}\n\nMoves remove the source entry only after a verified copy exists. No existing destination will be overwritten. Keep the run record for recovery.',parent=self):return
            self.task(lambda:execute(plan,records,dry_run=False,confirmed=True,cancel=self.cancel,progress=lambda n:self.events.put(('progress',f'Completed {n:,} operations…'))),'done')
        self.guard(start)

    def save_rules(self):
        def save():
            rules=self.rules();p=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('Rules','*.json')])
            if p:rules.save(p);self.status.set('Rules saved. Existing rule files are never overwritten; use a new filename.')
        self.guard(save)

    def load_rules(self):
        p=filedialog.askopenfilename(filetypes=[('Rules','*.json')])
        if p:
            def load():
                rules=Rules.load(p)
                for k,v in self.vars.items():v.set(getattr(rules,k))
                self.plan=None;self.stop_watch();self.status.set('Rules loaded. Select folders and preview again.')
            self.guard(load)

    def export(self):
        def start():
            plan=self.checked_plan();folder=self.records.get()
            if not folder:raise PilotError('Choose a report / run records folder.')
            self.task(lambda:export_preview(plan,folder),'export')
        self.guard(start)

    def restore(self):
        def start():
            if not self.source.get():raise PilotError('Select the original source folder first.')
            path=filedialog.askopenfilename(title='Select an operation journal',filetypes=[('Recovery journal','*.json')])
            if not path:return
            src=self.source.get();cfg=self.rules();dst=self.target.get() if cfg.mode in ('backup','sync') else src
            self.task(lambda:(path,src,dst,recovery_preview(path,src,dst)),'recovery')
        self.guard(start)

    def start_watch(self):
        def start():
            if self.busy:raise PilotError('Wait for the current task to finish.')
            if not self.source.get():raise PilotError('Select a source folder before starting a watch.')
            self.stop_watch();self.watcher=Watcher(self.source.get(),self.rules(),lambda event:self.events.put(('watch',event)));self.watcher.start();self.status.set('Watch started. Notifications only; file operations always require a new preview and confirmation.')
        self.guard(start)

    def stop_watch(self):
        if self.watcher:self.watcher.stop();self.watcher=None

    def open_last(self):
        if self.last_run:os.startfile(self.last_run)

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='idle':
                    self.busy=False;self.progress.stop();self.cancel_button.configure(state='disabled')
                    for b in self.buttons:b.configure(state='normal')
                elif kind=='error':self.status.set(str(value));messagebox.showerror('FolderPilot',str(value))
                elif kind=='progress':self.status.set(value)
                elif kind=='plan':self.plan=value;self.render_plan(value)
                elif kind=='done':
                    self.last_run,record=value;self.plan=None;self.status.set(f'Run {record["status"]}: {len(record["entries"])} recorded operations. {record.get("message","")} HTML report and journal saved.')
                elif kind=='export':self.last_run=value;self.status.set('Dry Run HTML report and complete JSON plan exported. Source files unchanged.')
                elif kind=='watch':
                    if value.get('changed'):self.plan=None;self.status.set(f'Watch: {len(value["changed"])} file changes detected. Preview again before execution.')
                    elif value.get('error'):self.status.set('Watch stopped: '+value['error'])
                    elif 'baseline' in value:self.status.set(f'Watch active: {value["baseline"]} files. Monitoring metadata only, no automatic changes.')
                elif kind=='recovery':
                    path,src,dst,(record,items)=value
                    self.table.delete(*self.table.get_children());self.tabs.select(0)
                    for _,a,status in items:self.table.insert('','end',values=(status,a.destination,a.source))
                    # Defer until the worker idle event has restored the UI state.
                    def confirm(p=path,s=src,d=dst,entries=items):
                        if messagebox.askyesno('Confirm recovery',f'Review the recovery statuses in the table.\n\nRestore / archive eligible operations from this record?\n{p}\n\nConflicts and changed files are left for manual review. Removed output entries are preserved in recovered-files.',parent=self):
                            self.task(lambda:recover(p,s,d,confirmed=True,cancel=self.cancel),'done')
                    self.after(150,confirm)
        except queue.Empty:pass
        self.after(100,self.poll)

    def close(self):
        self.stop_watch()
        if self.busy:self.cancel.set();self.status.set('Cancelling. Keep the run journal; close after the task stops.');return
        self.destroy()

    def load_demo(self):
        from .samples import create_demo
        base=Path('demo-work');create_demo(base)
        self.source.set('demo-work/inbox');self.target.set('demo-work/backup');self.records.set('demo-work/records');self.vars['find'].set('draft');self.vars['replace'].set('final');self.vars['number'].set(True);self.preview()

def main():
    if '--self-test' in sys.argv:
        from .selftest import run
        result=run()
        if '--verification-output' in sys.argv:
            output=Path(sys.argv[sys.argv.index('--verification-output')+1])
            with output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
        return
    app=App(demo='--demo' in sys.argv)
    if '--smoke-test' in sys.argv:app.after(1200,app.destroy)
    app.mainloop()
