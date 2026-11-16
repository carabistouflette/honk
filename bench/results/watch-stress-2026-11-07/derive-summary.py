import hashlib,json,statistics
from pathlib import Path
root=Path('.build/watch-long-final')
report=json.loads((root/'report.json').read_text())
remaining=Path('.build/watch-json-resources-final')
second=json.loads((remaining/'report.json').read_text())
handoff=json.loads(Path('.build/watch-phase-handoff.json').read_text())
if not second['complete'] or not handoff['complete']: raise SystemExit('remaining phase/handoff incomplete')
def require(value,message):
 if not value: raise SystemExit(message)
require(report['binary_sha256']==second['binary_sha256'],'binary mismatch across phases')
require(report['compiler_pin']==second['compiler_pin'],'compiler pin mismatch')
require(report['overflow_build_manifest_sha256']==second['overflow_build_manifest_sha256'],'observer build mismatch')
require(handoff['report_sha256']==hashlib.sha256((root/'report.json').read_bytes()).hexdigest(),'handoff report mismatch')
for key in ('archive_sha256','original_files','original_file_modes','canonical_stdout','adapter_manifest','projection'):
 require(report['projects']['json'][key]==second['projects']['json'][key],'JSON input/oracle mismatch: '+key)
require(second['selected_projects']==['json'] and second['selected_modes']==['resources'],'unexpected focused scope')
summary={'complete_selected_composite':True,'source_commits':[report['source_commit'],second['source_commit']],'first_report_sha256':hashlib.sha256((root/'report.json').read_bytes()).hexdigest(),'second_report_sha256':hashlib.sha256((remaining/'report.json').read_bytes()).hexdigest(),'handoff_sha256':hashlib.sha256(Path('.build/watch-phase-handoff.json').read_bytes()).hexdigest(),'sessions':{},'limits':report['limits']}
for project in report['projects']:
 for mode in ('timing','resources'):
  name=project+'-'+mode
  source=remaining if name=='json-resources' else root
  s=json.loads((source/name/'session.json').read_text())
  if not s['complete'] or s.get('forced_cleanup'):raise SystemExit('session incomplete/forced cleanup: '+name)
  starts={x['index']:x['at_ns'] for x in s['actions'] if x['kind']=='observed-command-start'}
  edits=[x for x in s['actions'] if x['kind']=='atomic-save']
  commands={x['index']:x for x in s['commands']}
  latencies=[{'command':i+2,'edit_complete_ns':x['completed_ns'],'observed_start_delta_ns':starts[i+2]-x['completed_ns'],'observed_terminal_delta_ns':commands[i+2]['observed_terminal_ns']-x['completed_ns']} for i,x in enumerate(edits)]
  cpu=s['idle_cpu']
  row={'source_run':source.name,'checked_command_intervals':len(s['commands']),'successful_intervals':sum(x['outcome']['code']==0 for x in s['commands']),'expected_failed_intervals':sum(x['outcome']['code']==1 for x in s['commands']),'idle_cpu':cpu,'idle_supervisor_cpu_percent':cpu['ticks']/cpu['hz']/(cpu['elapsed_ns']/1e9)*100,'quiescent_checkpoint_count':len(s['checkpoints']),'quiescent_fd_counts':sorted({len(x['fds']) for x in s['checkpoints']}),'steady_rss_observations_kib':s['steady_rss_observations_kib'],'atomic_save_observations':latencies,'exit_code':s['exit_code']}
  for metric in ('observed_start_delta_ns','observed_terminal_delta_ns'):
   values=[x[metric]/1e6 for x in latencies]
   row[metric.replace('_ns','_ms')]={'minimum':min(values),'median':statistics.median(values),'maximum':max(values)}
  if mode=='resources':row['observation']=s['observation']
  summary['sessions'][name]=row
projects={'diff':report['projects']['diff'],'json':second['projects']['json']}
summary['stopping_cases']={name:info['stopping_cases'] for name,info in projects.items()}
summary['real_kernel_overflow']={name:info['real_kernel_overflow'] for name,info in projects.items()}
summary['additional_checked_intervals']=0
for name,info in projects.items():
 source=root if name=='diff' else remaining
 for case in info['stopping_cases']:
  record=json.loads((source/case['folder']/'session.json').read_text())
  require(record['complete'] and not record.get('forced_cleanup'),'incomplete stopping case')
  require(record['exit_code']==(130 if case['kind']=='sigint' else 125),'stopping exit mismatch')
  summary['additional_checked_intervals']+=len(record['commands'])
 require(info['real_kernel_overflow']['result']=='observed-recovery','kernel loss evidence incomplete')
 record=json.loads((source/(name+'-overflow')/'session.json').read_text())
 require(record['complete'] and not record.get('forced_cleanup') and record['exit_code']==143,'overflow cleanup incomplete')
 summary['additional_checked_intervals']+=len(record['commands'])
summary['checked_intervals_total']=sum(x['checked_command_intervals'] for x in summary['sessions'].values())+summary['additional_checked_intervals']
Path('.build/watch-result-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
for name,row in summary['sessions'].items():
 print(name,row['checked_command_intervals'],row['idle_supervisor_cpu_percent'],row['quiescent_fd_counts'],row['steady_rss_observations_kib'],row['observed_terminal_delta_ms'])
