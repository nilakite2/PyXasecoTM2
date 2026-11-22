"""Title-aware map admission and non-destructive MP playlist quarantine."""

import asyncio
from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import struct
import time
import xml.etree.ElementTree as ET

from pyxaseco.core.file_io import file_io
from pyxaseco.core.gbx_client import GbxError
from pyxaseco.management.config_store import revision, update_file
from pyxaseco.maniaplanet_callbacks import is_shootmania, server_title


logger = logging.getLogger(__name__)
EXCLUDE = 'MatchSettings.exclude.txt'
PRESET_HANDOFF = '_PYXASECOMP_ACTIVE_PRESET'
BASE_TITLES = {name.casefold(): 'TM' + name + '@nadeo'
               for name in ('Stadium', 'Canyon', 'Valley', 'Lagoon')}
MAX_HEADER = 4 * 1024 * 1024
OFFICIAL = frozenset(title.casefold() for title in BASE_TITLES.values())


class TitleMismatch(ValueError):
    pass


def title_key(value):
    value = str(value or '').strip().casefold()
    if value in {title.split('@')[0].casefold() for title in BASE_TITLES.values()}:
        value += '@nadeo'
    return value


def check_title(metadata, active_title, base_title):
    title = title_key(metadata.get('title_id'))
    environment = str(metadata.get('environment') or '').casefold()
    if is_shootmania(title, {'envir': environment}):
        raise TitleMismatch('ShootMania maps are not supported.')
    if not title:
        raise ValueError('Map titlepack could not be read; this map cannot be queued or added safely.')
    if not base_title and title in OFFICIAL and title != title_key(active_title):
        raise ValueError('The custom titlepack base game is not known yet; compatibility could not be verified.')
    if title not in {title_key(active_title), title_key(base_title)}:
        raise TitleMismatch('Map belongs to a different titlepack or base game.')
    # Official maps must also match the base game's environment.
    expected = BASE_TITLES.get(environment)
    if title in OFFICIAL and title != title_key(expected):
        raise ValueError('Map title and environment disagree; compatibility could not be verified.')


def map_identity(path):
    """Read only GBX header chunks, never the compressed map body or thumbnail."""
    with Path(path).open('rb') as stream:
        prefix = stream.read(21)
        if len(prefix) != 21 or prefix[:7] != b'GBX\x06\x00BU':
            raise ValueError('Map has an unsupported GBX header.')
        class_id, size, count = struct.unpack_from('<III', prefix, 9)
        if class_id != 0x03043000 or not 1 <= count <= 4096 or not 4 + count * 8 <= size <= MAX_HEADER:
            raise ValueError('Map has an invalid GBX header.')
        table = stream.read(count * 8)
        if len(table) != count * 8:
            raise ValueError('Map header is truncated.')
        end = 4 + count * 8
        xml = None
        for index in range(count):
            chunk, length = struct.unpack_from('<II', table, index * 8)
            length &= 0x7fffffff
            end += length
            if end > size:
                raise ValueError('Map header chunk exceeds its declared size.')
            if chunk == class_id + 5:
                if xml is not None:
                    raise ValueError('Map contains duplicate XML headers.')
                data = stream.read(length)
                start, stop = data.find(b'<header'), data.find(b'</header>')
                if len(data) != length or start < 0 or stop < start:
                    raise ValueError('Map XML header is missing or truncated.')
                xml = data[start:stop + len(b'</header>')]
            else:
                stream.seek(length, 1)
        if end != size or xml is None or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
            raise ValueError('Map XML header could not be verified.')
        root = ET.fromstring(xml)
        desc = root.find('desc')
        return {'title_id': root.get('title', ''),
                'environment': desc.get('envir', '') if desc is not None else ''}


def file_key(value):
    return str(value or '').strip().replace('\\', '/').casefold()


def local_map(root, filename):
    value = str(filename or '').strip().replace('\\', '/')
    if not value or Path(value).is_absolute() or ':' in value or '..' in value.split('/'):
        raise ValueError('Map filename must stay inside the dedicated maps directory.')
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Map is not available in the dedicated maps directory.')
    return path


def playlist_tree(raw):
    text = raw.decode('utf-8-sig')
    if len(raw) > MAX_HEADER or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('MatchSettings contains unsupported XML or exceeds 4 MiB.')
    root = ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    if root.tag != 'playlist' or root.findall('challenge'):
        raise ValueError('A ManiaPlanet map playlist is required.')
    return root


def is_time_attack_script(name):
    tail = str(name or '').strip().replace('\\', '/').rsplit('/', 1)[-1].casefold()
    return tail.removesuffix('.script.txt').endswith('timeattack')


def _ta_preset(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_HEADER + 1)
    root = playlist_tree(raw)
    infos = root.findall('gameinfos')
    if len(infos) != 1:
        raise ValueError('MatchSettings must specify one scripted Time Attack game mode.')
    scripts = infos[0].findall('script_name')
    modes = infos[0].findall('game_mode')
    if (len(scripts) != 1 or not is_time_attack_script(scripts[0].text)
            or len(modes) > 1 or (modes and (modes[0].text or '').strip() != '0')):
        raise ValueError('MatchSettings must use a Time Attack-compatible mode script.')
    if not any(file_key(item.findtext('file')) for item in root.findall('map')):
        raise ValueError('Time Attack MatchSettings must contain at least one map.')
    return raw, root


def _rotation_stamp(rows):
    return revision(json.dumps([(file_key(row.get('FileName')), row.get('UId') or row.get('Uid') or '')
                                for row in rows]).encode('utf-8'))


def xml_text(root):
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'


def archive_entries(path, entries):
    def transform(text):
        root = playlist_tree(text.encode('utf-8')) if text else ET.Element('playlist')
        if root.find('startindex') is None:
            ET.SubElement(root, 'startindex').text = '0'
        known = {file_key(item.findtext('file')) for item in root.findall('map')}
        changed = not text
        for entry in entries:
            key = file_key(entry.findtext('file'))
            if key and key not in known:
                root.append(deepcopy(entry))
                known.add(key)
                changed = True
        return xml_text(root) if changed else text
    return update_file(path, transform)


class TitleGuard:
    def __init__(self, aseco):
        self.aseco = aseco
        self.lock = asyncio.Lock()
        self.base_title = ''
        self._warned = set()
        self.blocked = set()
        self.active_preset = None

    @property
    def enabled(self):
        return getattr(self.aseco.settings, 'mp_strict_titlepacks', False) is True

    def root(self):
        directory = str(getattr(self.aseco.server, 'trackdir', '') or '')
        if not directory or not Path(directory).is_absolute():
            raise ValueError('Titlepack checks require access to the dedicated server maps directory.')
        return Path(directory).resolve()

    def policy(self):
        active = server_title(self.aseco)
        official = next((t for t in BASE_TITLES.values() if title_key(t) == title_key(active)), '')
        if not self.base_title:
            challenge = getattr(self.aseco.server, 'challenge', None)
            environment = getattr(challenge, 'environment', '') or getattr(self.aseco.server, 'packmask', '')
            self.base_title = official or BASE_TITLES.get(str(environment).casefold(), '')
        return active, official or self.base_title

    def _require(self, filename):
        check_title(map_identity(local_map(self.root(), filename)), *self.policy())

    async def require(self, filename):
        if self.enabled:
            await file_io(self._require, filename)

    def _foreign(self, filename):
        key = file_key(filename)
        try:
            self._require(filename)
            self.blocked.discard(key)
        except TitleMismatch:
            self.blocked.add(key)
            return True
        except (OSError, ValueError, ET.ParseError) as exc:
            if key not in self._warned:
                logger.warning('[Titlepack] Leaving unreadable/unverified map unchanged: %s (%s)', filename, exc)
                self._warned.add(key)
        return False

    def _settings_path(self, filename):
        value = str(filename).replace('\\', '/')
        if '/' not in value:
            value = 'MatchSettings/' + value
        path = self.root() / value
        folder = self.root() / 'MatchSettings'
        if (folder.is_symlink() or folder.is_junction() or not folder.is_dir()
                or path.is_symlink() or path.is_junction()
                or path.resolve().parent != folder or path.suffix.casefold() != '.txt'):
            raise ValueError('A regular file in the local MatchSettings directory is required.')
        if path.name.casefold() == EXCLUDE.casefold():
            raise ValueError('MatchSettings.exclude.txt is an archive, not a playable preset.')
        return path

    def require_active_preset(self):
        if self.active_preset is None:
            raise ValueError('The active MatchSettings preset is unknown. Select it with /ms or //readtracklist <file> first.')
        return self.active_preset

    def _find_preset(self, rows):
        filenames = sorted(file_key(row.get('FileName')) for row in rows)
        if not filenames or not all(filenames):
            return None
        folder = self._settings_path('MatchSettings.txt').parent
        found = None
        for path in folder.glob('*.txt'):
            try:
                _, root = _ta_preset(self._settings_path(path.name))
            except (OSError, ValueError, ET.ParseError):
                continue
            if sorted(file_key(row.findtext('file')) for row in root.findall('map')) == filenames:
                if found is not None:
                    return None
                found = path.name
        return found

    async def _session(self):
        stats = await self.aseco.client.query('GetNetworkStats')
        uptime = stats.get('Uptime') if isinstance(stats, dict) else None
        login = str(getattr(self.aseco.server, 'serverlogin', '') or '').casefold()
        if not login or type(uptime) is not int or uptime < 0:
            raise ValueError('The dedicated server session could not be verified.')
        return [login, str(self.root()).casefold(), server_title(self.aseco)], time.monotonic() - uptime

    async def preserve_preset(self, _aseco, event):
        os.environ.pop(PRESET_HANDOFF, None)
        if not event.get('restart') or not self.active_preset:
            return
        try:
            async with asyncio.timeout(5):
                identity, boot = await self._session()
                rows = await self._live()
                if rows:
                    os.environ[PRESET_HANDOFF] = json.dumps(
                        [self.active_preset, identity, boot, _rotation_stamp(rows)])
        except (GbxError, OSError, ValueError, RuntimeError) as exc:
            logger.debug('[MatchSettings] Could not verify preset for restart: %s', exc)

    async def restore_preset(self, _aseco, _event):
        handoff = os.environ.pop(PRESET_HANDOFF, None)
        try:
            rows = await self._live()
            if handoff and rows:
                try:
                    name, prior_identity, prior_boot, stamp = json.loads(handoff)
                    identity, boot = await self._session()
                    if (identity == prior_identity and abs(boot - prior_boot) <= 3
                            and _rotation_stamp(rows) == stamp):
                        path = self._settings_path(name)
                        await file_io(_ta_preset, path)
                        self.active_preset = path.name
                        self.aseco._ms_last_loaded = path.name
                        return
                except (GbxError, OSError, ValueError, TypeError, ET.ParseError) as exc:
                    logger.debug('[MatchSettings] Ignoring unusable restart preset: %s', exc)
            self.active_preset = await file_io(self._find_preset, rows)
        except (GbxError, OSError, ValueError, RuntimeError) as exc:
            logger.debug('[MatchSettings] Could not identify the live playlist: %s', exc)
        if self.active_preset is None:
            logger.warning('[MatchSettings] Active preset unknown; load the intended preset before writing it.')

    async def load(self, query, *params):
        async with self.lock:
            await self.before_rpc('LoadMatchSettings', params)
            name = self._settings_path(params[0]).name
            self.active_preset = None
            self.aseco._ms_last_loaded = ''
            result = await query('LoadMatchSettings', f'MatchSettings/{name}')
            if result is True or type(result) is int and result > 0:
                self.active_preset = name
                self.aseco._ms_last_loaded = name
            return result

    def _sanitize(self, filename, extra=(), *, require_ta=False):
        path = self._settings_path(filename)
        if require_ta:
            raw, root = _ta_preset(path)
        else:
            with path.open('rb') as stream:
                raw = stream.read(MAX_HEADER + 1)
            root = playlist_tree(raw)
        maps = root.findall('map')
        removed = [item for item in maps if self._foreign(item.findtext('file'))]
        if removed and len(removed) == len(maps):
            raise ValueError('Titlepack cleanup refused: it would empty the active MatchSettings playlist.')
        # Archive first. A later revision conflict leaves a harmless archive copy,
        # never a map entry lost from both playlists.
        archive_entries(path.with_name(EXCLUDE), [*removed, *extra])
        if not removed:
            return 0
        try:
            start = int(root.findtext('startindex') or 0)
        except ValueError:
            start = 0
        for item in removed:
            root.remove(item)
        remaining = root.findall('map')
        index = root.find('startindex')
        if index is not None:
            index.text = str(sum(item not in removed for item in maps[:max(0, start)]) % len(remaining))
        update_file(path, lambda _text: xml_text(root), expected=revision(raw))
        logger.info('[Titlepack] Archived %d foreign map entries from %s to %s', len(removed), path.name, EXCLUDE)
        return len(removed)

    async def before_rpc(self, method, params):
        if method in ('LoadMatchSettings', 'SaveMatchSettings') and params:
            name = file_key(params[0]).rsplit('/', 1)[-1].rstrip(' .')
            if name == EXCLUDE.casefold():
                raise ValueError('MatchSettings.exclude.txt is an archive, not a playable preset.')
        if method == 'SaveMatchSettings':
            self._settings_path(params[0])  # Keep the existing save-path validation.
        if method == 'LoadMatchSettings':
            if len(params) != 1 or not isinstance(params[0], str):
                raise ValueError('LoadMatchSettings requires one local preset filename.')
            if self.enabled:
                await file_io(self._sanitize, params[0], require_ta=True)
            else:
                await file_io(_ta_preset, self._settings_path(params[0]))
            return
        if not self.enabled:
            return
        if method in ('AddMap', 'InsertMap', 'ChooseNextMap'):
            await self.require(params[0])
        elif method in ('AddMapList', 'InsertMapList', 'SetNextMapList', 'SetChallengeList', 'SetMapList'):
            for item in params[0]:
                await self.require(item.get('FileName', '') if isinstance(item, dict) else item)
        elif method in ('SetNextMapIndex', 'SetNextMapIdent'):
            rows = await self._live()
            selector = params[0] if len(params) == 1 else None
            if method == 'SetNextMapIndex':
                if type(selector) is not int or not 0 <= selector < len(rows):
                    raise ValueError('Invalid next-map index.')
                row = rows[selector]
            else:
                matches = [row for row in rows if isinstance(selector, str) and selector
                           and (row.get('UId') or row.get('Uid')) == selector]
                if len(matches) != 1:
                    raise ValueError('Next-map UID does not identify one live map.')
                row = matches[0]
            await self.require(row['FileName'])

    async def after_rpc(self, method, params, result):
        if self.enabled and method == 'SaveMatchSettings' and (result is True or type(result) is int and result >= 0):
            async with self.lock:
                await file_io(self._sanitize, params[0])

    async def _live(self):
        from pyxaseco.core.playlist import playlist
        return await playlist(self.aseco).snapshot(refresh=True)

    def _verified_successor(self, rows, blocked_next):
        offset = next((i + 1 for i, row in enumerate(rows) if file_key(row.get('FileName')) == blocked_next), 0)
        for row in rows[offset:] + rows[:offset]:
            name = row.get('FileName', '')
            if file_key(name) in self.blocked:
                continue
            try:
                self._require(name)
            except (OSError, ValueError, ET.ParseError):
                continue
            return name
        return None

    async def _protect_next_map(self, rows, remaining):
        upcoming = await self.aseco.client.query('GetNextMapInfo')
        next_key = file_key(upcoming.get('FileName')) if isinstance(upcoming, dict) else ''
        if next_key not in {file_key(name) for name in remaining}:
            return
        fallback = await file_io(self._verified_successor, rows, next_key)
        if fallback and await self.aseco.client.query('ChooseNextMap', fallback) is True:
            logger.info('[Titlepack] Selected a compatible next map: %s', fallback)
        else:
            logger.warning('[Titlepack] Could not replace the incompatible upcoming map; check the live rotation.')

    async def sweep(self, _aseco=None, _event=None):
        if not self.enabled or self.active_preset is None or self.lock.locked():
            return
        async with self.lock:
            try:
                self.policy()
                rows = await self._live()
                foreign = await file_io(lambda: [r for r in rows if self._foreign(r.get('FileName', ''))])
                if foreign and len(foreign) == len(rows):
                    raise ValueError('Titlepack cleanup refused: no compatible maps would remain in the live rotation.')
                extra = []
                for row in foreign:
                    entry = ET.Element('map')
                    ET.SubElement(entry, 'file').text = row['FileName']
                    ET.SubElement(entry, 'ident').text = row.get('UId', '')
                    extra.append(entry)
                await file_io(self._sanitize, self.require_active_preset(), extra, require_ta=True)
                if 'jukebox' in getattr(self.aseco, 'active_apps', ()):
                    from apps.jukebox.backend import jukebox
                    for uid, item in list(jukebox.items()):
                        if file_key(item.get('FileName')) in self.blocked:
                            jukebox.pop(uid, None)
                            await self.aseco.release_event('onJukeboxChanged', ['drop', item])
                remaining = []
                for row in foreign:
                    name = row['FileName']
                    try:
                        if await self.aseco.client.query('RemoveMap', name) is not True:
                            remaining.append(name)
                        else:
                            logger.info('[Titlepack] Removed foreign map from live rotation: %s', name)
                    except GbxError as error:
                        remaining.append(name)
                        logger.debug('[Titlepack] Removal of %s failed: %s', name, error)
                if foreign:
                    from pyxaseco.core.playlist import playlist
                    await playlist(self.aseco).invalidate(self.aseco)
                if remaining:
                    logger.warning('[Titlepack] Cleanup incomplete: %d archived map(s) could not be removed '
                                   'from live rotation and may still be selected by native rotation: %s',
                                   len(remaining), ', '.join(remaining))
                    await self._protect_next_map(rows, remaining)
            except (GbxError, OSError, RuntimeError, ValueError, ET.ParseError) as exc:
                logger.warning('[Titlepack] Playlist cleanup not completed: %s', exc)
