"""
tmxvideo.py - Port of plugins/chat.tmxvideo.php

Commands:
  /gps [help|latest|oldest|list]

Fetches TMX video links for the current track and shows them either in chat
or in a multi-page ManiaLink window.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from pyxaseco import BUILD_LABEL, PRODUCT_NAME
from pyxaseco.helpers import display_manialink, display_manialink_multi
from pyxaseco.app_services import get_tmx_service

from . import maniaplanet as mx

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

PLUGIN_VERSION = "1.0.0"
YOUTUBE_ID = re.compile(r'[A-Za-z0-9_-]{11}')
TMX_VIDEO_HOSTS_BY_PREFIX = {
    "tmnforever": "tmnf.exchange",
    "united": "tmuf.exchange",
    "nations": "nations.tm-exchange.com",
    "original": "original.tm-exchange.com",
    "sunrise": "sunrise.tm-exchange.com",
}

_current_uid: str = ""
_current_tmx_id: int = 0
_current_tmx_prefix: str = ""
_videos: list[dict] = []
_loading = False


def _tmx_service(aseco):
    return get_tmx_service(aseco)


def register(aseco: "Aseco"):
    aseco.register_event("onStartup", tmxvideo_startup)
    aseco.register_event("onNewChallenge2", tmxvideo_new_challenge)
    aseco.add_chat_command(
        "gps",
        f"Shows {_provider(aseco)} GPS/videos for the current track",
        owner="chat/tmxvideo",
        app="tmx",
        category="chat-tmx",
        usage="/gps [help|latest|oldest|list]",
        display_name="gps",
        order=356,
    )
    aseco.register_event("onChat_gps", chat_gps)


def _msg_console(aseco: "Aseco", text: str):
    aseco.console(f"[TMXVideo] {text}")


async def _msg_player(aseco: "Aseco", login: str, text: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        aseco.format_colors("{#server}> " + text),
        login,
    )


def _escape_title(title: str) -> str:
    return str(title or "").replace("$", "$$")


def _provider(aseco):
    return 'MX' if getattr(aseco, 'is_maniaplanet', False) else 'TMX'


def _video_url(aseco, video_id: str) -> str:
    scheme = 'https' if _provider(aseco) == 'MX' else 'http'
    return f'{scheme}://youtu.be/{video_id}'


def _published_sort_key(item: dict) -> float:
    raw = str(item.get("PublishedAt") or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw).timestamp()
    except Exception:
        return 0.0


def _published_label(item: dict) -> str:
    raw = str(item.get("PublishedAt") or "").strip()
    if not raw:
        return "-"
    return raw.split("T", 1)[0]


def _current_challenge(aseco: "Aseco"):
    return getattr(getattr(aseco, "server", None), "challenge", None)


async def _resolve_server_section(aseco: "Aseco") -> str:
    try:
        service = _tmx_service(aseco)
        impl = getattr(service, 'get_tmx_section', None) if service is not None else None
        return await impl(aseco) if callable(impl) else ""
    except Exception:
        try:
            game = aseco.server.get_game()
        except Exception:
            game = str(getattr(aseco.server, "game", "") or "").upper()

        if game == "TMF":
            packmask = str(getattr(aseco.server, "packmask", "") or "")
            return "TMNF" if packmask == "Stadium" else "TMU"

        return game or "TMNF"





async def _ensure_current_videos(aseco: "Aseco", challenge=None, *, force=False):
    global _current_uid, _videos, _loading
    ch = challenge or _current_challenge(aseco)
    uid = str(getattr(ch, 'uid', '') or '')
    if not uid or (not force and uid == _current_uid):
        return
    from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy
    from pyxaseco.core.external_io import request_json
    _current_uid, _videos, _loading = uid, [], True
    section = await _resolve_server_section(aseco)
    service = _tmx_service(aseco)
    is_mp = _provider(aseco) == 'MX'
    job = JobEnvelope.capture(aseco.capture_job_context(), {
        'uid': uid, 'id': int(getattr(ch, 'tmx_id', 0) or 0),
        'prefix': str(getattr(ch, 'tmx_prefix', '') or ''), 'section': section})
    async def operation(envelope):
        p = envelope.payload()
        track_id, prefix = p['id'], p['prefix']
        if not track_id or (is_mp and prefix != 'mx'):
            track_id, prefix = await service.resolve_tmx_track_id(p['uid'], p['section'])
        if not track_id:
            return 0, '', []
        host = mx.HOST if is_mp else TMX_VIDEO_HOSTS_BY_PREFIX.get(prefix, 'tmnf.exchange')
        filters = (dict(fields='LinkId,Title,PublishedAt,Map.MapId', mapid=track_id) if is_mp
                   else dict(fields='LinkId,Title,PublishedAt', trackid=track_id))
        data = await request_json(aseco, 'tmx_video', 'GET',
            f'https://{host}/api/videos?{urlencode(filters)}',
            headers={'User-Agent': f'{PRODUCT_NAME}/{BUILD_LABEL}'}, timeout=10)
        results = data.get('Results') if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise ValueError('Invalid Exchange video response.')
        rows = []
        for row in results:
            if not isinstance(row, dict) or not YOUTUBE_ID.fullmatch(str(row.get('LinkId') or '')):
                continue
            if is_mp and (not isinstance(row.get('Map'), dict) or row['Map'].get('MapId') != track_id):
                continue
            rows.append(dict(row))
        return track_id, prefix, sorted(rows, key=_published_sort_key, reverse=True)
    async def apply(result):
        global _current_tmx_id, _current_tmx_prefix, _videos, _loading, _current_uid
        _loading = False
        if result.status == 'completed':
            _current_tmx_id, _current_tmx_prefix, _videos = result.value
        else:
            _current_uid = ''  # an outage is retryable, not a cached empty list
    admitted = aseco.jobs.service('tmx_video', JobPolicy(deadline_seconds=60)).submit(
        job, operation, apply, dedupe_key='current')
    from pyxaseco.core.background_jobs import Admission
    if admitted not in (Admission.ACCEPTED, Admission.DUPLICATE):
        _current_uid, _loading = '', False


def _has_videos() -> bool:
    return bool(_videos)


async def _show_help(aseco: "Aseco", login: str):
    header = f"{{#black}}/gps <option>$g shows {_provider(aseco)} GPS/videos for the current track:"
    help_data = [
        ["...", "{#black}help", "Shows this help window"],
        ["...", "{#black}latest", "Gives the latest video in chat"],
        ["...", "{#black}oldest", "Gives the oldest video in chat"],
        ["...", "{#black}list", "Displays all videos in a window"],
    ]
    display_manialink(
        aseco,
        login,
        header,
        ["Icons64x64_1", "TrackInfo", -0.01],
        help_data,
        [1.1, 0.05, 0.3, 0.75],
        "OK",
    )


async def _send_video_in_chat(aseco: "Aseco", login: str, video: dict):
    link_id = str(video.get("LinkId") or "").strip()
    title = _escape_title(str(video.get("Title") or "").strip() or link_id)
    await _msg_player(
        aseco,
        login,
        f"Watch $l[{_video_url(aseco, link_id)}]{title}$l{{#server}} on YouTube.",
    )


async def _show_videos_window(aseco: "Aseco", player):
    challenge = _current_challenge(aseco)
    header = f"Videos for {getattr(challenge, 'name', '') or 'current track'}"

    rows: list[list[str]] = []
    for item in _videos:
        link_id = str(item.get("LinkId") or "").strip()
        title = _escape_title(str(item.get("Title") or "").strip() or link_id)
        rows.append(
            [
                "{#black}" + _published_label(item),
                f"$l[{_video_url(aseco, link_id)}]{{#black}}{title}$l",
            ]
        )

    pages = [rows[i:i + 15] for i in range(0, max(len(rows), 1), 15)]
    player.msgs = [[1, header, [1.35, 0.25, 1.10], ["Icons64x64_1", "TrackInfo"]]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


async def tmxvideo_startup(aseco: "Aseco", _param=None):
    _msg_console(aseco, f"Plugin {_provider(aseco)} Video initialized.")
    try:
        versions = getattr(aseco, "app_versions", None)
        if isinstance(versions, list):
            versions.append({"name": "app/tmx", "component": "tmxvideo", "version": PLUGIN_VERSION})
    except Exception:
        pass


async def tmxvideo_new_challenge(aseco: "Aseco", challenge):
    await _ensure_current_videos(aseco, challenge, force=True)


async def chat_gps(aseco: "Aseco", command: dict):
    player = command["author"]
    login = player.login
    params = [part for part in str(command.get("params") or "").strip().split() if part]
    subcmd = params[0].lower() if params else ""

    if subcmd == "help":
        await _show_help(aseco, login)
        return

    await _ensure_current_videos(aseco)
    if not _has_videos():
        if _loading:
            text = "Video lookup loading; try /gps shortly."
        elif not _current_uid:
            text = "{#error}Video lookup unavailable; try again shortly."
        else:
            text = "{#error}No videos found for this track."
        await _msg_player(aseco, login, text)
        return

    if subcmd == "list":
        await _show_videos_window(aseco, player)
        return
    if subcmd in ("", "latest"):
        await _send_video_in_chat(aseco, login, _videos[0])
        return
    if subcmd == "oldest":
        await _send_video_in_chat(aseco, login, _videos[-1])
        return

    await _msg_player(aseco, login, "{#error}Unknown command, use /gps help for more information.")
