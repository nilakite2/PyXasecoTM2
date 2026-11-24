"""Play around known unsafe, directed ManiaPlanet map transitions."""

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
import tomllib

from pyxaseco.core.file_io import file_io
from pyxaseco.core.gbx_client import GbxError
from pyxaseco.core.playlist import playlist
from pyxaseco.maniaplanet_bridge import (
    DEFAULT_MX_ID, DEFAULT_MX_UID, discard_bridge, download_bridge, owned_filename,
)
from pyxaseco.maniaplanet_runtime import ControllerError


logger = logging.getLogger(__name__)
HANDOFF = 'PYXASECOMP_TRANSITION_HANDOFF'
ADVANCE_TIMEOUT = 45


def _uid(value):
    return value if isinstance(value, str) and 0 < len(value) <= 64 and all(
        c.isascii() and (c.isalnum() or c in '-_') for c in value
    ) else ''


def _file_key(filename):
    return filename.replace('\\', '/').casefold()


def _map(row):
    if isinstance(row, dict):
        uid = _uid(row.get('Uid') or row.get('UId'))
        filename = row.get('FileName')
        if uid and isinstance(filename, str) and filename:
            return uid, filename
    raise ControllerError('Could not verify the current or next ManiaPlanet map.')


def _launch_path(root, value):
    path = Path(value)
    if path.anchor and not path.is_absolute():
        raise ControllerError('Use a fully absolute launch path or a path relative to config.toml.')
    return (root / path).resolve()


def _auto_batch(root):
    parent = root.resolve().parent
    candidates = [parent / (parent.name + extension) for extension in ('.bat', '.cmd')]
    found = [path for path in candidates if path.is_file()]
    if len(found) != 1:
        raise ControllerError('dedicated_batch = "auto" requires exactly one .bat or .cmd named after the '
                              'parent folder; otherwise set dedicated_batch to the launcher path.')
    return found[0]


def read_config(root):
    settings = tomllib.loads((root / 'config.toml').read_text(encoding='utf-8-sig')).get('mp_recovery', {})
    if not isinstance(settings, dict):
        raise ControllerError('[mp_recovery] must be a table.')
    if settings.get('enabled') is not True:
        return None
    bridges = settings.get('bridge_uids', [])
    pairs = settings.get('unsafe_pairs', [])
    mx_id = settings.get('bridge_mx_id', DEFAULT_MX_ID)
    mx_uid = settings.get('bridge_mx_uid', DEFAULT_MX_UID)
    if type(mx_id) is not int or not 0 <= mx_id <= 2_147_483_647 or (mx_id and not _uid(mx_uid)):
        raise ControllerError('mp_recovery requires a valid bridge_mx_id and matching bridge_mx_uid.')
    if 'bridge_mx_id' in settings and mx_id not in (0, DEFAULT_MX_ID) and 'bridge_mx_uid' not in settings:
        raise ControllerError('Set bridge_mx_uid when changing the default bridge_mx_id.')
    if not isinstance(bridges, list) or not all(_uid(uid) for uid in bridges):
        raise ControllerError('mp_recovery.bridge_uids must contain map UIDs.')
    if not isinstance(pairs, list) or not all(
        isinstance(pair, list) and len(pair) == 2 and all(_uid(uid) for uid in pair)
        and pair[0] != pair[1] for pair in pairs
    ):
        raise ControllerError('mp_recovery.unsafe_pairs must contain ordered pairs of different map UIDs.')
    executable = settings.get('dedicated_executable', '')
    batch = settings.get('dedicated_batch', '')
    arguments = settings.get('dedicated_arguments', [])
    if not isinstance(executable, str) or not isinstance(batch, str) or not isinstance(arguments, list) or not all(
        isinstance(arg, str) and '\0' not in arg for arg in arguments
    ):
        raise ControllerError('Invalid dedicated executable, batch path or argument list in mp_recovery.')
    if batch:
        script = _launch_path(root, _auto_batch(root) if batch.casefold() == 'auto' else batch)
        if (not script.is_file()
                or not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_. -]*\.(?:bat|cmd)', script.name, re.IGNORECASE)):
            raise ControllerError('mp_recovery.dedicated_batch must point to an existing .bat or .cmd '
                                  'with a simple filename.')
        if arguments:
            raise ControllerError('Put launch arguments inside the dedicated batch file, not in dedicated_arguments.')
        settings['dedicated_batch'] = str(script)
        executable = executable or str(script.with_suffix('.exe'))
    if executable:
        path = _launch_path(root, executable)
        if path.suffix.casefold() != '.exe' or not path.is_file():
            raise ControllerError('mp_recovery.dedicated_executable must point to an existing Windows .exe.')
        settings['dedicated_executable'] = str(path)
    return settings


def log_event(root, scope, event, **data):
    record = {'utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'server': scope[0], 'title': scope[1], 'event': event, **data}
    try:
        with (root / 'unsafe_transitions_log.txt').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=True) + '\n')
    except OSError:
        logger.warning('Could not append to unsafe_transitions_log.txt', exc_info=True)


def _edge(source, target):
    source, target = _uid(source), _uid(target)
    return (source, target) if source and target and source != target else None


def _learned(root, scope):
    pairs = set()
    path = root / 'unsafe_transitions_log.txt'
    try:
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                # Older builds logged the first verified restart as "suspected".
                if (isinstance(row, dict) and (row.get('server'), row.get('title')) == scope
                        and row.get('event') in ('unsafe', 'suspected')):
                    edge = _edge(row.get('from_uid'), row.get('to_uid'))
                    if edge:
                        pairs.add(edge)
    except FileNotFoundError:
        pass
    return pairs


class TransitionGuard:
    def __init__(self, aseco, options, root, scope, handoff):
        self.aseco, self.options, self.root, self.scope = aseco, options, root, scope
        self.lock = asyncio.Lock()
        self.unsafe = {tuple(pair) for pair in options.get('unsafe_pairs', [])}
        self.bridge_uids = options.get('bridge_uids', [])
        self.bridge_mx_id = options.get('bridge_mx_id', DEFAULT_MX_ID)
        self.bridge_mx_uid = options.get('bridge_mx_uid', DEFAULT_MX_UID) if self.bridge_mx_id else ''
        self._bridge_retry_at = 0
        self.plan = None
        self.hold = None
        self.attempt = None
        self.disconnected_attempt = ()
        self._finishing_detour = False
        self.started_at = time.monotonic()
        self.recovery = handoff if handoff.get('scope') == list(scope) else {}
        owned = self.recovery.get('temporary_bridge')
        self.temporary_bridge = owned if owned_filename(owned) else None
        self.boot = None
        self.pid = None

    async def start(self):
        self.unsafe.update(await file_io(_learned, self.root, self.scope))
        carried = self.recovery.get('unsafe_edge')
        if isinstance(carried, list) and len(carried) == 2:
            edge = _edge(*carried)
            if edge:
                self.unsafe.add(edge)

    async def log(self, event, **data):
        await file_io(log_event, self.root, self.scope, event, **data)

    def preserves_request(self, uid):
        return bool(uid and ((self.plan and self.plan[2][0] == uid)
                             or (self.hold and self.hold[1] == uid)))

    def is_bridge(self, uid):
        return bool(self.plan and self.plan[1][0] == uid != self.plan[2][0])

    def get_attempt(self):
        if self.attempt and time.monotonic() - self.attempt[2] <= ADVANCE_TIMEOUT:
            return self.attempt[:2]
        return ()

    def handoff(self):
        data = dict(self.recovery, scope=list(self.scope))
        if self.temporary_bridge:
            data['temporary_bridge'] = self.temporary_bridge
        else:
            data.pop('temporary_bridge', None)
        if self.plan:
            source, step, target = self.plan
            if step[0] != target[0]:
                data['armed_detour'] = [source, step[0], target[0]]
            if self.disconnected_attempt or self.get_attempt() or self._finishing_detour:
                data['resume'] = target[0]
        if time.monotonic() - self.started_at >= 90:
            data.pop('launches', None)
        return data

    def unloading(self):
        if self.plan and not self.get_attempt():
            source, step, _target = self.plan
            self.attempt = (source, step[0], time.monotonic())

    async def _choose(self, direct, filename):
        await self.aseco.client.map_guard.before_rpc('ChooseNextMap', (filename,))
        if await direct('ChooseNextMap', filename) is not True:
            raise ControllerError('The dedicated server rejected the next map selection.')

    async def _erase_bridge(self, direct):
        if not self.temporary_bridge:
            return
        filename = self.temporary_bridge
        try:
            removed = await discard_bridge(self.aseco, direct, filename)
        except (ControllerError, GbxError, RuntimeError, ValueError, OSError) as error:
            await self.log('bridge_cleanup_deferred', file=filename, error=type(error).__name__)
            return
        if removed:
            self.temporary_bridge = None
            await self.log('bridge_erased', file=filename)

    async def _install_mx_bridge(self, direct, current, target):
        if time.monotonic() < self._bridge_retry_at:
            return None
        self.hold, self.plan = (current[0], target[0]), None
        # Native rotation must not reach the known unsafe target during the download.
        await self._choose(direct, current[1])
        if _map(await direct('GetNextMapInfo'))[0] != current[0]:
            raise ControllerError('Could not hold the current map while preparing the MX bridge.')
        try:
            await self._erase_bridge(direct)
            if self.temporary_bridge:
                raise ControllerError('An earlier temporary bridge could not be cleaned up.')
            filename = await download_bridge(self.aseco, self.bridge_mx_id, self.bridge_mx_uid)
            self.temporary_bridge = filename
            rpc_filename = filename.replace('/', '\\')
            if _map(await direct('GetCurrentMapInfo'))[0] != current[0]:
                raise ControllerError('The active map changed while downloading the MX bridge.')
            await self.aseco.client.map_guard.before_rpc('AddMap', (rpc_filename,))
            if await direct('AddMap', rpc_filename) is not True:
                raise ControllerError('The dedicated server did not add the temporary MX bridge.')
            await playlist(self.aseco).invalidate(self.aseco)
            if _map(await direct('GetMapInfo', rpc_filename))[0] != self.bridge_mx_uid:
                raise ControllerError('The live MX bridge has an unexpected UID.')
            await self.log('bridge_downloaded', mx_id=self.bridge_mx_id, uid=self.bridge_mx_uid, file=filename)
            return rpc_filename
        except Exception as error:
            self._bridge_retry_at = time.monotonic() + 30
            await self.log('bridge_download_failed', mx_id=self.bridge_mx_id, error=type(error).__name__)
            if not self.aseco.client.is_connected():
                raise
            await self._erase_bridge(direct)
            return None

    async def _plan(self, direct, current, target, *, select):
        source, target_uid = current[0], target[0]
        step = target
        if (source, target_uid) in self.unsafe:
            rows = await playlist(self.aseco).snapshot()
            candidates = {}
            for row in rows:
                try:
                    uid, filename = _map(row)
                except ControllerError:
                    continue
                candidates[uid] = filename
            step = None
            choices = dict.fromkeys([*self.bridge_uids, self.bridge_mx_uid])
            for bridge in choices:
                if (not bridge or bridge in (source, target_uid)
                        or (source, bridge) in self.unsafe or (bridge, target_uid) in self.unsafe):
                    continue
                filename = candidates.get(bridge)
                if not filename and bridge == self.bridge_mx_uid:
                    filename = await self._install_mx_bridge(direct, current, target)
                    if filename and _map(await direct('GetCurrentMapInfo'))[0] != source:
                        await self._erase_bridge(direct)
                        raise ControllerError('The active map changed before the MX bridge could be selected.')
                if not filename:
                    continue
                try:
                    await self._choose(direct, filename)
                    if _map(await direct('GetNextMapInfo'))[0] != bridge:
                        continue
                except (ControllerError, GbxError, ValueError, OSError):
                    if not self.aseco.client.is_connected():
                        raise
                    continue
                step = (bridge, filename)
                break
            if step is None:
                if self.hold != (source, target_uid):
                    await self.log('no_safe_bridge', from_uid=source, to_uid=target_uid)
                self.hold = (source, target_uid)
                self.plan = None
                # For native rotation retain a safe next selection as well as refusing explicit skips.
                if _map(await direct('GetCurrentMapInfo'))[0] == source:
                    await self._choose(direct, current[1])
                await self._erase_bridge(direct)
                return False
            await self.log('detour', from_uid=source, via_uid=step[0], to_uid=target_uid)
        elif select:
            await self._choose(direct, target[1])
        self.plan = (source, step, target)
        self.hold = None
        return True

    async def _prepare_next(self, direct):
        current = _map(await direct('GetCurrentMapInfo'))
        target = _map(await direct('GetNextMapInfo'))
        if self.hold and current[0] == target[0] == self.hold[0]:
            return False
        if self.plan and self.plan[0] == current[0] and self.plan[1][0] == target[0]:
            return True
        return await self._plan(direct, current, target, select=False)

    async def arm_rotation(self, direct):
        async with self.lock:
            if not self.get_attempt():
                await self._prepare_next(direct)

    async def choose(self, direct, filename):
        async with self.lock:
            if self.get_attempt():
                # End-of-race Jukebox handling may reselect the map a skip already armed.
                target_file = self.plan[2][1] if self.plan else ''
                if isinstance(filename, str) and target_file and _file_key(filename) == _file_key(target_file):
                    return True
                raise ControllerError('A map transition is already in progress.')
            current = _map(await direct('GetCurrentMapInfo'))
            target = _map(await direct('GetMapInfo', filename))
            if self.plan and current[0] == self.plan[0] and target[0] == self.plan[2][0]:
                if _map(await direct('GetNextMapInfo'))[0] == self.plan[1][0]:
                    return True
            return await self._plan(direct, current, target, select=True)

    async def advance(self, direct):
        async with self.lock:
            return await self._advance(direct)

    async def _advance(self, direct):
        if self.get_attempt():
            return False
        if not await self._prepare_next(direct):
            raise ControllerError('Unsafe map transition: no eligible bridge is in the live playlist.')
        source, step, _target = self.plan
        selected = _map(await direct('GetNextMapInfo'))[0]
        if selected != step[0]:
            await self.log('next_map_mismatch', from_uid=source, expected_uid=step[0], actual_uid=selected)
            raise ControllerError('Map skip cancelled: the dedicated server did not keep the verified next map.')
        self.attempt = (source, step[0], time.monotonic())
        try:
            accepted = await direct('NextMap')
        except GbxError as error:
            if error.code != -32300:
                self.attempt = None
            raise
        if accepted is not True:
            self.attempt = None
            raise ControllerError('The dedicated server did not accept NextMap.')
        return accepted

    async def loaded(self, direct, uid):
        async with self.lock:
            plan, self.plan = self.plan, None
            self.hold = self.attempt = None
            target = plan[2][0] if plan and plan[1][0] == uid else ''
            armed = self.recovery.pop('armed_detour', None)
            if not target and isinstance(armed, list) and len(armed) == 3:
                source, bridge, intended = armed
                if uid == bridge:
                    target = _uid(intended)
                elif uid == source and _map(await direct('GetNextMapInfo'))[0] == bridge:
                    # A reconnect before the bridge loads must not cut the current race short.
                    rows = await playlist(self.aseco).snapshot()
                    match = next((row for row in rows if (row.get('Uid') or row.get('UId')) == intended), None)
                    if match is not None:
                        self.recovery.pop('resume', None)
                        await self._plan(direct, _map(await direct('GetCurrentMapInfo')), _map(match), select=False)
                        return
            if not target:
                target = _uid(self.recovery.get('resume'))
            self.recovery.pop('resume', None)
            if uid != self.bridge_mx_uid:
                await self._erase_bridge(direct)
            if target and uid == target:
                if plan and self._finishing_detour:
                    self.recovery.pop('launches', None)
                if plan and self._finishing_detour:
                    await self.log('detour_complete', via_uid=plan[0], to_uid=uid)
            if target and target != uid:
                rows = await playlist(self.aseco).snapshot(refresh=True)
                resume = next((row for row in rows if (row.get('Uid') or row.get('UId')) == target), None)
                if not resume:
                    await self.log('target_not_in_playlist', from_uid=uid, to_uid=target)
                    return
                self._finishing_detour = self._finishing_detour or bool(plan)
                current = _map(await direct('GetCurrentMapInfo'))
                if current[0] != uid:
                    return
                if await self._plan(direct, current, _map(resume), select=True):
                    await self._advance(direct)
                return
            self._finishing_detour = False
            await self._prepare_next(direct)
