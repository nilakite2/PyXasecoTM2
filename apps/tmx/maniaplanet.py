"""TM2 ManiaExchange v2 adapter. Keep TMF and TM2 identifiers separate."""

import re
from urllib.parse import urlencode, urlsplit

from pyxaseco import BUILD_LABEL, PRODUCT_NAME
from pyxaseco.core.external_io import request_json
from pyxaseco.helpers import clean_tm_text, format_time
from pyxaseco.maniaplanet_callbacks import is_shootmania, server_title


HOST = 'tm.mania.exchange'
BASE = f'https://{HOST}'
SECTION = 'MX'
MAP_FIELDS = ('MapId,MapUid,Name,GbxMapName,Uploader.Name,Environment,ServerSizeExceeded,'
              'ReplayCount,TitlePack,Type,MapType,UploadedAt,UpdatedAt,AwardCount,Difficulty,Routes,Length,Tags')
REPLAY_FIELDS = 'ReplayId,ReplayTime,User.Name,Position,HasFile,ReplayAt,TrackAt'
UID = re.compile(r'[A-Za-z0-9_-]{1,64}')
ID = re.compile(r'[0-9]{1,18}')
ENVIRONMENTS = ('Custom', 'Canyon', 'Stadium', 'Valley', 'Lagoon', 'Desert', 'Snow', 'Rally', 'Coast', 'Bay', 'Island')
DIFFICULTIES = ('Beginner', 'Intermediate', 'Advanced', 'Expert', 'Lunatic', 'Impossible')
ROUTES = ('Single', 'Multiple', 'Symmetrical')


class MapDownloadRejected(ValueError):
    """A known map refusal, not a provider outage; messages must be safe for chat."""


def map_page(map_id):
    return f'{BASE}/mapshow/{int(map_id)}'


def map_download_url(map_id):
    return f'{BASE}/mapgbx/{int(map_id)}'


def map_image_url(map_id):
    # MP Records Eyepiece gives the client a file type for extensionless images.
    return f'{BASE}/mapimage/{int(map_id)}/0?.jpg'


def download_reference(reference):
    text = str(reference or '').strip()
    if ID.fullmatch(text) and int(text) > 0:
        return int(text)
    url = urlsplit(text)
    match = re.fullmatch(r'/(?:mapshow|mapgbx)/([0-9]{1,18})(?:/[^/]*)?/?', url.path)
    if url.scheme in ('http', 'https') and url.netloc.casefold() == HOST and match and int(match[1]) > 0:
        return int(match[1])
    raise ValueError('Use a ManiaExchange map ID or a tm.mania.exchange map link.')


def verify_download(map_data, title_id='TMStadium@nadeo'):
    if is_shootmania(title_id) or is_shootmania(map_data.get('titlepack', ''), map_data):
        raise MapDownloadRejected('ShootMania maps and titles are not supported.')
    if map_data.get('server_size_exceeded'):
        raise MapDownloadRejected('This MX map exceeds the dedicated server size limit.')
    # The dedicated server validates the downloaded map against its active
    # title/script before insertion. Do not guess compatibility from MX labels.


def _choice(options, value):
    return options[value] if type(value) is int and 0 <= value < len(options) else ''


def _number(value):
    return value if type(value) is int else 0


def _name(value):
    return clean_tm_text(value) if isinstance(value, str) else ''


async def _results(aseco, route, fields, **filters):
    query = urlencode(dict(fields=fields, **filters))
    result = await request_json(aseco, 'tmx_metadata', 'GET', f'{BASE}/api/{route}?{query}',
                                headers={'User-Agent': f'{PRODUCT_NAME}/{BUILD_LABEL}'}, timeout=10)
    if result is None:
        return []
    if not isinstance(result, dict) or not isinstance(result.get('Results'), list):
        raise ValueError('Invalid ManiaExchange results.')
    if not all(isinstance(row, dict) for row in result['Results']):
        raise ValueError('Invalid ManiaExchange result row.')
    return result['Results']


def _map(row):
    map_id = _number(row.get('MapId'))
    uid = row.get('MapUid')
    if map_id <= 0 or not isinstance(uid, str) or not UID.fullmatch(uid):
        raise ValueError('Invalid ManiaExchange map identity.')
    uploader = row.get('Uploader')
    length = _number(row.get('Length'))
    tags = row.get('Tags')
    first_tag = tags[0] if isinstance(tags, list) and tags else None
    return {
        'id': map_id, 'uid': uid, 'section': SECTION,
        'name': _name(row.get('Name') or row.get('GbxMapName')) or uid,
        'author': _name(uploader.get('Name')) if isinstance(uploader, dict) else '',
        'type': _name(row.get('MapType')),
        'style': _name(first_tag.get('Name')) if isinstance(first_tag, dict) else '',
        'mood': '',
        'envir': _choice(ENVIRONMENTS, row.get('Environment')),
        'diffic': _choice(DIFFICULTIES, row.get('Difficulty')),
        'routes': _choice(ROUTES, row.get('Routes')),
        'author_time': length,
        'length': format_time(length) if length > 0 else '',
        'awards': _number(row.get('AwardCount')), 'lbrating': '',
        'uploaded': str(row.get('UploadedAt') or '')[:16],
        'updated': str(row.get('UpdatedAt') or '')[:16],
        'titlepack': _name(row.get('TitlePack')),
        'server_size_exceeded': row.get('ServerSizeExceeded') is True,
        'replay_count': _number(row.get('ReplayCount')),
        'pageurl': map_page(map_id), 'dloadurl': map_download_url(map_id),
        'imageurl': map_image_url(map_id),
        'replayurl': '', 'recordlist': [],
    }


async def _replays(aseco, map_id):
    rows = await _results(aseco, 'replays', REPLAY_FIELDS, mapid=map_id, best=1, count=10)
    replays = []
    for row in rows:
        replay_id, time = _number(row.get('ReplayId')), _number(row.get('ReplayTime'))
        if replay_id <= 0 or time <= 0:
            continue
        user = row.get('User')
        replays.append({
            'id': replay_id, 'time': time,
            'name': (_name(user.get('Name')) if isinstance(user, dict) else '') or '?',
            'url': f'{BASE}/recordgbx/{replay_id}' if row.get('HasFile') is True else '',
            'replay_at': row.get('ReplayAt') or '', 'track_at': row.get('TrackAt') or '',
        })
    return sorted(replays, key=lambda row: row['time'])[:10]


async def fetch_map(aseco, reference, *, records=False):
    reference = str(reference or '').strip()
    if ID.fullmatch(reference) and int(reference) > 0:
        key, value = 'id', int(reference)
    elif UID.fullmatch(reference) and not reference.isdecimal():
        key, value = 'uid', reference
    else:
        return None
    rows = await _results(aseco, 'maps', MAP_FIELDS, count=1, **{key: value})
    if not rows:
        return None
    data = _map(rows[0])
    if data[key] != value:
        raise ValueError('ManiaExchange returned a different map.')
    if records and data['replay_count'] > 0:
        data['recordlist'] = await _replays(aseco, data['id'])
        if data['recordlist']:
            data['replayurl'] = data['recordlist'][0]['url']
    return data


async def random_map(aseco, title_id):
    title = str(title_id or '').partition('@')[0]
    if not title:
        raise MapDownloadRejected('Random MX needs an active TrackMania title.')
    rows = await _results(aseco, 'maps', MAP_FIELDS, count=1, random=1, titlepack=title)
    return _map(rows[0]) if rows else None


async def search_maps(aseco, name):
    query = str(name or '').strip()
    if not 2 <= len(query) <= 80:
        return []
    rows = await _results(aseco, 'maps', MAP_FIELDS, name=query, count=12)
    return [_map(row) for row in rows]


async def search_list(aseco, *, name='', author='', recent=False, tag=None):
    filters = {'count': 10 if recent else 100, 'order1': 6 if recent else 1}
    if name:
        filters['name'] = str(name)[:80]
    if author:
        filters['author'] = str(author)[:80]
    if tag is not None:
        filters['tag'] = int(tag)
    rows = await _results(aseco, 'maps', MAP_FIELDS, **filters)
    maps = [_map(row) for row in rows]
    return [dict(row, environment=row['envir']) for row in maps]
