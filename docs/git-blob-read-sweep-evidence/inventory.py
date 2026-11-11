import subprocess, ast
from pathlib import Path
files=subprocess.check_output(['git','ls-files','scripts']).decode().splitlines()
print('tracked Python/shell files:',sum(Path(f).suffix in ('.py','.sh') for f in files))
for f in files:
 if Path(f).suffix != '.py': continue
 try: tree=ast.parse(Path(f).read_text())
 except (SyntaxError,UnicodeError): continue
 for node in ast.walk(tree):
  if isinstance(node,ast.Call):
   vals=[a.value for a in ast.walk(node) if isinstance(a,ast.Constant) and a.value=='show']
   if vals and isinstance(node.func,(ast.Name,ast.Attribute)):
    # Smallest enclosing call: omit calls containing another call with the same literal.
    if any(isinstance(c,ast.Call) and c is not node and any(isinstance(v,ast.Constant) and v.value=='show' for v in ast.walk(c)) for c in ast.walk(node)): continue
    if f.endswith(('library-holdings-ledger.py','zoom-client.py')): continue
    print(f+':'+str(node.lineno),ast.unparse(node)[:155])
