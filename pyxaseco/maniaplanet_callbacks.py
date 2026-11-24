"""Bounded, console-only diagnostics for ManiaPlanet scripted callbacks."""

import asyncio
from collections import Counter
import json


METHOD_API = '2013-04-16'
SCRIPT_CALLBACK = 'maniaplanet.modescriptcallbackarray'
SCRIPT_MAP_EVENTS = {'maniaplanet.loadingmap_end': 'map_loaded',
                     'maniaplanet.unloadingmap_start': 'map_unloading'}
SCRIPT_PLAYER_EVENTS = {'trackmania.event.startline': 'race_start',
                        'trackmania.event.giveup': 'give_up', 'trackmania.event.respawn': 'respawn'}


class CallbackError(ValueError):
    """The diagnostic cannot safely watch the specified server."""


def server_title(aseco):
    report = getattr(aseco, '_mp_report', None)
    server = report.get('server', {}) if isinstance(report, dict) else {}
    title = server.get('TitleId') if isinstance(server, dict) else None
    return title if isinstance(title, str) and title else 'TMStadium@nadeo'


def is_shootmania(title, map_data=None):
    name = str(title).casefold().split('@', 1)[0]
    if name in ('smstorm', 'storm') or name.startswith('shootmania'):
        return True
    data = map_data if isinstance(map_data, dict) else {}
    environment = data.get('Environnement') or data.get('Environment') or data.get('envir') or ''
    map_type = data.get('MapType') or data.get('type') or ''
    return (str(environment).casefold() == 'storm'
            or str(map_type).casefold().startswith('shootmania'))


def _text(value):
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None


def _time(value):
    return value if type(value) is int and value >= 0 else None


def _map_fields(data):
    return {'uid': _text(data.get('uid') or data.get('Uid') or data.get('UId')),
            'name': _text(data.get('name') or data.get('Name'))}


def decode(method, params):
    """Project known events only. Never copy chat messages or raw payloads."""
    method = method.casefold()
    if method == SCRIPT_CALLBACK:
        if (len(params) != 2 or not isinstance(params[0], str) or not isinstance(params[1], list)
                or not params[1] or not isinstance(params[1][0], str) or len(params[1][0]) > 65_536):
            return None
        name = params[0].casefold()
        if (name not in ('xmlrpc.apiversion', 'trackmania.event.waypoint')
                and name not in SCRIPT_MAP_EVENTS and name not in SCRIPT_PLAYER_EVENTS):
            return None
        try:
            payload = json.loads(params[1][0])
        except (ValueError, RecursionError):
            return None
        if not isinstance(payload, dict):
            return None
        if name == 'xmlrpc.apiversion':
            return {'event': 'script_api', 'version': _text(payload.get('version'))}
        if name in SCRIPT_MAP_EVENTS:
            data = payload.get('map')
            return ({'event': SCRIPT_MAP_EVENTS[name], 'source': 'script', **_map_fields(data)}
                    if isinstance(data, dict) else None)
        login = _text(payload.get('login'))
        if login is None:
            return None
        if name in SCRIPT_PLAYER_EVENTS:
            return {'event': SCRIPT_PLAYER_EVENTS[name], 'source': 'script', 'login': login,
                    'server_time_ms': _time(payload.get('time'))}
        finished = payload.get('isendrace')
        race_time = _time(payload.get('racetime'))
        if type(finished) is not bool or race_time is None:
            return None
        result = {'event': 'finish' if finished else 'checkpoint', 'source': 'script',
                  'login': login, 'race_time_ms': race_time, 'server_time_ms': _time(payload.get('time')),
                  'checkpoint_index': _time(payload.get('checkpointinrace')),
                  'is_end_lap': payload.get('isendlap') is True}
        splits = payload.get('curracecheckpoints')
        if isinstance(splits, list) and len(splits) <= 5000 and all(_time(t) is not None for t in splits):
            result['splits_ms'] = splits
        return result

    if method in ('maniaplanet.beginmap', 'maniaplanet.endmap') and params and isinstance(params[0], dict):
        return {'event': 'map_begin' if method.endswith('beginmap') else 'map_end',
                'source': 'dedicated', **_map_fields(params[0])}
    if method == 'maniaplanet.beginmatch':
        return {'event': 'match_begin', 'source': 'dedicated'}
    if method == 'maniaplanet.endmatch':
        return {'event': 'match_end', 'source': 'dedicated',
                'rank_count': len(params[0]) if params and isinstance(params[0], list) else None}
    if method in ('maniaplanet.playerconnect', 'maniaplanet.playerdisconnect') and params and _text(params[0]):
        return {'event': 'join' if method.endswith('playerconnect') else 'leave',
                'source': 'dedicated', 'login': params[0]}
    if method == 'maniaplanet.playerchat' and len(params) >= 3 and _text(params[1]):
        return {'event': 'chat', 'source': 'dedicated', 'login': params[1]}
    if method in ('trackmania.playercheckpoint', 'trackmania.playerfinish') and len(params) >= 3 and _text(params[1]):
        race_time = _time(params[2])
        if race_time is None or race_time == 0:
            return None
        return {'event': 'finish' if method.endswith('playerfinish') else 'checkpoint',
                'source': 'legacy', 'login': params[1], 'race_time_ms': race_time}
    return None


async def enable_watch(rpc, server, map_data=None):
    if is_shootmania(server.get('TitleId', ''), map_data):
        raise CallbackError('ShootMania titles are not supported by PyXasecoMP.')
    if await rpc.query('SetApiVersion', METHOD_API) is not True:
        raise CallbackError('The dedicated server rejected the requested XML-RPC API version.')
    mode = await rpc.query('GetGameMode')
    if type(mode) is not int or mode != 0:
        raise CallbackError('Callback watching requires a scripted game mode, not a legacy mode.')
    if await rpc.query('EnableCallbacks', True) is not True:
        raise CallbackError('The dedicated server did not enable callbacks.')
    if await rpc.query('TriggerModeScriptEventArray', 'XmlRpc.EnableCallbacks', ['true']) is not True:
        raise CallbackError('The dedicated server did not queue the script callback request.')
    await rpc.query('TriggerModeScriptEventArray', 'XmlRpc.GetApiVersion', [])


async def watch(rpc, seconds, emit):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    counts = Counter()
    received = 0
    while True:
        if not rpc.is_connected():
            raise CallbackError('The dedicated server disconnected during the callback watch.')
        for method, params in rpc.get_cb_responses():
            received += 1
            entry = decode(method, params)
            if entry is not None:
                counts[f"{entry.get('source', 'script')}.{entry['event']}"] += 1
                emit(entry)
        left = deadline - loop.time()
        if left <= 0:
            break
        await asyncio.sleep(min(0.1, left))
    emit({'event': 'watch_complete', 'received': received, 'events': dict(counts)})
