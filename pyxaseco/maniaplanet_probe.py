"""Entry point for the ManiaPlanet probe, watcher, and test controller."""

import argparse
import asyncio
from getpass import getpass
import json
import logging
import os
from pathlib import Path
import sys
import time

from pyxaseco import BUILD_LABEL, PRODUCT_NAME
from pyxaseco.core.config import _load_dotenv
from pyxaseco.core.gbx_client import GbxAuthenticationError, GbxClient, GbxError
from pyxaseco.maniaplanet_callbacks import CallbackError, METHOD_API, enable_watch, watch
from pyxaseco.maniaplanet_records import RecordsError, db_config
from pyxaseco.maniaplanet_runtime import ControllerError
from pyxaseco.management.config_store import ManagementError, runtime_lock


DISPLAY = f'{PRODUCT_NAME} v{BUILD_LABEL}'
MP_NAMES = frozenset(('maniaplanet', 'maniaplanetserver', 'maniaplanetdedicatedserver'))


class ProbeError(ValueError):
    """The server failed a read-only compatibility check."""


async def probe(host, port, login, password, *, client=None, watch_seconds=0, emit=None, controller=None):
    if watch_seconds and not callable(emit):
        raise ProbeError('Callback watching requires an output handler.')
    rpc = client if client is not None else GbxClient()
    step = 'connecting'
    try:
        async with asyncio.timeout(15):
            await rpc.connect(host, port, timeout=5)
            step = 'authenticating'
            await rpc.authenticate(login, password)
            step = 'reading GetVersion'
            version = await rpc.query('GetVersion')
            if not isinstance(version, dict) or not isinstance(version.get('Name'), str):
                raise ProbeError('GetVersion returned an unexpected response.')
            name = ''.join(c for c in version['Name'].casefold() if c.isalnum())
            if name not in MP_NAMES:
                raise ProbeError('The server did not identify itself as ManiaPlanet. Use a separate ManiaPlanet test server.')

            step = 'reading GetStatus'
            status = await rpc.query('GetStatus')
            if not isinstance(status, dict):
                raise ProbeError('GetStatus returned an unexpected response.')
            step = 'reading GetCurrentMapInfo'
            track = await rpc.query('GetCurrentMapInfo')
            if track is not None and track is not False and not isinstance(track, dict):
                raise ProbeError('GetCurrentMapInfo returned an unexpected response.')
            report = {
                'edition': DISPLAY,
                'server': {k: version.get(k) for k in ('Name', 'TitleId', 'Version', 'Build', 'ApiVersion')},
                'status': {k: status.get(k) for k in ('Code', 'Name')},
                'map': ({'uid': track.get('Uid') or track.get('UId'), 'name': track.get('Name'),
                         'file': track.get('FileName'), 'checkpoints': track.get('NbCheckpoints')} if track else None),
            }
            if watch_seconds or controller is not None:
                step = 'enabling callbacks'
                await enable_watch(rpc, version, track)
        if controller is not None:
            step = 'running the test controller'
            await controller(rpc, report)
            return None
        if watch_seconds:
            step = 'watching callbacks'
            emit({'event': 'listening', 'seconds': watch_seconds, 'method_api': METHOD_API, **report})
            await watch(rpc, watch_seconds, emit)
            return None
        return report
    except CallbackError as error:
        raise ProbeError(str(error)) from error
    except (GbxError, OSError, TimeoutError) as error:
        if step == 'authenticating':
            if isinstance(error, OSError) or (
                isinstance(error, GbxError) and error.message.startswith('transport error -')
            ):
                raise ProbeError(f'Connection lost or timed out during XML-RPC authentication at {host}:{port}.') from error
            code = f' (RPC code {error.code})' if isinstance(error, GbxError) and type(error.code) is int else ''
            if isinstance(error, GbxAuthenticationError):
                code = ''
            raise ProbeError(
                f'XML-RPC authentication failed at {host}:{port}{code}. '
                'Check the login and password in <authorization_levels> in the active dedicated server config. '
                'Use --prompt-password to bypass the saved password.'
            ) from error
        raise ProbeError(f'Probe failed while {step} ({type(error).__name__}).') from error
    finally:
        await rpc.disconnect()


def _restart_process():
    logging.getLogger('pyxaseco').info('PyXasecoMP restart requested - re-executing the controller process')
    time.sleep(2.0)
    try:
        os.execv(sys.executable, [sys.executable, *sys.argv])
    except OSError as error:
        raise ControllerError('Could not restart the controller process. Start PyXasecoMP again manually.') from error


def main(argv=None, *, configure_logging=None, default_run=False):
    parser = argparse.ArgumentParser(description=f'{DISPLAY}: ManiaPlanet diagnostics and test controller')
    parser.add_argument('--version', action='version', version=DISPLAY)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--probe', action='store_true', help='Read server, status, and current map information')
    mode.add_argument('--watch', action='store_true', help='Enable and show callbacks on a supported MP4 title')
    mode.add_argument('--run', action='store_true', help='Run MP4 scripted Time Attack on TrackMania titles (not ShootMania)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging and controller diagnostics')
    parser.add_argument('--perf', action='store_true', help='Enable controller performance metrics')
    parser.add_argument('--import-test-records', action='store_true', help='Copy prototype PBs into the standard tables on startup')
    parser.add_argument('--seconds', type=int, help='Callback watch duration (default: 180 seconds)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--login', help='XML-RPC login (default: PYXASECOMP_RPC_LOGIN or SuperAdmin)')
    parser.add_argument('--prompt-password', action='store_true', help='Prompt even if an XML-RPC password is configured')
    args = parser.parse_args(argv)
    if default_run and not (args.probe or args.watch):
        args.run = True
    if args.seconds is not None and (not args.watch or not 1 <= args.seconds <= 900):
        parser.error('--seconds requires --watch and a duration from 1 to 900 seconds.')
    if args.import_test_records and not args.run:
        parser.error('--import-test-records requires --run.')
    if not (args.probe or args.watch or args.run):
        parser.print_help()
        return 0
    if not 1 <= args.port <= 65535 or not args.host.strip() or (args.login is not None and not args.login.strip()):
        parser.error('Provide a host, login and an XML-RPC port from 1 to 65535.')
    if args.run and args.host.casefold() not in ('localhost', '127.0.0.1', '::1'):
        parser.error('--run requires the ManiaPlanet dedicated server on the same host.')
    try:
        root = Path(__file__).resolve().parents[1]
        _load_dotenv(root / '.env')
        login = args.login or os.environ.get('PYXASECOMP_RPC_LOGIN', '').strip() or 'SuperAdmin'
        config = db_config() if args.run else None

        password = None if args.prompt_password else os.environ.get('PYXASECOMP_RPC_PASSWORD')
        password = password or getpass(f'Dedicated server XML-RPC password for {login}: ')
        if not password:
            raise ProbeError('No dedicated server XML-RPC password supplied.')
        rpc_args = args.host, args.port, login, password
        if args.run:
            from pyxaseco.maniaplanet_client import ManiaPlanetClient
            from pyxaseco.maniaplanet_controller import run_controller

            restart_requested = False

            async def run_shared(rpc, report):
                nonlocal restart_requested
                restart_requested = await run_controller(
                    rpc, report, config, rpc_args, root / 'config.toml',
                    import_records=args.import_test_records, debug=args.debug, performance=args.perf,
                )

            with runtime_lock(root):
                if configure_logging is not None:
                    configure_logging(root, debug=args.debug)
                report = asyncio.run(probe(*rpc_args, client=ManiaPlanetClient(), controller=run_shared))
            # Re-exec only after controller, RPC and instance-lock cleanup has completed.
            if restart_requested:
                _restart_process()
        else:
            report = asyncio.run(probe(*rpc_args, watch_seconds=(args.seconds or 180) if args.watch else 0,
                                       emit=lambda entry: print(json.dumps(entry), flush=True)))
    except KeyboardInterrupt:
        return 130
    except (ProbeError, RecordsError, ControllerError, ManagementError, EOFError) as error:
        print(f'{PRODUCT_NAME}: {str(error) or "No dedicated server XML-RPC password supplied."}', file=sys.stderr)
        return 1
    if report is not None:
        print(json.dumps(report, indent=2))
    return 0
