"""Optional ManiaPlanet MXKarma API, using the PyPlanet API2 contract."""

import hashlib
import json
import math

from pyxaseco import BUILD_LABEL, PRODUCT_NAME
from pyxaseco.core.external_io import read_limited
from pyxaseco.core.http_sessions import request_timeout
from pyxaseco.core.service_health import observed_response
from pyxaseco.maniaplanet_callbacks import server_title


SITE = 'https://karma.mania-exchange.com'
OWNER = 'mx_karma'
VOTE_VALUES = {-3: 0, -2: 17, -1: 33, 1: 67, 2: 83, 3: 100}


class MXKarmaUnavailable(RuntimeError):
    pass


class MXKarmaSessionExpired(MXKarmaUnavailable):
    pass


async def _request(aseco, method, route, params, payload=None, *, timeout):
    session = aseco.jobs.http.get(OWNER)
    headers = {'User-Agent': f'{PRODUCT_NAME}/{BUILD_LABEL}',
               'X-ManiaPlanet-ServerLogin': aseco.server.serverlogin}
    try:
        async with observed_response(aseco, OWNER, session.request(
                method, f'{SITE}/api2/{route}', params=params, json=payload,
                headers=headers, allow_redirects=False,
                timeout=request_timeout(timeout))) as response:
            if not 200 <= response.status < 300:
                raise ValueError('unexpected HTTP status')
            result = json.loads(await read_limited(response, 1024 * 1024))
        if not isinstance(result, dict) or not isinstance(result.get('data'), dict):
            raise ValueError('invalid response')
    except Exception:
        # URLs and response bodies can contain session keys; never log them.
        raise MXKarmaUnavailable(f'MXKarma {route} unavailable or rejected') from None
    data = result['data']
    if result.get('success') is not True:
        if data.get('code') == 2:
            raise MXKarmaSessionExpired('MXKarma session expired or invalid')
        raise MXKarmaUnavailable(f'MXKarma {route} rejected')
    return data


async def authenticate(aseco, key, *, timeout):
    result = await _request(aseco, 'GET', 'startSession', {
        'serverLogin': aseco.server.serverlogin,
        'applicationIdentifier': f'{PRODUCT_NAME} {BUILD_LABEL}',
        'testMode': 'false',
    }, timeout=timeout)
    session_key, seed = result.get('sessionKey'), result.get('sessionSeed')
    if not all(isinstance(value, str) and 0 < len(value) <= 512
               for value in (session_key, seed)):
        raise MXKarmaUnavailable('MXKarma did not return a session')
    proof = hashlib.sha512((key + seed).encode('utf-8')).hexdigest()
    activated = await _request(aseco, 'GET', 'activateSession', {
        'sessionKey': session_key, 'activationHash': proof,
    }, timeout=timeout)
    if activated.get('activated') is not True:
        raise MXKarmaUnavailable('MXKarma activation was rejected')
    return session_key


def _map_fields(course, title_id='TMStadium@nadeo'):
    return {'gamemode': course['script'], 'titleid': title_id, 'mapuid': course['uid']}


async def map_rating(aseco, session_key, course, *, timeout):
    result = await _request(aseco, 'POST', 'getMapRating', {'sessionKey': session_key}, {
        **_map_fields(course, server_title(aseco)), 'getvotesonly': False, 'playerlogins': [],
    }, timeout=timeout)
    total, average = result.get('votecount'), result.get('voteaverage')
    if type(total) is not int or total < 0:
        raise MXKarmaUnavailable('MXKarma did not return a valid vote count')
    if total == 0:
        return {'total': 0, 'karma': 50}
    if type(average) not in (int, float) or not 0 <= average <= 100 or not math.isfinite(average):
        raise MXKarmaUnavailable('MXKarma did not return a valid rating')
    return {'total': total, 'karma': round(average)}


async def save_votes(aseco, session_key, course, votes, *, timeout):
    result = await _request(aseco, 'POST', 'saveVotes', {'sessionKey': session_key}, {
        **_map_fields(course, server_title(aseco)), 'mapname': course['name'], 'mapauthor': course['author'],
        'isimport': False, 'maptime': course['seconds'],
        'votes': [{'login': login, 'nickname': data['nickname'], 'vote': VOTE_VALUES[data['vote']]}
                  for login, data in votes.items()],
    }, timeout=timeout)
    if type(result.get('updated')) is not bool:
        raise MXKarmaUnavailable('MXKarma did not confirm the vote submission')
