"""First playable controller for MP4 Stadium scripted Time Attack."""

import asyncio
from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET

from pyxaseco import BUILD_LABEL, PRODUCT_NAME
from pyxaseco.helpers import format_time_millis as format_time
from pyxaseco.maniaplanet_callbacks import decode


LOGIN = re.compile(r'[A-Za-z0-9_.@-]{1,100}')
UID = re.compile(r'[A-Za-z0-9_-]{1,64}')
UINT32 = 4_294_967_295
PAGE = '5721000'
CLOSE = '5721001'


class ControllerError(ValueError):
    """This connection did not meet the conditions for the test controller."""


def safe_login(value):
    return value if isinstance(value, str) and LOGIN.fullmatch(value) else None


@dataclass(frozen=True)
class Course:
    uid: str
    name: str
    checkpoints: int


def course_from_rpc(data):
    if not isinstance(data, dict):
        return None
    uid = data.get('Uid') or data.get('UId')
    count = data.get('NbCheckpoints')
    if not isinstance(uid, str) or not UID.fullmatch(uid) or type(count) is not int or not 1 <= count <= 5000:
        return None
    name = data.get('Name')
    return Course(uid, name if isinstance(name, str) else uid, count)


def records_page(course, rows):
    page = ET.Element('manialink', id=PAGE, version='3')
    ET.SubElement(page, 'quad', pos='-45 35', size='90 55', bgcolor='112d', **{'z-index': '1'})
    ET.SubElement(page, 'label', pos='-41 31', size='68 5', text='Local Records: ' + course.name.replace('$', '$$')[:110],
                  textsize='3', **{'z-index': '2'})
    ET.SubElement(page, 'label', pos='30 31', size='12 5', text='Close', action=CLOSE,
                  style='TextButtonSmall', **{'z-index': '2'})
    if not rows:
        ET.SubElement(page, 'label', pos='-41 22', text='No local records yet.', **{'z-index': '2'})
    for rank, (login, time) in enumerate(rows[:10], 1):
        ET.SubElement(page, 'label', pos=f'-41 {25 - rank * 4}', size='80 4',
                      text=f'{rank:2}. {format_time(time)}  {login}', **{'z-index': '2'})
    return ET.tostring(page, encoding='unicode')


class StadiumTimeAttack:
    def __init__(self, rpc, records):
        self.rpc = rpc
        self.records = records
        self.course = None
        self.starts = {}
        self.latest_starts = {}

    def clear_map(self):
        self.course = None
        self.starts.clear()
        self.latest_starts.clear()

    async def sync_map(self, expected=None):
        self.clear_map()
        mode = await self.rpc.query('GetModeScriptInfo')
        name = mode.get('Name', '') if isinstance(mode, dict) else ''
        tail = str(name).replace('\\', '/').rsplit('/', 1)[-1].casefold().removesuffix('.script.txt')
        if tail != 'timeattack':
            raise ControllerError('This build only supports the official TimeAttack.Script.txt mode.')
        course = course_from_rpc(await self.rpc.query('GetCurrentMapInfo'))
        if course and (expected is None or course.uid == expected):
            self.course = course

    async def reply(self, login, text):
        await self.rpc.query_ignore_result('ChatSendServerMessageToLogin', f'$z$s$8cf{PRODUCT_NAME}$fff: {text}', login)

    async def command(self, login, text):
        key = text.strip().casefold()
        if key == '/help':
            await self.reply(login, '/help, /pb, /recs. Local records only on this test server.')
        elif key in ('/pb', '/recs'):
            if not self.course:
                await self.reply(login, 'The map is changing or its checkpoint data is unavailable.')
            elif key == '/pb':
                pb = await self.records.personal(self.course.uid, login)
                await self.reply(login, 'No local PB yet.' if pb is None else f'Your local PB: {format_time(pb)}')
            else:
                rows = await self.records.top(self.course.uid)
                await self.rpc.query_ignore_result('SendDisplayManialinkPageToLogin', login,
                                                   records_page(self.course, rows), 0, False)

    async def callback(self, method, params):
        name = method.casefold()
        if name == 'maniaplanet.playerchat' and len(params) >= 3:
            login = safe_login(params[1])
            if login and isinstance(params[2], str) and len(params[2]) <= 32:
                await self.command(login, params[2])
            return
        if name == 'maniaplanet.playermanialinkpageanswer' and len(params) >= 3:
            login = safe_login(params[1])
            if login and params[2] in (CLOSE, int(CLOSE)):
                await self.rpc.query_ignore_result('SendDisplayManialinkPageToLogin', login,
                                                   f'<manialink id="{PAGE}" version="3"/>', 0, False)
            return
        event = decode(method, params)
        if not event:
            return
        kind = event['event']
        if kind in ('map_unloading', 'map_end', 'map_begin'):
            self.clear_map()
            return
        if kind == 'map_loaded':
            await self.sync_map(expected=event.get('uid'))
            return
        login = safe_login(event.get('login'))
        if not login:
            return
        if kind in ('leave', 'give_up'):
            self.starts.pop(login, None)
            if kind == 'leave':
                self.latest_starts.pop(login, None)
        elif kind == 'race_start' and self.course:
            stamp = event.get('server_time_ms')
            if stamp is not None and stamp > self.latest_starts.get(login, -1):
                self.latest_starts[login] = stamp
                self.starts[login] = stamp
        elif kind == 'finish' and event.get('source') == 'script':
            await self.finish(login, event)

    async def finish(self, login, event):
        course = self.course
        start = self.starts.get(login)
        ended = event.get('server_time_ms')
        if course is None or start is None or ended is None or ended <= start:
            return
        self.starts.pop(login)
        time = event['race_time_ms']
        splits = event.get('splits_ms')
        if (not 0 < time <= UINT32 or not splits or len(splits) != course.checkpoints
                or event.get('checkpoint_index') != len(splits) - 1 or splits[-1] != time
                or splits[0] <= 0 or any(a > b for a, b in zip(splits, splits[1:]))):
            return
        if await self.records.save(course.uid, login, time, splits):
            await self.reply(login, f'Local PB saved: {format_time(time)}')


async def serve(rpc, records, report):
    if report['status']['Code'] != 4:
        raise ControllerError('Wait for the Stadium server to be in Running - Play state.')
    controller = StadiumTimeAttack(rpc, records)
    await controller.sync_map()
    if controller.course is None:
        raise ControllerError('The active map did not supply a valid UID and checkpoint count.')
    print(f'{PRODUCT_NAME} v{BUILD_LABEL}: Stadium Time Attack ready (/help, /pb, /recs).', flush=True)
    while rpc.is_connected():
        for method, params in rpc.get_cb_responses():
            await controller.callback(method, params)
        await asyncio.sleep(0.05)
    raise ControllerError('The dedicated server disconnected. Restart the MP controller once it is ready.')
