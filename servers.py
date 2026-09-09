"""Track running tracker instances so a launch reuses one server and Stop closes them all.

Each server records its port and shutdown token in data/servers.json. Launch checks
that registry before binding, so changing the default port can no longer leave older
copies serving stale code on the ports they were started with.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime

APP = 'cfb-tracker'
REGISTRY_NAME = 'servers.json'
# Defaults this app has shipped with. Swept so copies started before the registry
# existed, which answer no ping, are still found and closed.
LEGACY_PORTS = (8765, 8766, 8767, 8768)


def _path(data):
    return data/REGISTRY_NAME


def read(data):
    try:
        entries = json.loads(_path(data).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return entries if isinstance(entries, dict) else {}


def _write(data, entries):
    path = _path(data)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(entries, indent=2), encoding='utf-8')
    temp.replace(path)


def ping(port, timeout=1.0):
    """Identity of a tracker listening on `port`, or None for silent/foreign ports."""
    request = urllib.request.Request(f'http://127.0.0.1:{port}/api/ping', headers={'Host': f'127.0.0.1:{port}'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    return body if isinstance(body, dict) and body.get('app') == APP else None


def candidates(data, ports=(), legacy=True):
    seen = []
    for value in list(read(data))+[str(p) for p in tuple(ports)+(LEGACY_PORTS if legacy else ())]:
        try:
            port = int(value)
        except (TypeError, ValueError):
            continue
        if port not in seen:
            seen.append(port)
    return seen


def register(data, port, token):
    entries = {key: value for key, value in read(data).items()
               if key.isdigit() and key != str(port) and ping(int(key))}
    entries[str(port)] = {'pid': os.getpid(), 'token': token,
                          'started_at': datetime.now().astimezone().isoformat(timespec='seconds')}
    _write(data, entries)


def deregister(data, port):
    entries = read(data)
    if entries.pop(str(port), None) is not None:
        _write(data, entries)


def find_running(data, ports=(), legacy=True):
    """Port of the first live tracker found, or None."""
    return next((port for port in candidates(data, ports, legacy) if ping(port)), None)


def _ask_shutdown(port, token, timeout=5.0):
    request = urllib.request.Request(f'http://127.0.0.1:{port}/api/shutdown', data=b'{}',
                                     headers={'Host': f'127.0.0.1:{port}', 'Content-Type': 'application/json',
                                              'X-Tracker-Token': token})
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _run(command, timeout=30):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout or ''
    except (OSError, subprocess.SubprocessError):
        return ''


def listening_pids(port):
    pids = set()
    if os.name != 'nt':
        return pids
    for line in _run(['netstat', '-ano', '-p', 'TCP']).splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == 'LISTENING' and parts[1].rsplit(':', 1)[-1] == str(port) and parts[4].isdigit():
            pids.add(int(parts[4]))
    return pids


def is_tracker_process(pid):
    """True only when the process was started from this app's dashboard entry point."""
    if os.name != 'nt':
        return False
    command = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                    f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine'])
    return 'dashboard.py' in command.casefold()


def _force_stop(pid):
    _run(['taskkill', '/F', '/PID', str(pid)], timeout=20)
    return True


def _wait(check, attempts=10, delay=0.5):
    for _ in range(attempts):
        if check():
            return True
        time.sleep(delay)
    return check()


def stop_all(data, ports=(), report=print, legacy=True):
    """Close every tracker instance. Ports held by other software are left alone."""
    entries = read(data)
    stopped, skipped = [], []
    for port in candidates(data, ports, legacy):
        alive = ping(port)
        pids = listening_pids(port)
        if not alive and not pids:
            continue
        token = (entries.get(str(port)) or {}).get('token')
        if alive and token and _ask_shutdown(port, token) and _wait(lambda: ping(port) is None):
            report(f'Closed the tracker on port {port}.')
            stopped.append(port)
            deregister(data, port)
            continue
        ours = [pid for pid in pids if alive or is_tracker_process(pid)]
        if not ours:
            skipped.append(port)
            report(f'Port {port} is used by another program. Left it alone.')
            continue
        for pid in ours:
            _force_stop(pid)
        if _wait(lambda: not listening_pids(port)):
            report(f'Stopped the tracker on port {port}.')
            stopped.append(port)
            deregister(data, port)
        else:
            skipped.append(port)
            report(f'Could not stop the process on port {port}. Try again from an administrator prompt.')
    if not stopped and not skipped:
        report('No tracker servers were running.')
    return stopped, skipped
