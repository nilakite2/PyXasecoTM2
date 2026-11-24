"""Recover an MP controller session without treating a lost socket as a crash."""

import asyncio
from contextlib import ExitStack
import csv
import ctypes
import os
from pathlib import Path
import socket
import subprocess
import time

from pyxaseco.core.file_io import file_io
from pyxaseco.core.gbx_client import GbxAuthenticationError, GbxClient, GbxError
from pyxaseco.maniaplanet_runtime import ControllerError


def _system_tool(name):
    return Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / name


def _pids(executable):
    tasklist = _system_tool('tasklist.exe')
    result = subprocess.run([str(tasklist), '/fo', 'csv', '/nh'], capture_output=True,
                            text=True, errors='replace', check=True, timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    rows = [row for row in csv.reader(result.stdout.splitlines()) if row]
    if not rows or any(len(row) != 5 or not row[1].isdigit() for row in rows):
        raise ValueError('Could not verify dedicated process state.')
    return {int(row[1]) for row in rows if row[0].casefold() == executable.name.casefold()}


def _launched_pid(executable):
    pids = _pids(executable)
    if len(pids) != 1:
        return None
    pid = next(iter(pids))
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes = (
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong))
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(buf))
        if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            if Path(buf.value).resolve() == executable:
                return pid
    finally:
        kernel.CloseHandle(handle)
    return None


async def _boot(query):
    stats = await query('GetNetworkStats')
    uptime = stats.get('Uptime') if isinstance(stats, dict) else None
    return time.monotonic() - uptime if type(uptime) is int and uptime >= 0 else None


async def watch_dedicated(guard, client):
    try:
        guard.boot = await _boot(client.query)
    except GbxError:
        pass
    executable = guard.options.get('dedicated_executable', '')
    if executable and os.name == 'nt':
        try:
            guard.pid = await file_io(_launched_pid, Path(executable).resolve())
        except (OSError, ValueError, subprocess.SubprocessError):
            guard.pid = None
        if guard.pid is None:
            await guard.log('launch_disarmed', reason='Configured dedicated executable could not be identified.')


def _rpc_port_available(port):
    # A crashed GBX endpoint can time out rather than refuse TCP. Prove the
    # local port is free instead of treating that timeout as a launch failure.
    families = [(socket.AF_INET, ('0.0.0.0', port))]
    if socket.has_ipv6:
        families.append((socket.AF_INET6, ('::', port)))
    try:
        with ExitStack() as probes:
            for family, address in families:
                probe = probes.enter_context(socket.socket(family, socket.SOCK_STREAM))
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                if family == socket.AF_INET6:
                    probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                probe.bind(address)
    except OSError:
        return False
    return True


def _launch_if_absent(executable, arguments, endpoint, batch=None):
    try:
        if _pids(executable):
            return 'process_running'
    except (OSError, ValueError, subprocess.SubprocessError):
        return 'process_check_unavailable'
    if not _rpc_port_available(endpoint[1]):
        return 'rpc_port_not_free'
    if batch:
        # Config permits only simple filenames. Use the script's own working directory for its relative paths.
        command = [str(_system_tool('cmd.exe')), '/d', '/c', '.\\' + batch.name]
        cwd = batch.parent
    else:
        command = [str(executable), *arguments]
        cwd = executable.parent
    subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    return 'launched'


async def reconnect(guard, rpc):
    handoff = guard.handoff()
    attempt = guard.disconnected_attempt
    await guard.log('rpc_disconnected', from_uid=attempt[0] if attempt else '',
                    to_uid=attempt[1] if attempt else '', queued_uid=handoff.get('resume', ''))
    configured = guard.options.get('dedicated_executable', '')
    executable = Path(configured).resolve() if configured and os.name == 'nt' else None
    script = guard.options.get('dedicated_batch', '')
    batch = Path(script).absolute() if script else None
    may_launch = bool(executable and guard.pid is not None and handoff.get('launches', 0) < 2)
    if not may_launch:
        reason = ('No dedicated launch configured.' if not executable else
                  'Dedicated process not verified at startup.' if guard.pid is None else
                  'Automatic launch limit reached.')
        await guard.log('waiting_for_manual_recovery', reason=reason)
    launched = False
    last_launch_state = None
    delay = 2
    while True:
        client = GbxClient()
        endpoint_reached = False
        try:
            async with asyncio.timeout(12):
                await client.connect(rpc[0], rpc[1], timeout=5)
                endpoint_reached = True
                await client.authenticate(rpc[2], rpc[3])
                version = await client.query('GetVersion')
                identity = await client.query('GetSystemInfo')
                if (str(identity.get('ServerLogin', '')).casefold(),
                    str(version.get('TitleId', '')).casefold()) != guard.scope:
                    raise ControllerError('Recovery stopped: the RPC endpoint now belongs to another server or title.')
                status = await client.query('GetStatus')
                if status.get('Code') == 4:
                    try:
                        boot = await _boot(client.query)
                    except GbxError:
                        if not client.is_connected():
                            raise
                        boot = None
                    restarted = launched or (boot is not None and guard.boot is not None and boot > guard.boot + 3)
                    if restarted and len(attempt) == 2 and attempt[0] != attempt[1]:
                        await guard.log('unsafe', from_uid=attempt[0], to_uid=attempt[1],
                                        reason='Dedicated restart verified after an interrupted map transition.')
                        # Honor the pair during the immediate recovery even if the log write failed.
                        handoff['unsafe_edge'] = list(attempt)
                    if not restarted:
                        handoff.pop('resume', None)
                    else:
                        armed = handoff.pop('armed_detour', None)
                        if isinstance(armed, list) and len(armed) == 3:
                            handoff.setdefault('resume', armed[2])
                    await guard.log('rpc_reconnected', dedicated_restarted=restarted)
                    return handoff
        except GbxAuthenticationError as error:
            raise ControllerError('Recovery stopped: the dedicated server refused XML-RPC authentication.') from error
        except (OSError, GbxError, TimeoutError):
            pass
        finally:
            await client.disconnect()
        if may_launch and not endpoint_reached:
            try:
                launch_state = await file_io(_launch_if_absent, executable,
                                              guard.options.get('dedicated_arguments', []), rpc[:2], batch)
                launched = launch_state == 'launched'
                if launched:
                    may_launch = False
                    handoff['launches'] = handoff.get('launches', 0) + 1
                    await guard.log('dedicated_launched', launches=handoff['launches'],
                                    launcher=batch.name if batch else executable.name)
                elif launch_state != last_launch_state:
                    await guard.log('launch_wait', reason=launch_state)
                last_launch_state = launch_state
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                may_launch = False
                await guard.log('launch_disarmed', reason='Dedicated launch failed; waiting for manual recovery.',
                                error=type(error).__name__, winerror=getattr(error, 'winerror', None))
        await asyncio.sleep(delay)
        delay = min(15, delay * 2)
