"""Map MP4 dedicated calls and ManiaLinks to the shared controller interface."""

import logging
from math import floor
from time import time_ns
import xml.etree.ElementTree as ET

from pyxaseco.core.gbx_client import GbxClient
from pyxaseco.maniaplanet_maps import is_time_attack_script
from pyxaseco.maniaplanet_runtime import ControllerError
from pyxaseco.models import Gameinfo


logger = logging.getLogger(__name__)
MAP_RPC = {
    'GetCurrentChallengeInfo': 'GetCurrentMapInfo',
    'GetNextChallengeInfo': 'GetNextMapInfo',
    'GetChallengeInfo': 'GetMapInfo',
    'GetChallengeList': 'GetMapList',
    'GetCurrentChallengeIndex': 'GetCurrentMapIndex',
    'GetNextChallengeIndex': 'GetNextMapIndex',
    'GetTracksDirectory': 'GetMapsDirectory',
    'CheckChallengeForCurrentServerParams': 'CheckMapForCurrentServerParams',
    'AddChallenge': 'AddMap',
    'AddChallengeList': 'AddMapList',
    'InsertChallenge': 'InsertMap',
    'InsertChallengeList': 'InsertMapList',
    'RemoveChallenge': 'RemoveMap',
    'RemoveChallengeList': 'RemoveMapList',
    'ChooseNextChallenge': 'ChooseNextMap',
    'NextChallenge': 'NextMap',
    'ChallengeRestart': 'RestartMap',
    'AllowChallengeDownload': 'AllowMapDownload',
    'IsChallengeDownloadAllowed': 'IsMapDownloadAllowed',
    'GetServerCoppers': 'GetServerPlanets',
}
MANIALINK_ARG = {'SendDisplayManialinkPage': 0, 'SendDisplayManialinkPageToLogin': 1}
TMF_SCALE_X, TMF_SCALE_Y = 2.5, 1.875  # Legacy +/-64 x +/-48 to MP4 +/-160 x +/-90.
_COLOR_ATTRIBUTES = ('bgcolor', 'bgcolorfocus', 'textcolor', 'focusareacolor1', 'focusareacolor2')
_EYEPIECE_PANEL_ACTIONS = {'91805': '91802', '91812': '91805'}  # Track overview, local records.
CPLIVE_MATCHED_PAGES = frozenset(('3', '5834290', '342312'))  # Admin, Banner, Best Finishes.
CPLIVE_BACKGROUND = ('BgsPlayerCard', 'BgCard')
_MENU_SKINS = {
    '3830000': {('Bgs1InRace', 'NavButton'): ('293745E8', '384B5EFF')},
    '3830001': {
        ('Bgs1', 'BgTitle3'): ('18212BF4', ''),
        ('BgsPlayerCard', 'BgCardSystem'): ('FFFFFF0D', '41556EFF'),
        ('BgsPlayerCard', 'BgMediaTracker'): ('CAD6E1FF', 'E4EDF5FF'),
    },
}


def map_info(data):
    if not isinstance(data, dict):
        return data
    uid = data.get('Uid') or data.get('UId')
    return dict(data, UId=uid, Uid=uid)


def _convert_legacy_page(page):
    menu_skins = _MENU_SKINS.get(page.get('id'), {})

    def collapse_window_backdrop(node):
        card = node.find('quad[@style="Bgs1InRace"][@substyle="BgCard3"][@sizen="80.4 55.7"]')
        dimmers = node.findall('quad[@bgcolor="3336"][@sizen="78.4 53.7"]')
        if card is None or not dimmers or any(
                quad.attrib.keys() & {'id', 'action', 'url', 'manialink', 'scriptevents'}
                for quad in (card, *dimmers)):
            return
        # The TMF outer skin and inner tint form one backdrop; MP's skin fills
        # the whole card and would cover any labels beneath its old depth.
        for dimmer in dimmers:
            node.remove(dimmer)
        card.attrib.pop('style')
        card.attrib.pop('substyle')
        card.set('posn', '-0.2 0.2 0')
        card.set('bgcolor', '19222DE8')

    def convert(node, formatting):
        depth = 0.0
        if position := node.attrib.pop('posn', None):
            x, y, *z = position.split()
            node.set('pos', f'{float(x) * TMF_SCALE_X:g} {float(y) * TMF_SCALE_Y:g}')
            if z:
                depth = float(z[0])
                node.set('z-index', str(floor(depth)))
        if size := node.attrib.pop('sizen', None):
            w, h = size.split()
            node.set('size', f'{float(w) * TMF_SCALE_X:g} {float(h) * TMF_SCALE_Y:g}')
        if node.tag == 'label':
            for key, value in formatting.items():
                node.attrib.setdefault(key, value)
            if menu_skins:
                node.attrib.setdefault('textcolor', 'FFFFFFFF')
        elif node.tag == 'quad':
            skin = (node.get('style'), node.get('substyle'))
            if skin in menu_skins and not node.get('image'):
                fill, focus = menu_skins[skin]
                node.attrib.pop('style')
                node.attrib.pop('substyle')
                node.set('bgcolor', fill)
                if focus and node.get('action'):
                    node.set('bgcolorfocus', focus)
        for key in _COLOR_ATTRIBUTES:
            color = node.get(key, '')
            if len(color) == 4 and all(char in '0123456789abcdefABCDEF' for char in color):
                node.set(key, ''.join(char * 2 for char in color).upper())

        local = dict(formatting)
        layers = []
        passive_quads = set()
        if node.tag == 'frame':
            collapse_window_backdrop(node)
        for child in list(node):
            if child.tag == 'format':
                local.update(child.attrib)
                node.remove(child)
                continue
            if child.tag == 'quad' and not child.attrib.keys() & {'id', 'action', 'url', 'manialink', 'scriptevents'}:
                signature = frozenset(child.attrib.items())
                if signature in passive_quads:
                    node.remove(child)
                    continue
                passive_quads.add(signature)
            child_depth = convert(child, local)
            if child.tag in ('frame', 'quad', 'label', 'entry', 'frameinstance'):
                layers.append((child_depth, child))

        if layers:
            # MP4 orders whole sibling frames. Anchor each to its lowest drawn
            # child, then resolve fractional depths and ties deterministically.
            ordered = sorted(layers, key=lambda layer: layer[0])
            # Preserve a lone top-level frame's cross-page depth.
            if node.tag != 'manialink' or len(layers) > 1:
                z = floor(ordered[0][0])
                for child_depth, child in ordered:
                    z = max(floor(child_depth), z)
                    if len(layers) > 1 or child.get('z-index') is not None or z:
                        child.set('z-index', str(z))
                    z += 1
            if node.tag == 'frame':
                depth += ordered[0][0]
        return depth

    convert(page, {})
    action = _EYEPIECE_PANEL_ACTIONS.get(page.get('id'))
    frame = page.find('frame')
    if action is not None and frame is not None:
        backdrop = frame.find(f'quad[@action="{action}"]')
        if backdrop is not None and 'pos' in backdrop.attrib and 'size' in backdrop.attrib:
            # Keep the configured Eyepiece skin passive. MP's full-card target
            # must sit in front of the title and rows to receive their clicks.
            backdrop.attrib.pop('action')
            attrs = {key: backdrop.attrib[key] for key in ('pos', 'size', 'halign', 'valign')
                     if key in backdrop.attrib}
            depth = max(int(child.get('z-index', '0')) for child in frame)
            ET.SubElement(frame, 'quad', attrs, action=action, bgcolor='FFFFFF01',
                          bgcolorfocus='FFFFFF16', **{'z-index': str(depth + 1)})


def legacy_manialinks(xml):
    """Convert legacy window geometry and inherited label formatting to MP4."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        # Shared HUD code also emits batches of sibling page fragments.
        if error.code != 9 or not xml.lstrip().startswith('<manialink '):
            raise
        root = ET.fromstring(f'<manialinks>{xml}</manialinks>')
        xml = ET.tostring(root, encoding='unicode')

    changed = False
    for page in root.iter('manialink'):
        if page.get('id') == '1928379':
            for node in page.iter('quad'):
                if not node.get('action') or node.get('image'):
                    continue
                if (node.get('substyle') != 'NavButton' and node.get('sizen') != '21 1.8'
                        and node.get('size') != '52.5 3.375'):
                    continue
                # Apply after personal styling too: retain its row tint, but
                # never inherit MP's opaque spectator-selection background.
                tint = node.get('bgcolor', '00000040')
                if len(tint) == 4:
                    tint = ''.join(char * 2 for char in tint)
                node.attrib.pop('style', None)
                node.attrib.pop('substyle', None)
                node.set('bgcolor', tint[:6] + '40' if len(tint) == 8 else '00000040')
                node.set('bgcolorfocus', 'FFFFFF24')
                changed = True
        if page.get('id') in CPLIVE_MATCHED_PAGES:
            for node in page.iter('quad'):
                if not node.get('style', '').startswith('Bgs') or node.get('image'):
                    continue
                if (node.get('style'), node.get('substyle')) != CPLIVE_BACKGROUND:
                    node.set('style', CPLIVE_BACKGROUND[0])
                    node.set('substyle', CPLIVE_BACKGROUND[1])
                    changed = True
        if page.get('version') != '3':
            page.set('version', '3')
            _convert_legacy_page(page)
            changed = True
        for label in page.iter('label'):
            # Standard body text, not the outer frame's personal HUD density.
            # Keep deliberately small captions and nickname formatting intact.
            if label.get('scale') in ('0.8', '0.80', '0.9', '0.90'):
                label.set('scale', '1')
                changed = True
    return ET.tostring(root, encoding='unicode') if changed else xml


def _manialink_args(method, params):
    slot = MANIALINK_ARG.get(method)
    if slot is None or len(params) <= slot or not isinstance(params[slot], str):
        return params
    try:
        xml = legacy_manialinks(params[slot])
    except (ET.ParseError, ValueError, OverflowError):
        logger.warning('Skipped a ManiaLink with invalid XML or geometry.')
        return None
    return (*params[:slot], xml, *params[slot + 1:])


class ManiaPlanetClient(GbxClient):
    # Validation-replay base64 replies can exceed TMF's 4 MiB packet ceiling.
    max_packet_size = 40 * 1024 * 1024

    async def query(self, method, *params):
        mapped = MAP_RPC.get(method, method)
        guard = getattr(self, 'map_guard', None)
        if guard is not None:
            if mapped == 'LoadMatchSettings':
                return await guard.load(super().query, *params)
            await guard.before_rpc(mapped, params)
        if method == 'ForceEndRound':
            return await super().query('TriggerModeScriptEventArray', 'Trackmania.ForceEndRound', [str(time_ns())])
        if method == 'SetChallengeList':
            return await self._reorder_maps(*params)
        if method in ('GetDisableRespawn', 'SetDisableRespawn'):
            settings = await self.time_attack_settings()
            if type(settings.get('S_AllowRespawn')) is not bool:
                raise ControllerError('The active script does not expose S_AllowRespawn.')
            if method == 'GetDisableRespawn':
                return not settings['S_AllowRespawn']
            if len(params) != 1 or type(params[0]) is not bool:
                raise ValueError('DisableRespawn requires a boolean.')
            return await super().query('SetModeScriptSettings', {'S_AllowRespawn': not params[0]})
        if method == 'GetServerPackMask':
            current = await super().query('GetCurrentMapInfo')
            if isinstance(current, dict):
                return current.get('Environnement') or current.get('Environment') or ''
            return ''
        if method in ('GetCurrentGameInfo', 'GetNextGameInfo', 'GetTimeAttackLimit'):
            settings = await self.time_attack_settings()
            limit = settings.get('S_TimeLimit', 0)
            limit_ms = limit * 1000 if type(limit) is int else 0
            if method == 'GetTimeAttackLimit':
                return {'CurrentValue': limit_ms, 'NextValue': limit_ms}
            info = await super().query(method, *params)
            info = dict(info) if isinstance(info, dict) else {}
            info.update(GameMode=Gameinfo.TA, TimeAttackLimit=limit_ms)
            if type(settings.get('S_AllowRespawn')) is bool:
                info['DisableRespawn'] = not settings['S_AllowRespawn']
            return info
        args = _manialink_args(mapped, params)
        if args is None:
            return False
        result = await super().query(mapped, *args)
        if guard is not None:
            await guard.after_rpc(mapped, args, result)
        if mapped in ('GetMapInfo', 'GetCurrentMapInfo', 'GetNextMapInfo'):
            return map_info(result)
        if mapped == 'GetMapList' and isinstance(result, list):
            return [map_info(row) for row in result]
        return result

    async def query_ignore_result(self, method, *params):
        mapped = MAP_RPC.get(method, method)
        if getattr(self, 'map_guard', None) is not None and mapped in (
                'AddMap', 'InsertMap', 'ChooseNextMap', 'AddMapList', 'InsertMapList',
                'SetNextMapList', 'SetNextMapIndex', 'SetNextMapIdent', 'LoadMatchSettings', 'SaveMatchSettings', 'SetMapList'):
            return await self.query(method, *params)
        if method in ('ForceEndRound', 'SetChallengeList', 'SetDisableRespawn',
                      'SetForceShowAllOpponents', 'SetRefereePassword', 'AllowChallengeDownload'):
            accepted = await self.query(method, *params)
            if accepted is not True:
                raise ControllerError(f'The dedicated server did not accept {method}.')
            return accepted
        mapped = MAP_RPC.get(method, method)
        args = _manialink_args(mapped, params)
        if args is None:
            return False
        return await super().query_ignore_result(mapped, *args)

    async def _reorder_maps(self, filenames):
        """Reorder only the existing rotation, recovering it if an RPC step fails."""
        if not isinstance(filenames, list) or not filenames or any(not isinstance(name, str) for name in filenames):
            raise ValueError('A non-empty list of map filenames is required.')
        from pyxaseco.core.playlist import read_playlist_pages
        rows = await read_playlist_pages(super().query, method='GetMapList', overlap=True)
        previous = [row['FileName'] for row in rows]
        if len(set(previous)) != len(previous) or sorted(filenames) != sorted(previous):
            raise ValueError('Shuffle must contain every existing map exactly once.')
        if filenames == previous:
            return True
        try:
            removed = await super().query('RemoveMapList', previous)
            if type(removed) is not int or removed != len(previous):
                raise ControllerError('The dedicated server did not remove the complete rotation.')
            added = await super().query('AddMapList', filenames)
            if type(added) is not int or added != len(filenames):
                raise ControllerError('The dedicated server did not accept the shuffled rotation.')
        except Exception as error:
            try:
                await super().query('RemoveMapList', previous)
                restored = await super().query('AddMapList', previous)
                if type(restored) is not int or restored != len(previous):
                    raise ControllerError('Incomplete restoration.')
            except Exception as recovery:
                raise ControllerError('Shuffle failed and the rotation could not be restored; reload MatchSettings.') from recovery
            raise ControllerError('Shuffle failed; the original rotation was restored.') from error
        return True

    async def time_attack_settings(self):
        mode = await super().query('GetModeScriptInfo')
        name = mode.get('Name', '') if isinstance(mode, dict) else ''
        if not is_time_attack_script(name):
            raise ControllerError('This build requires a Time Attack-compatible mode script.')
        settings = await super().query('GetModeScriptSettings')
        if not isinstance(settings, dict):
            raise ControllerError('The dedicated server did not return Time Attack script settings.')
        return settings
