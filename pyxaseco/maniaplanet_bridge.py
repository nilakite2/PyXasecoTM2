"""Temporary, controller-owned MX bridge maps for crash recovery."""

import asyncio
from pathlib import Path
import re
from uuid import uuid4

from pyxaseco.core.file_io import file_io
from pyxaseco.core.playlist import playlist
from pyxaseco.maniaplanet_runtime import ControllerError


BRIDGE_DIR = 'PyXaseco-Recovery'
DEFAULT_MX_ID = 267668
DEFAULT_MX_UID = 'A_XjtQOrBTbuiNA3d7_FwitQ5F9'


def owned_filename(value):
    return isinstance(value, str) and re.fullmatch(
        rf'{BRIDGE_DIR}/[0-9a-f]{{32}}\.Map\.Gbx', value) is not None


def _file(root, filename):
    if not owned_filename(filename):
        raise ValueError('Invalid recovery-owned map filename.')
    path = root / filename
    if (path.is_symlink() or path.is_junction() or path.parent.is_symlink() or path.parent.is_junction()
            or not path.resolve().is_relative_to(root)):
        raise ValueError('Recovery bridge file resolves outside its owned directory.')
    return path


def _file_key(value):
    return str(value or '').replace('\\', '/').casefold()


async def download_bridge(aseco, track_id, uid):
    from apps.jukebox.tmx_jobs import get_tmx_jobs

    jobs = get_tmx_jobs(aseco)
    payload = dict(jobs.payload(), kind='add', track_id=track_id, download_dir=BRIDGE_DIR)
    root = Path(payload['tracks_root']).resolve()
    token = uuid4().hex
    filename = f'{BRIDGE_DIR}/{token}.Map.Gbx'
    path = await file_io(_file, root, filename)
    prepared = None
    try:
        async with asyncio.timeout(25):
            prepared = await jobs.transport.prepare(payload, token)
            if prepared.metadata.get('uid') != uid:
                raise ControllerError('Downloaded MX bridge UID does not match the configured UID.')
            async def unlink_promoted(_result):
                await file_io(path.unlink, missing_ok=True)
            await file_io(prepared.path.rename, path, cancel_cleanup=unlink_promoted)
    finally:
        await jobs.transport.discard(prepared)
    return filename


async def discard_bridge(aseco, direct, filename):
    """Remove the rotation entry first; never unlink a current or unverified map."""
    root = Path(aseco.server.trackdir).resolve()
    path = await file_io(_file, root, filename)
    key = _file_key(filename)

    async def inactive():
        current = await direct('GetCurrentMapInfo')
        name = current.get('FileName') if isinstance(current, dict) else None
        return bool(name and _file_key(name) != key)

    if not await inactive():
        return False
    rotation = playlist(aseco)
    rows = await rotation.snapshot(refresh=True)
    if any(_file_key(row.get('FileName')) == key for row in rows):
        if await direct('RemoveMap', filename.replace('/', '\\')) is not True:
            return False
        await rotation.invalidate(aseco)
        rows = await rotation.snapshot(refresh=True)
        if any(_file_key(row.get('FileName')) == key for row in rows) or not await inactive():
            return False
    await file_io(path.unlink, missing_ok=True)
    return True
