"""Native ManiaLink v3 drawing primitives and shared command windows."""

import asyncio
import logging
import xml.etree.ElementTree as ET

from pyxaseco.helpers import ML_ID_MAIN


logger = logging.getLogger(__name__)
_SCRIPT_UI_FIELDS = {
    'challenge_info': ('map_info', 'visible'),
    'chat': ('chat', 'visible'),
    'checkpoint_list': ('checkpoint_list', 'visible'),
    'checkpoint_ranking': ('checkpoint_ranking', 'visible'),
    'round_scores': ('round_scores', 'visible'),
    'scoretable': ('scorestable', 'visible'),
}


def _script_ui_state(aseco):
    if not hasattr(aseco, '_mp_custom_ui_properties'):
        aseco._mp_custom_ui_properties = {}
        aseco._mp_custom_ui_lock = asyncio.Lock()
    return aseco._mp_custom_ui_properties, aseco._mp_custom_ui_lock


async def apply_script_ui(aseco, flags, *, force=False):
    """Apply server-wide MP script visibility, never an individual player's preferences."""
    properties = {_SCRIPT_UI_FIELDS[name]: 'true' if value else 'false'
                  for name, value in flags.items() if name in _SCRIPT_UI_FIELDS}
    if 'scoretable' in flags:
        properties[('scorestable', 'alt_visible')] = 'true' if flags['scoretable'] else 'false'
    state, lock = _script_ui_state(aseco)
    async with lock:
        changed = {key: value for key, value in properties.items() if force or state.get(key) != value}
        if not changed:
            return
        root = ET.Element('ui_properties')
        nodes = {}
        for (module, attribute), value in changed.items():
            if module not in nodes:
                nodes[module] = ET.SubElement(root, module)
            nodes[module].set(attribute, value)
        accepted = await aseco.client.query('TriggerModeScriptEventArray', 'Trackmania.UI.SetProperties',
                                           [ET.tostring(root, encoding='unicode')])
        if accepted is True:
            state.update(changed)
        else:
            logger.warning('The dedicated server did not accept the native UI visibility request')


async def restore_script_ui(aseco, _data=None):
    """Release only visibility properties owned by the controller, not positions or other HUD settings."""
    if not hasattr(aseco, '_mp_custom_ui_properties'):
        return
    state, lock = _script_ui_state(aseco)
    async with lock:
        for module, attribute in tuple(state):
            accepted = await aseco.client.query('TriggerModeScriptEventArray', 'Trackmania.UI.ResetProperty',
                                               [module, attribute])
            if accepted is True:
                state.pop((module, attribute))
            else:
                logger.warning('Could not release the native UI visibility property %s.%s', module, attribute)


def provider_label(text):
    """Adapt generated provider labels, never player or map content."""
    return (str(text).replace('ManiaKarma', 'MXKarma').replace('TMX', 'MX')
            .replace('/tmxinfo', '/mxinfo').replace('/tmxrecs', '/mxrecs'))


PAGER_ACTIONS = dict(zip((-4, -3, -2, 0, 1, 2, 3, 4), range(5721210, 5721218)))
PAGER_ANSWERS = {action: code for code, action in PAGER_ACTIONS.items()}
CARD = {'style': 'BgsPlayerCard', 'substyle': 'BgCardSystem'}
TITLE = {'style': 'BgsPlayerCard', 'substyle': 'BgRacePlayerName'}
WINDOW_TEXT_COLOR = 'F0F3F8FF'
WINDOW_COLORS = {'{#black}': '$def', '{black}': '$def', '{#welcome}': '$cde'}


def quad(parent, x, y, w, h, depth=0, **attrs):
    return ET.SubElement(parent, 'quad', pos=f'{x:g} {y:g}', size=f'{w:g} {h:g}',
                         **{'z-index': str(depth), **attrs})


def label(parent, x, y, w, h, text, *, depth=2, textsize='1', **attrs):
    return ET.SubElement(parent, 'label', pos=f'{x:g} {y:g}', size=f'{w:g} {h:g}',
                         text=str(text), textsize=textsize, **{'z-index': str(depth), **attrs})


def _window_label(parent, x, y, w, h, text, **attrs):
    text = str(text)
    for token, color in WINDOW_COLORS.items():
        text = text.replace(token, color)
    return label(parent, x, y, w, h, text, textcolor=WINDOW_TEXT_COLOR, **attrs)


def _pager_icon(parent, x, y, substyle, action, *, size=7):
    ident = str(PAGER_ACTIONS.get(action, action))
    quad(parent, x, y + (size - 7) / 2, size, size, 2, halign='center', style='Icons64x64_1',
         substyle=substyle, action=ident)


def command_window(_player, title, rows, widths, page=1, total=1, refresh_action=None, *, icon=None):
    width = min(240, max(135, widths[0] * 145))
    row_height = min(5.5, 125 / max(len(rows), 1))
    height = 23 + row_height * len(rows)
    root = ET.Element('manialink', id=ML_ID_MAIN, version='3')
    frame = ET.SubElement(root, 'frame', pos=f'{-width / 2:g} {height / 2:g}', **{'z-index': '20'})
    quad(frame, 0, 0, width, height, bgcolor='15171DF2')
    quad(frame, 1, -1, width - 2, 8, 1, bgcolor='242D3BFF')
    title_x = 4
    if icon and len(icon) >= 2:
        quad(frame, 3, -2, 5, 5, 2, style=icon[0], substyle=icon[1])
        title_x = 10
    _window_label(frame, title_x, -2.5, width - title_x - 23, 6, title, textsize='2')
    if total > 1:
        _window_label(frame, width - 4, -3.2, 20, 5, f'{page} / {total}', halign='right')

    columns = widths[1:] or [1]
    usable = width - 8
    columns = [usable * value / (sum(columns) or 1) for value in columns]
    for index, row in enumerate(rows):
        if not row:
            continue
        if isinstance(row, str):
            row = [row]
        y = -10 - index * row_height
        if index % 2 == 0:
            quad(frame, 2, y, width - 4, row_height, 1, bgcolor='FFFFFF0D')
        x = 4.0
        for cell, column in zip(row, [usable] if len(row) == 1 else columns):
            attrs = {}
            if isinstance(cell, (tuple, list)) and len(cell) == 2:
                cell, action = cell
                attrs = {'action': str(action), 'focusareacolor1': '303948FF', 'focusareacolor2': '46566AFF'}
            _window_label(frame, x, y - row_height / 2, max(1, column - 1.5), row_height, cell,
                          valign='center2', **attrs)
            x += column

    footer_y = -height + 9
    if page > 1:
        _pager_icon(frame, 8, footer_y, 'ArrowFirst', -4)
        if total > 5:
            _pager_icon(frame, 17, footer_y, 'ArrowFastPrev', -3)
        _pager_icon(frame, width / 4, footer_y, 'ArrowPrev', -2)
    _pager_icon(frame, width / 2, footer_y, 'Close', 0, size=8)
    if refresh_action is not None:
        _pager_icon(frame, width / 2 + 10, footer_y, 'Refresh', refresh_action)
    if page < total:
        _pager_icon(frame, width * 3 / 4, footer_y, 'ArrowNext', 2)
        if total > 5:
            _pager_icon(frame, width - 17, footer_y, 'ArrowFastNext', 3)
        _pager_icon(frame, width - 8, footer_y, 'ArrowLast', 4)
    return ET.tostring(root, encoding='unicode')
