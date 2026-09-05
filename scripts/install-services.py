#!/usr/bin/env python3
"""Install a persistent worker and localhost results server on the experiment host."""
import argparse
import getpass
import os
from pathlib import Path
import subprocess
import sys


def quote(value):
    if any(c in str(value) for c in '\n\r\x00'): raise ValueError('Invalid systemd value')
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


def install(name, content):
    subprocess.run(['sudo','-n','tee',f'/etc/systemd/system/{name}.service'],input=content,text=True,stdout=subprocess.DEVNULL,check=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--no-start',action='store_true');p.add_argument('--work',required=True);p.add_argument('--key-file',required=True);p.add_argument('--port',type=int,default=8830)
    args=p.parse_args();work=Path(args.work).resolve();repo=work/'maplebench';root=repo/'artifacts/batches'
    key=Path(args.key_file).resolve()
    if not key.is_file() or key.stat().st_mode & 0o077: p.error('Key file must exist and allow access only to its owner')
    if key.is_relative_to(repo) and not key.is_relative_to(repo/'private'): p.error('Keep API credentials outside source directories')
    if not 1024<=args.port<=65535: p.error('Invalid gallery port')
    user=getpass.getuser();root.mkdir(parents=True,exist_ok=True)
    node=work/'tools/node-v22.19.0-linux-arm64/bin'
    env={'MAPLEBENCH_WORK':str(work),'MAPLEBENCH_API_KEY_FILE':str(key),'MAPLEBENCH_DOCKER_COMMAND':'sudo -n docker',
         'PATH':str(node)+':/usr/local/bin:/usr/bin:/bin','PYTHONUNBUFFERED':'1'}
    worker='[Unit]\nDescription=MapleBench durable experiment worker\nAfter=network-online.target docker.service mysql.service\nWants=network-online.target\n\n[Service]\nType=simple\nUser='+user+'\nWorkingDirectory='+str(repo).replace('%','%%')+'\n'
    worker+='\n'.join('Environment='+quote(k+'='+v) for k,v in env.items())+'\n'
    worker+='ExecStart='+quote(sys.executable)+' '+quote(repo/'scripts/maplebench.py')+' worker --watch --root '+quote(root)+' --work '+quote(work)+'\nRestart=on-failure\nRestartSec=10\nKillMode=control-group\nTimeoutStopSec=10\nUMask=0077\n\n[Install]\nWantedBy=multi-user.target\n'
    gallery='[Unit]\nDescription=MapleBench local results gallery\nAfter=network.target\n\n[Service]\nUser='+user+'\nWorkingDirectory='+str(repo).replace('%','%%')+'\nExecStart='+quote(sys.executable)+' '+quote(repo/'scripts/serve-gallery.py')+' --root '+quote(root)+' --port '+str(args.port)+'\nRestart=on-failure\nRestartSec=3\nNoNewPrivileges=true\nProtectSystem=strict\nReadOnlyPaths='+quote(root)+'\nPrivateTmp=true\n\n[Install]\nWantedBy=multi-user.target\n'
    install('maplebench-worker',worker);install('maplebench-gallery',gallery)
    subprocess.run(['sudo','-n','systemctl','daemon-reload'],check=True)
    subprocess.run(['sudo','-n','systemctl','enable','maplebench-worker','maplebench-gallery'],check=True)
    subprocess.run(['sudo','-n','systemd-analyze','verify','/etc/systemd/system/maplebench-worker.service','/etc/systemd/system/maplebench-gallery.service'],check=True)
    if not args.no_start:
        subprocess.run(['sudo','-n','systemctl','restart','maplebench-worker','maplebench-gallery'],check=True)
    print('Worker installed; gallery listens on localhost:'+str(args.port))

if __name__=='__main__':main()
