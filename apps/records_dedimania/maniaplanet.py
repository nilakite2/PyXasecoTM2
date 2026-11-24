"""TM2 Dedimania adapter with the MP replay-backed submission protocol."""

import asyncio
import logging
from time import monotonic
import xmlrpc.client

from pyxaseco import BUILD_LABEL, PRODUCT_NAME
from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.config import _env
from pyxaseco.core.external_io import read_limited
from pyxaseco.core.http_sessions import HttpPolicy, request_timeout
from pyxaseco.core.service_health import observe_request
from pyxaseco.maniaplanet_runtime import safe_login

from .mp_submission import DedimaniaSubmissions


URL = 'http://dedimania.net:8082/Dedimania'
POLICY = JobPolicy(capacity=32, workers=1, deadline_seconds=90)
logger = logging.getLogger(__name__)


def normalise(records, count):
    rows = {}
    for entry in records[:500]:
        if not isinstance(entry, dict):
            continue
        login, best = safe_login(entry.get('Login')), entry.get('Best')
        if not login or type(best) is not int or best <= 0:
            continue
        try:
            checks = [int(value) for value in str(entry.get('Checks', '')).split(',')]
        except ValueError:
            checks = []
        if (len(checks) != count or not checks or checks[0] <= 0 or checks[-1] != best
                or any(a > b for a, b in zip(checks, checks[1:]))):
            checks = []
        old = rows.get(login)
        if old is None or best < old['Best']:
            rows[login] = {'Login': login, 'NickName': str(entry.get('NickName') or login).replace('\n', '')[:256],
                           'Best': best, 'Checks': checks, 'Game': 'TM2'}
    return sorted(rows.values(), key=lambda row: (row['Best'], row['Login']))


class DedimaniaMP:
    def __init__(self):
        self.dedi_db = {'Challenge': {}, 'RecsValid': False, 'MaxRank': 30, 'ShowRecLogins': True}
        self._connected = False
        self._session = ''
        self._session_lock = asyncio.Lock()
        self._next_request = 0.0
        self.submissions = DedimaniaSubmissions(self)

    def configured(self, aseco):
        return bool(str(_env('PYXASECOMP_DEDI_CODE') or '').strip()
                    and safe_login(aseco.server.serverlogin))

    async def _request(self, aseco, method, *args, timeout=15):
        calls = [{'methodName': method, 'params': list(args)},
                 {'methodName': 'dedimania.WarningsAndTTR', 'params': []}]
        payload = xmlrpc.client.dumps((calls,), 'system.multicall').encode('utf-8')
        session = aseco.jobs.http.get('mp4_dedimania', HttpPolicy())
        with observe_request(aseco, 'dedimania') as sample:
            async with session.post(URL, data=payload, headers={'Content-Type': 'text/xml'},
                                    timeout=request_timeout(timeout), allow_redirects=False) as response:
                if sample is not None:
                    sample.http_status = response.status
                response.raise_for_status()
                if response.status != 200:
                    raise ValueError('TM2 Dedimania did not return an XML-RPC response.')
                data = await read_limited(response, 4 * 1024 * 1024)
            results, _ = xmlrpc.client.loads(data)
            first = results[0][0] if results and isinstance(results[0], list) and results[0] else None
            row = first[0] if isinstance(first, list) and len(first) == 1 else first
            if not isinstance(row, dict) or 'faultCode' in row:
                if sample is not None:
                    sample.status = 'API rejected'
                raise ValueError('TM2 Dedimania rejected the request.')
            if row.get('Error') and not row.get('SessionId'):
                raise ValueError('TM2 Dedimania returned an API error.')
            return row

    async def _ensure_session(self, aseco):
        async with self._session_lock:
            if not self._session:
                code = str(_env('PYXASECOMP_DEDI_CODE') or '').strip()
                server = aseco.server
                if not code or not safe_login(server.serverlogin):
                    raise ValueError('TM2 Dedimania is not configured.')
                identity = {'Game': 'TM2', 'Login': server.serverlogin, 'Code': code,
                            'Path': 'World|' + server.zone.removeprefix('World|'),
                            'Packmask': server.packmask, 'ServerVersion': server.version, 'ServerBuild': server.build,
                            'Tool': PRODUCT_NAME, 'Version': BUILD_LABEL}
                opened = await self._request(aseco, 'dedimania.OpenSession', identity)
                session = opened.get('SessionId')
                if not isinstance(session, str) or not session:
                    raise ValueError('TM2 Dedimania session not accepted.')
                self._session = session
            return self._session

    async def update(self, aseco, _param):
        if not aseco.score_phase and monotonic() >= self._next_request:
            await self._fetch(aseco, aseco.server.challenge)

    async def new_map(self, aseco, challenge):
        await self.submissions.new_map(aseco, challenge)
        self.dedi_db.update(Challenge={}, RecsValid=False)
        await aseco.release_event('onDediRecsLoaded', False)
        await self._fetch(aseco, challenge)

    async def _fetch(self, aseco, challenge):
        server = aseco.server
        if not self.configured(aseco) or not challenge.uid:
            self._next_request = monotonic() + 240
            return
        info = {'UId': challenge.uid, 'Name': challenge.name, 'Environment': challenge.environment or 'Stadium',
                'Author': challenge.author, 'NbCheckpoints': challenge.nbchecks, 'NbLaps': challenge.nblaps}
        players = [{'Login': p.login, 'IsSpec': bool(p.isspectator)} for p in server.players.all()
                   if p.login != server.serverlogin and safe_login(p.login)]
        spectators = sum(row['IsSpec'] for row in players)
        options = {'SrvName': server.name, 'Comment': '', 'Private': True, 'NumPlayers': len(players) - spectators,
                   'MaxPlayers': server.maxplay, 'NumSpecs': spectators, 'MaxSpecs': server.maxspec}
        job = JobEnvelope.capture(aseco.capture_job_context(), {'map': info, 'server': options, 'players': players})

        async def fetch(envelope):
            try:
                await self._ensure_session(aseco)
                data = envelope.payload()
                result = await self._request(aseco, 'dedimania.GetChallengeRecords', self._session,
                                             data['map'], 'TA', data['server'], data['players'])
                records = result.get('Records')
                if not isinstance(records, list):
                    raise ValueError('Missing TM2 Dedimania records.')
                if result.get('UId', info['UId']) != info['UId']:
                    raise ValueError('TM2 Dedimania returned a different map.')
                return normalise(records, info['NbCheckpoints']), result
            except Exception:
                self._session = ''
                raise

        async def apply(result):
            self._connected = result.status == 'completed'
            if not self._connected:
                self.dedi_db.update(Challenge={}, RecsValid=False)
                logger.warning('[Dedimania MP] Lookup unavailable (%s)', result.failure_label)
            else:
                rows, response = result.value
                limit = response.get('ServerMaxRank')
                maximum = max(0, min(500, limit)) if type(limit) is int else 30
                rows = self.submissions.loaded(aseco, info, rows, response)
                self.dedi_db.update(Challenge={'Uid': info['UId'], 'Records': rows}, RecsValid=True,
                                    MaxRank=max(1, maximum), ServerMaxRank=maximum)
            await aseco.release_event('onDediRecsLoaded', self._connected)

        outcome = aseco.jobs.service('mp4_dedimania', POLICY).submit(job, fetch, apply, dedupe_key='map-records')
        self._next_request = monotonic() + (240 if outcome == Admission.ACCEPTED else 5)


def register(aseco):
    service = DedimaniaMP()
    aseco.register_service('service/records_dedimania', service, owner='service/records_dedimania',
                           aliases=['records_dedimania', 'service/dedimania', 'dedimania'])
    aseco.register_event('onNewChallenge', service.new_map)
    aseco.register_event('onEverySecond', service.update)
    aseco.register_event('onSync', service.submissions.startup)
    aseco.register_event('onEverySecond', service.submissions.update)
    aseco.register_event('onPlayerFinish', service.submissions.finish)
    aseco.register_event('onPlayerDisconnect', service.submissions.disconnect)
    aseco.register_event('onEndRace', service.submissions.end_map)
    aseco.register_event('onShutdown', service.submissions.shutdown)
