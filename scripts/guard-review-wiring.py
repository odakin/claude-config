#!/usr/bin/env python3
"""Observe synthetic wiring-scope counterexamples; no policy is installed or relaxed."""
from pathlib import Path
import argparse, importlib.util, tempfile, subprocess, os, json
parser = argparse.ArgumentParser(description='Observe synthetic wiring counterexamples without changing the installed guard.')
parser.add_argument('--guard', type=Path, default=Path(__file__).resolve().with_name('agent-rule-guard.py'))
parser.add_argument('--output', type=Path)
args = parser.parse_args()
source = args.guard.resolve()
spec=importlib.util.spec_from_file_location('rule_guard', source)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
marker='agent-'+'authority'
block=(f'# {marker}:begin id=mandatory\n'
       'run python3 "$FIXTURE_DIR/manuscript-claim-guard.py" --canary\n'
       f'# {marker}:end id=mandatory\n')
prefix='set -e\nrun() { "$@"; }\n'+('# padding\n'*20)
suffix="printf '%s\\n' 'ordinary checks done'\n"
base=prefix+block+suffix
cases={
 'baseline':(base,False),
 'ordinary_message_edit':(prefix+block+suffix.replace('checks done','checks complete'),False),
 'early_exit':(prefix+'exit 0\n'+block+suffix,False),
 'early_return':(prefix+'return 0\n'+block+suffix,False),
 'shadow_runner':(prefix.replace('run() { "$@"; }','run() { :; }')+block+suffix,False),
 'shadow_interpreter':(prefix+'python3() { :; }\n'+block+suffix,False),
 'false_condition':(prefix+'if false; then\n'+block+'fi\n'+suffix,False),
 'heredoc_data':(prefix+": <<'DISABLED'\n"+block+'DISABLED\n'+suffix,False),
 'baseline_failure':(base,True),
 'mask_failure_outside':(prefix+'{\n'+block+'} || true\n'+suffix,True),
}
baseline=m.authority_regions(base,'tools/check-suite.sh')
results=[]
with tempfile.TemporaryDirectory(prefix='wiring-observe.') as t:
 root=Path(t);(root/'manuscript-claim-guard.py').write_text('import os,sys\nprint("CANARY_RAN")\nsys.exit(7 if os.environ.get("TOY_FAIL") else 0)\n')
 for name,(text,fail) in cases.items():
  p=root/(name+'.sh');p.write_text(text)
  env=dict(os.environ,FIXTURE_DIR=t,PATH=os.environ.get('PATH',''))
  if fail:env['TOY_FAIL']='1'
  else:env.pop('TOY_FAIL',None)
  run=subprocess.run(['/bin/bash','-c','source "$1"','study',str(p)],env=env,text=True,capture_output=True)
  regions=m.authority_regions(text,'tools/check-suite.sh')
  result={'case':name,'exit':run.returncode,'canary_ran':'CANARY_RAN' in run.stdout,
          'block_unchanged':regions.get('authority:mandatory')==baseline['authority:mandatory'],
          'current_wiring_changed':regions.get('authority:wiring')!=baseline['authority:wiring']}
  results.append(result)
 # A leading # in an unquoted heredoc is not a shell comment.
 p=root/'heredoc-expansion.sh';p.write_text('cat <<EOF\n# $(python3 "$FIXTURE_DIR/manuscript-claim-guard.py" --canary)\nEOF\n')
 run=subprocess.run(['/bin/bash',str(p)],env=dict(os.environ,FIXTURE_DIR=t,PATH=os.environ.get('PATH','')),text=True,capture_output=True)
 results.append({'case':'hash_inside_unquoted_heredoc','canary_ran':'CANARY_RAN' in run.stdout,'exit':run.returncode})
comment='# manuscript-claim-guard is discussed in this note\nprintf done\\n\n'
results.append({'case':'comment_only_reference','regions':sorted(m.authority_regions(comment,'tools/helper.sh')),
                'ordinary_edit_triggers_lock':m.authority_regions(comment,'tools/helper.sh')!=m.authority_regions(comment.replace('done','ready'),'tools/helper.sh')})
results.append({'case':'manifest_still_locks_without_engine_name','regions':sorted(m.authority_regions('printf done\\n\n','tools/helper.sh',['tools/helper.sh']))})
results.append({'case':'marker_addition_does_not_narrow','regions':sorted(baseline)})
if args.output:
 args.output.write_text(json.dumps(results,indent=2)+'\n')
for r in results:print(json.dumps(r))
