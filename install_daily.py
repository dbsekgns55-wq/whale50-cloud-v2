# -*- coding: utf-8 -*-
"""Install (or remove) one Windows Scheduled Task for 09:05 local time."""
import os,sys,subprocess
from pathlib import Path
TASK='Whale50 SEC 13F Daily'
SCRIPT=str(Path(__file__).with_name('whale50.py').resolve())
if os.name!='nt':raise SystemExit('이 기능은 Windows에서 실행해야 합니다.')
if '--remove' in sys.argv:
    cmd=['schtasks','/Delete','/TN',TASK,'/F']
else:
    command='"%s" "%s" --update'%(sys.executable,SCRIPT)
    cmd=['schtasks','/Create','/F','/SC','DAILY','/ST','09:05','/TN',TASK,'/TR',command]
print('실행:',subprocess.list2cmdline(cmd))
res=subprocess.run(cmd,capture_output=True,text=True,encoding='cp949',errors='replace')
print(res.stdout,res.stderr)
if res.returncode:
    print('작업 등록/해제 실패. Windows 작업 스케줄러의 권한과 설치 경로를 확인하세요.')
    sys.exit(res.returncode)
print('등록/해제 완료. Windows 작업 스케줄러에서 확인할 수 있습니다.')
