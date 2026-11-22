"""Minimal MP4 Current Track and Local Records fallback for servers without Eyepiece."""

import xml.etree.ElementTree as ET
from collections import defaultdict

from pyxaseco.core.widget_delivery import deliver_ui
from pyxaseco.helpers import clean_tm_text
from pyxaseco.maniaplanet_ui import CARD, TITLE, label, quad


APP_METADATA = {
    'id': 'mp_panels',
    'display_name': 'MP4 Panels',
    'description': 'Current track and local records for MP4 Stadium.',
    'depends_on': ['platform_core', 'records_local'],
}
TRACK_ID, RECORDS_ID = '5721100', '5721101'
TRACK_ACTION, RECORDS_ACTION, PB_ACTION = 5721102, 5721103, 5721104
RAIL_X, WIDTH = 120, 39.4
ROW_TOP, ROW_HEIGHT, ROW_LIMIT = -6, 4.2, 10


def _panel(root, page, y, height, title, action, icon_style, icon_substyle):
    link = ET.SubElement(root, 'manialink', id=page, version='3')
    frame = ET.SubElement(link, 'frame', pos=f'{RAIL_X} {y:g}', **{'z-index': '1'})
    quad(frame, 0, 0, WIDTH, height, **CARD)
    quad(frame, 1, -0.9, WIDTH - 2, 4.5, 1, **TITLE)
    quad(frame, 1.7, -0.45, 5.1, 5.1, 2, style=icon_style, substyle=icon_substyle)
    label(frame, 7.5, -3.15, WIDTH - 8.5, 5, title, valign='center2')
    _hit_area(frame, 0, 0, WIDTH, height, action)
    return frame


def _hit_area(frame, x, y, width, height, action):
    quad(frame, x, y, width, height, 3, action=str(action), bgcolor='FFFFFF01', bgcolorfocus='FFFFFF16')


def _track_panel(root, aseco, course, page=TRACK_ID):
    frame = _panel(root, page, 87, 19, 'Current Track', TRACK_ACTION, 'Icons128x128_1', 'Challenge')
    label(frame, 2, -6, WIDTH - 4, 4.4, clean_tm_text(course.name))
    label(frame, 2, -10, WIDTH - 4, 4.4, f'by {clean_tm_text(course.author) or "Unknown"}', scale='0.88')
    quad(frame, 1.7, -14.1, 3.5, 3.5, 2, style='BgRaceScore2', substyle='ScoreReplay')
    author_time = aseco.format_time(course.authortime) if course.authortime > 0 else '--'
    label(frame, 6, -14.25, 17, 4, author_time, scale='0.85')
    quad(frame, 24.5, -14.1, 3.5, 3.5, 2, style='Icons128x128_1', substyle='Advanced')
    label(frame, 29, -14.25, 10, 4, f'{max(0, course.nbchecks - 1)} CPs', scale='0.85')


def _records_panel(root, aseco, login, page=RECORDS_ID):
    records = aseco.server.records
    count = min(records.count(), ROW_LIMIT)
    body_height = max(1, count) * ROW_HEIGHT
    frame = _panel(root, page, 44, 6.7 + body_height, 'Local Records', RECORDS_ACTION,
                   'BgRaceScore2', 'LadderRank')
    for x, width, shade in ((1, 5, 'AAAAAA55'), (6, 9.8, 'AAAAAA33'), (15.8, 22.6, 'AAAAAA11')):
        quad(frame, x, ROW_TOP, width, body_height, 0.5, bgcolor=shade)
    if count:
        quad(frame, 1, ROW_TOP, WIDTH - 2, min(count, 3) * ROW_HEIGHT, 1, **CARD)
    first_row_center = ROW_TOP - ROW_HEIGHT / 2
    for index in range(count):
        record = records.get_record(index)
        y = first_row_center - index * ROW_HEIGHT
        own = bool(login and login == record.player.login)
        if own:
            quad(frame, 1, y + ROW_HEIGHT / 2, WIDTH - 2, ROW_HEIGHT, 1.5, **CARD)
        nick = clean_tm_text(record.player.nickname) or record.player.login
        time_color = '33FF55FF' if own else ('FFFF00FF' if index < 3 else 'CCCCCCFF')
        label(frame, 5.75, y, 4, ROW_HEIGHT, f'{index + 1}.', halign='right', valign='center2', scale='0.85')
        label(frame, 6, y, 9.7, ROW_HEIGHT, '$n' + aseco.format_time(record.score),
              valign='center2', scale='0.82', textcolor=time_color)
        label(frame, 16.15, y, WIDTH - 17.5, ROW_HEIGHT, nick, valign='center2', scale='0.9')
    if not count:
        label(frame, 2.1, first_row_center, WIDTH - 4, ROW_HEIGHT, 'No local records yet',
              valign='center2', scale='0.85')
    quad(frame, -5.7, ROW_TOP, 5.2, ROW_HEIGHT, 1, **CARD)
    label(frame, -3.1, first_row_center, 5, ROW_HEIGHT, 'PB', scale='0.75', halign='center', valign='center2')
    _hit_area(frame, -5.7, ROW_TOP, 5.2, ROW_HEIGHT, PB_ACTION)


def build_panels(aseco, *, login='', hide=False):
    root = ET.Element('manialinks')
    course = aseco.server.challenge
    if hide or not course.uid:
        for page in (TRACK_ID, RECORDS_ID):
            ET.SubElement(root, 'manialink', id=page, version='3')
        return ET.tostring(root, encoding='unicode')
    _track_panel(root, aseco, course)
    _records_panel(root, aseco, login)
    return ET.tostring(root, encoding='unicode')


async def _show(aseco, _payload):
    if aseco.has_service('ui/custom_ui'):
        return  # Eyepiece owns the same panels, using its standard page IDs.
    groups = defaultdict(list)
    for player in aseco.server.players.all():
        xml = build_panels(aseco, login=player.login, hide=aseco.score_phase)
        groups[xml].append(player.login)
    for xml, logins in groups.items():
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', ','.join(logins), xml, 0, False)


async def _join(aseco, player):
    if aseco.has_service('ui/custom_ui'):
        return
    await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login,
                     build_panels(aseco, login=player.login, hide=aseco.score_phase), 0, False)


async def _answer(aseco, params):
    if len(params) >= 3 and (command := {
        TRACK_ACTION: '/track', RECORDS_ACTION: '/recs', PB_ACTION: '/pb',
    }.get(params[2])):
        await aseco.dispatch_chat_command(params[1], command)


def register(aseco):
    for event in ('onNewChallenge2', 'onLocalRecord', 'onEndRace'):
        aseco.register_event(event, _show)
    aseco.register_event('onPlayerConnect2', _join)
    aseco.register_event('onPlayerManialinkPageAnswer', _answer)
