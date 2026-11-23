"""
Track info command surface for current song and mod details.

/song -> Shows current track's song filename
/mod  -> Shows current track's mod name/filename
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from typing import TYPE_CHECKING, Any

from pyxaseco.helpers import format_text, strip_colors
from pyxaseco.maniaplanet_maps import local_map, read_map_xml_header

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)


def register(aseco: 'Aseco'):
    aseco.add_chat_command(
        'song',
        "Shows filename of current track's song",
        owner='chat/songmod',
        app='platform_core',
        category='chat-track',
        usage='/song',
        display_name='song',
        order=320,
    )
    aseco.add_chat_command(
        'mod',
        "Shows (file)name of current track's mod",
        owner='chat/songmod',
        app='platform_core',
        category='chat-track',
        usage='/mod',
        display_name='mod',
        order=321,
    )
    aseco.register_event('onChat_song', chat_song)
    aseco.register_event('onChat_mod', chat_mod)


def _gbx_value(gbx: Any, *names: str):
    if gbx is None:
        return None
    for name in names:
        value = getattr(gbx, name, None)
        if value not in (None, ''):
            return value
    return None


def _first_param(command: dict) -> str:
    params = command.get('params') or ''
    if isinstance(params, str):
        parts = params.split(None, 1)
    else:
        parts = list(params) if params else []
    return str(parts[0]).lower() if parts else ''


def _has_music_command(aseco: 'Aseco') -> bool:
    try:
        return bool(aseco.get_command('music'))
    except Exception:
        return False


def _challenge_abs_path(aseco: 'Aseco') -> pathlib.Path | None:
    challenge = getattr(aseco.server, 'challenge', None)
    filename = getattr(challenge, 'filename', '') or ''
    if not filename:
        return None
    root = pathlib.Path(str(getattr(aseco.server, 'trackdir', '') or ''))
    if not root.is_absolute():
        return None
    try:
        return local_map(root.resolve(), filename)
    except (OSError, RuntimeError, ValueError):
        return None


def _parse_songmod_from_gbx(path: pathlib.Path) -> dict[str, str]:
    root = read_map_xml_header(path)
    desc = root.find('desc')
    declared_mod = desc.get('mod', '').strip() if desc is not None else ''

    song_file = ''
    song_url = ''
    mod_name = ''
    mod_file = ''
    mod_url = ''

    for dep in root.iter('dep'):
        file_attr = dep.get('file', '').strip()
        url_attr = dep.get('url', '').strip()
        norm = file_attr.replace('\\', '/').casefold()

        if not song_file and norm.startswith('challengemusics/'):
            basename = pathlib.PureWindowsPath(file_attr).name
            song_file = pathlib.PureWindowsPath(basename).stem
            song_url = url_attr

        if not mod_file and '/mod/' in '/' + norm:
            basename = pathlib.PureWindowsPath(file_attr).name
            mod_file = basename
            mod_name = declared_mod or pathlib.PureWindowsPath(basename).stem
            mod_url = url_attr

    return {
        'song_file': song_file,
        'song_url': song_url,
        'mod_name': mod_name,
        'mod_file': mod_file,
        'mod_url': mod_url,
    }


async def _get_songmod(aseco: 'Aseco', kind: str, *, with_locator: bool = False) -> dict[str, str]:
    challenge = aseco.server.challenge
    gbx = getattr(challenge, 'gbx', None)

    info = {
        'song_file': str(_gbx_value(gbx, 'song_file', 'songFile') or ''),
        'song_url': str(_gbx_value(gbx, 'song_url', 'songUrl') or ''),
        'mod_name': str(_gbx_value(gbx, 'mod_name', 'modName') or ''),
        'mod_file': str(_gbx_value(gbx, 'mod_file', 'modFile') or ''),
        'mod_url': str(_gbx_value(gbx, 'mod_url', 'modUrl') or ''),
    }
    complete = info[f'{kind}_file'] and (kind != 'mod' or info['mod_name'])
    if not complete or (with_locator and not info[f'{kind}_url']):
        try:
            path = _challenge_abs_path(aseco)
            if path:
                parsed = await asyncio.to_thread(_parse_songmod_from_gbx, path)
                info = {key: value or parsed[key] for key, value in info.items()}
        except Exception as e:
            logger.debug('[Track] GBX song/mod lookup failed: %s', e)
    if info['mod_file'] and not info['mod_name']:
        info['mod_name'] = pathlib.PureWindowsPath(info['mod_file']).stem
    return info


async def chat_song(aseco: 'Aseco', command: dict):
    player = command['author']
    challenge = aseco.server.challenge
    with_locator = _first_param(command) in ('url', 'loc')
    info = await _get_songmod(aseco, 'song', with_locator=with_locator)

    if info['song_file']:
        msg = format_text(
            aseco.get_chat_message('SONG'),
            strip_colors(challenge.name),
            info['song_file'],
        )
        if with_locator and info['song_url']:
            msg += '\n{#highlite}$l[' + info['song_url'] + ']' + info['song_url'] + '$l'
    else:
        msg = '{#server}> {#error}No track song found!'
        if getattr(aseco.server, 'get_game', lambda: '')() == 'TMF' and _has_music_command(aseco):
            msg += '  Try {#highlite}$i /music current {#error}instead.'

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(msg),
        player.login,
    )


async def chat_mod(aseco: 'Aseco', command: dict):
    player = command['author']
    challenge = aseco.server.challenge
    with_locator = _first_param(command) in ('url', 'loc')
    info = await _get_songmod(aseco, 'mod', with_locator=with_locator)

    if info['mod_name']:
        msg = format_text(
            aseco.get_chat_message('MOD'),
            strip_colors(challenge.name),
            info['mod_name'],
            info['mod_file'],
        )
        if with_locator and info['mod_url']:
            msg += '\n{#highlite}$l[' + info['mod_url'] + ']' + info['mod_url'] + '$l'
    else:
        msg = '{#server}> {#error}No track mod found!'

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(msg),
        player.login,
    )
