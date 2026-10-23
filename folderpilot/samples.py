"""Opt-in synthetic sample workspace; exclusive creation never replaces existing files."""
from pathlib import Path

def create_demo(base):
    base=Path(base)
    for name in ('inbox','backup','records'):(base/name).mkdir(parents=True,exist_ok=True)
    data={'invoice_draft.txt':b'Synthetic invoice 001\n','notes_draft.txt':b'Synthetic project notes\n','notes_copy.txt':b'Synthetic project notes\n','metadata_sample.json':b'{"demo":true}\n','subfolder/report_draft.csv':b'item,total\nexample,125\n'}
    for name,content in data.items():
        p=base/'inbox'/name;p.parent.mkdir(parents=True,exist_ok=True)
        try:
            with p.open('xb') as f:f.write(content)
        except FileExistsError:pass
    return base
