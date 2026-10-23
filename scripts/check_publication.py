"""Publication checks for this source snapshot and its own Windows package.

Build-time tool, not a runtime dependency. Optional private markers are supplied
only through the local process environment and are never written to output.
"""
import argparse,hashlib,io,json,marshal,os,re,types,zipfile
from pathlib import Path

SIGNATURE=re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
PROFILE=re.compile(r'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s<>"\x00]+')
DENIED=re.compile(r'(?i)(?:^|/)(?:\.env(?:\..*)?|id_rsa|id_ed25519|S[1-9]_[^/]*REPORT\.md|audit-results\.json|manual-review\.json|[^/]*\.(?:pfx|p12|pem|key|sqlite3?|db))$')
SKIP={'.git','.venv','__pycache__','.pytest_cache','build','dist','demo-work'}
class Review:
    def __init__(self):
        self.errors=[];self.files=0;self.code_objects=0;self.zip_members=0
        values=json.loads(os.environ.get('PUBLICATION_PRIVATE_MARKERS','[]'))
        if os.name=='nt' and not os.environ.get('CI'):values.append(str(Path.home()))
        self.markers=[str(v).casefold().replace('\\','/') for v in values if len(str(v))>=6]
    def text(self,value,label,filename=False):
        normalized=value.casefold().replace('\\','/')
        if any(m in normalized or m.replace('/','//') in normalized for m in self.markers):self.errors.append(label+': private marker')
        if filename and PROFILE.search(value):self.errors.append(label+': user directory in code/source path')
    def bytes(self,data,label,source=False):
        self.files+=1
        if SIGNATURE.search(data):self.errors.append(label+': credential/private-key signature')
        self.text(data.decode('utf-8','replace'),label,source)
        if b'\0' in data[:8192]:self.text(data.decode('utf-16-le','replace'),label)
    def code(self,obj,label):
        if isinstance(obj,types.CodeType):
            self.code_objects+=1;self.text(obj.co_filename,label,True)
            for item in obj.co_consts:self.code(item,label)
        elif isinstance(obj,str):self.text(obj,label)
        elif isinstance(obj,bytes):self.bytes(obj,label)
        elif isinstance(obj,(tuple,list,frozenset)):
            for item in obj:self.code(item,label)
    def archive(self,data,label,depth=0):
        if depth>3:raise ValueError('Archive nesting exceeds review bound')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                if member.is_dir():continue
                self.zip_members+=1
                if member.file_size>100*1024**2:raise ValueError('Oversized archive member')
                name=member.filename.replace('\\','/')
                if name.startswith('/') or '..' in Path(name).parts or DENIED.search(name):self.errors.append(label+'/'+name+': disallowed member')
                payload=archive.read(member)
                self.bytes(payload,label+'/'+name,member.filename.endswith(('.py','.md','.json','.xml','.csv','.txt','.log','.ps1','.bat','.yml')))
                if name.endswith(('.zip','.xlsx')):self.archive(payload,label+'/'+name,depth+1)
                elif name.endswith('.pyc'):
                    obj=marshal.loads(payload[16:]);self.code(obj,label+'/'+name)
    def source(self,root):
        for file in root.rglob('*'):
            rel=file.relative_to(root)
            if any(p in SKIP for p in rel.parts):continue
            if file.is_symlink():self.errors.append(rel.as_posix()+': symbolic link');continue
            if not file.is_file():continue
            label=rel.as_posix()
            if DENIED.search(label):self.errors.append(label+': disallowed source file')
            data=file.read_bytes();self.bytes(data,label,file.suffix in ('.py','.md','.json','.csv','.xml','.ps1','.bat','.yml','.txt','.log'))
            if file.suffix=='.xlsx':self.archive(data,label)
            if file.suffix.lower() in ('.jpg','.jpeg') and b'Exif\0\0' in data:self.errors.append(label+': unexpected EXIF metadata')
    def package(self,folder):
        from PyInstaller.archive.readers import CArchiveReader
        for file in folder.rglob('*'):
            if not file.is_file():continue
            name=file.relative_to(folder).as_posix()
            if DENIED.search(name):self.errors.append(name+': disallowed packaged file')
            data=file.read_bytes();self.bytes(data,name)
            if file.suffix in ('.zip','.xlsx'):self.archive(data,name)
            if file.suffix=='.exe' and file.parent==folder:
                archive=CArchiveReader(str(file))
                for key,entry in archive.toc.items():
                    if entry[-1]=='z':
                        pyz=archive.open_embedded_archive(key)
                        for module in pyz.toc:self.code(pyz.extract(module),name+'/PYZ/'+module)
                    elif entry[-1]=='s':self.code(marshal.loads(archive.extract(key)),name+'/'+key)
                    else:
                        payload=archive.extract(key)
                        if isinstance(payload,bytes):self.bytes(payload,name+'/'+key)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path);parser.add_argument('--package',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    review=Review()
    if args.source:review.source(args.source)
    if args.package:review.package(args.package)
    if not (args.source or args.package):parser.error('Select an explicit source or package directory')
    result={'status':'PASS' if not review.errors else 'FAIL','files_read':review.files,'zip_members':review.zip_members,'code_objects':review.code_objects,'issues':sorted(set(review.errors)),'method':'Credential signatures, explicit local private markers, file allow-boundaries, XML/ZIP contents and recursively decoded PyInstaller Python code objects. Standard vendor runtime metadata is retained.'}
    if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    raise SystemExit(bool(review.errors))
if __name__=='__main__':main()
