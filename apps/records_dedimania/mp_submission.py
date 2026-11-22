"""Capture MP finishes and submit replay-backed batches without blocking on HTTP."""

import asyncio
import base64
import binascii
import logging
from pathlib import Path
from time import monotonic
from uuid import uuid4
from xmlrpc.client import Binary

from pyxaseco.core.background_jobs import Admission, JobEnvelope
from pyxaseco.core.config import _env
from pyxaseco.core.file_io import file_io
from pyxaseco.core.retained_delivery import PreparationDeferred, PreparationRejected, delivery
from pyxaseco.helpers import format_time
from pyxaseco.maniaplanet_runtime import safe_login
from pyxaseco.models import Gameinfo

from .mp_replays import MAX_BATCH_BYTES, MAX_REPLAY_BYTES, ReplayError, check_replay


logger = logging.getLogger(__name__)
OWNER = 'mp4_dedimania_submit'
MAX_PENDING_BYTES = 64 * 1024 * 1024


class EligibilityError(ValueError):
    pass


def player_status(status, login):
    """Normalize documented status scalars without treating arbitrary truthy data as authorization."""
    if not isinstance(status, dict):
        raise EligibilityError('response is not a player status struct')
    if status.get('Login') != login:
        raise EligibilityError('missing or mismatched Login')
    banned = status.get('Banned')
    if type(banned) is bool:
        pass
    elif type(banned) is int and banned in (0, 1):
        banned = bool(banned)
    elif isinstance(banned, str) and banned.strip().lower() in ('true', 'false', '0', '1'):
        banned = banned.strip().lower() in ('true', '1')
    else:
        raise EligibilityError('missing or invalid Banned flag (' + type(banned).__name__ + ')')
    rank = status.get('MaxRank')
    if isinstance(rank, str) and rank.strip().isascii() and rank.strip().isdecimal():
        rank = int(rank.strip()) if len(rank.strip()) <= 3 else -1
    elif type(rank) is float and rank.is_integer():
        rank = int(rank)
    if type(rank) is not int or not 0 <= rank <= 500:
        raise EligibilityError('missing or invalid MaxRank (' + type(rank).__name__ + ')')
    return dict(status, Banned=banned, MaxRank=rank)


def player_identity(player):
    return {'Login': player.login, 'NickName': player.nickname,
            'Path': 'World|' + player.zone.removeprefix('World|'), 'IsSpec': bool(player.isspectator)}


def eligible_checks(checks, score, count):
    return (isinstance(checks, list) and len(checks) == count and bool(checks)
            and all(type(value) is int and 0 < value <= score for value in checks)
            and checks[-1] == score and all(a <= b for a, b in zip(checks, checks[1:])))


def replay_directory(aseco):
    configured = str(_env('PYXASECOMP_REPLAYS_DIR') or '').strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            raise ReplayError('PYXASECOMP_REPLAYS_DIR must be an absolute UserData/Replays path')
        return path.resolve()
    directory = Path(str(aseco.server.gamedir or ''))
    if directory.is_absolute():
        return directory.resolve() / 'Replays'
    root = Path(aseco._base_dir).resolve()
    candidates = {path.resolve() for path in (root / directory, root.parent / directory)
                  if str(directory) not in ('', '.') and path.is_dir()}
    if len(candidates) != 1:
        raise ReplayError('Set PYXASECOMP_REPLAYS_DIR to the dedicated UserData/Replays folder')
    return candidates.pop() / 'Replays'


class DedimaniaSubmissions:
    def __init__(self, reader):
        self.reader = reader
        self._info = None
        self._valid = False
        self._eligibility_reported = False
        self._top1 = 0
        self._pending = {}
        self._pending_bytes = 0
        self._players = {}
        self._player_inflight = set()
        self._next_player_try = {}
        self._delivery = None
        self._delivery_retry_at = 0.0
        self.last_submission_status = 'No submissions yet'

    def _retainer(self, aseco):
        if self._delivery is None:
            async def prepare(payload):
                try:
                    result = await file_io(self._prepare_replays, payload)
                except (ReplayError, ValueError, TypeError, KeyError, binascii.Error) as error:
                    logger.warning('[Dedimania MP] Retained submission has invalid replay evidence')
                    raise PreparationRejected('Invalid MP replay evidence') from error
                try:
                    result['session'] = await self.reader._ensure_session(aseco)
                    for player in payload['players']:
                        status = await self.reader._request(
                            aseco, 'dedimania.PlayerConnect', result['session'], player['Login'],
                            player['NickName'], player['Path'], player['IsSpec'])
                        try:
                            status = player_status(status, player['Login'])
                        except EligibilityError as error:
                            logger.warning('[Dedimania MP] Submission eligibility rejected: %s', error)
                            raise PreparationRejected('Player eligibility was not confirmed') from error
                        if status['Banned']:
                            raise PreparationRejected('Player eligibility was not confirmed')
                except PreparationRejected:
                    logger.warning('[Dedimania MP] Submission blocked by player eligibility checks')
                    raise
                except Exception as error:
                    self.reader._session = ''
                    self._delivery_retry_at = monotonic() + 30
                    raise PreparationDeferred('TM2 Dedimania authentication unavailable') from error
                return result

            async def send(prepared):
                result = await self.reader._request(
                    aseco, 'dedimania.SetChallengeTimes', prepared['session'], prepared['map'], 'TA',
                    prepared['times'], prepared['replays'], timeout=60)
                if result.get('UId') != prepared['map']['UId'] or not isinstance(result.get('Records'), list):
                    raise ValueError('TM2 Dedimania submission was not confirmed')
                logger.info('[Dedimania MP] Submission processed for %s (%d time(s))',
                            prepared['map']['UId'], len(prepared['times']))
                return result

            async def applied(payload, result, current):
                self.last_submission_status = 'Processed'
                if current:
                    from .maniaplanet import normalise
                    rows = normalise(result['Records'], payload['map']['NbCheckpoints'])
                    self.reader.dedi_db.update(Challenge={'Uid': payload['map']['UId'], 'Records': rows}, RecsValid=True)
                    await aseco.release_event('onDediRecsLoaded', True)

            async def failed(result):
                self.last_submission_status = 'Failed or uncertain; retained for inspection'
                logger.warning('[Dedimania MP] Submission failed or is uncertain (%s); not automatically resubmitted',
                               result.failure_label)

            self._delivery = delivery(aseco, OWNER, send, applied, prepare=prepare, on_failure=failed,
                                      ready=lambda: monotonic() >= self._delivery_retry_at)
        return self._delivery

    async def startup(self, aseco, _data=None):
        if str(_env('PYXASECOMP_DEDI_CODE') or '').strip():
            self._retainer(aseco)

    async def new_map(self, aseco, challenge):
        await self.end_map(aseco)
        self._info = None
        self._valid = False
        self._eligibility_reported = False
        self._top1 = 0

    def loaded(self, aseco, info, rows, response):
        if self._info is None or self._info['UId'] != info['UId']:
            self._info = dict(info)
        top1 = rows[0]['Best'] if rows else 0
        self._top1 = top1
        modes = response.get('AllowedGameModes', 'TA')
        modes = modes.replace(';', ',').split(',') if isinstance(modes, str) else modes
        allowed = isinstance(modes, (list, tuple)) and any(str(mode).strip() == 'TA' for mode in modes)
        self._valid = (allowed and info['NbCheckpoints'] >= 2 and aseco.server.challenge.authortime >= 10000
                       and aseco.server.gameinfo.mode == Gameinfo.TA)
        if not self._valid and not self._eligibility_reported:
            logger.info('[Dedimania MP] Map is read-only: mode, author time or checkpoint count is not eligible for submission')
            self._eligibility_reported = True
        merged = {row['Login']: row for row in rows}
        for login, item in self._pending.items():
            row = item['record']
            if login not in merged or row['Best'] < merged[login]['Best']:
                merged[login] = dict(row)
        return sorted(merged.values(), key=lambda row: (row['Best'], row['Login']))

    async def update(self, aseco, _data=None):
        if not self.reader._session or not self.reader._connected:
            return
        from .maniaplanet import POLICY
        for player in aseco.server.players.all():
            login, session = player.login, self.reader._session
            key = (login, session)
            if (not safe_login(login) or login == aseco.server.serverlogin or login == 'lan' or login.startswith('lan_')
                    or self._players.get(login, {}).get('session') == session or key in self._player_inflight
                    or monotonic() < self._next_player_try.get(login, 0)):
                continue
            identity = player_identity(player)
            job = JobEnvelope.capture(aseco.capture_job_context(login=login), identity)

            async def operation(envelope, sid=session):
                data = envelope.payload()
                return await self.reader._request(aseco, 'dedimania.PlayerConnect', sid,
                                                  data['Login'], data['NickName'], data['Path'], data['IsSpec'])

            async def apply(result, name=login, sid=session, request_key=key, identity=identity):
                self._player_inflight.discard(request_key)
                if sid != self.reader._session:
                    return
                try:
                    if result.status != 'completed':
                        raise EligibilityError('request failed: ' + result.failure_label)
                    status = player_status(result.value, name)
                except EligibilityError as error:
                    self._next_player_try[name] = monotonic() + 30
                    logger.warning('[Dedimania MP] Player eligibility unavailable for %s: %s', name, error)
                else:
                    self._players[name] = dict(status, session=sid, identity=identity)
                    connected = aseco.server.players.get_player(name)
                    if connected is not None:
                        connected.dedirank = status['MaxRank']
                    logger.debug('[Dedimania MP] Player eligibility confirmed for %s: banned=%s, max rank=%d',
                                 name, status['Banned'], status['MaxRank'])

            outcome = aseco.jobs.service('mp4_dedimania', POLICY).submit(
                job, operation, apply, current_map=False, dedupe_key='player:' + login, revision_guard=False)
            if outcome == Admission.ACCEPTED:
                self._player_inflight.add(key)
            else:
                break

    async def disconnect(self, aseco, player):
        self._players.pop(player.login, None)
        self._next_player_try.pop(player.login, None)

    async def _ghost(self, aseco, login, score):
        root = await file_io(replay_directory, aseco)
        folder = root / '.pyxaseco-dedimania'
        if not folder.resolve().is_relative_to(root.resolve()):
            raise ReplayError('Unsafe Dedimania replay directory')
        await file_io(folder.mkdir, parents=True, exist_ok=True)
        filename = uuid4().hex + '.Replay.Gbx'
        path = folder / filename
        relative = '.pyxaseco-dedimania/' + filename
        try:
            if await aseco.client.query('SaveBestGhostsReplay', login, relative) is not True:
                raise ReplayError('Dedicated server did not save the ghost replay')
            def read():
                with path.open('rb') as stream:
                    return stream.read(MAX_REPLAY_BYTES + 1)
            data = await file_io(read)
            return await file_io(check_replay, data, self._info['UId'], login, score, self._info['NbCheckpoints'])
        finally:
            await file_io(path.unlink, missing_ok=True)

    async def finish(self, aseco, params):
        if (not self._valid or not self._info or not self.reader.dedi_db.get('RecsValid')
                or aseco.score_phase or aseco.warmup_phase or aseco.server.challenge.uid != self._info['UId']
                or not isinstance(params, (list, tuple)) or len(params) < 3):
            return
        login, score = params[1:3]
        if not safe_login(login) or type(score) is not int or not 8000 <= score <= 2_147_483_647:
            return
        status = self._players.get(login, {})
        if status.get('session') != self.reader._session or status.get('Banned') is not False:
            logger.debug('[Dedimania MP] Finish not staged: player eligibility is unavailable or restricted')
            return
        from apps.platform_core.checkpoints import checkpoints
        cp = checkpoints.get(login)
        checks = list(cp.curr_cps) if cp is not None else []
        if not eligible_checks(checks, score, self._info['NbCheckpoints']):
            return
        rows = self.reader.dedi_db['Challenge'].get('Records', [])
        old = next((row for row in rows if row['Login'] == login), None)
        old_rank = rows.index(old) + 1 if old is not None else 0
        if old is not None and score >= old['Best']:
            return
        rank = 1 + sum(row['Best'] <= score for row in rows if row['Login'] != login)
        if rank > max(self.reader.dedi_db.get('ServerMaxRank', 30), status['MaxRank']):
            return
        try:
            top1_required = not self._top1 or score < self._top1
            async with asyncio.timeout(20):
                raw = await aseco.client.query('GetValidationReplay', login)
                validation = await file_io(check_replay, raw, self._info['UId'], login, score, len(checks))
                ghost = await self._ghost(aseco, login, score) if top1_required else b''
            if top1_required and not ghost:
                raise ReplayError('A new world record requires a ghost replay')
            if len(validation) + len(ghost) > MAX_BATCH_BYTES:
                raise ReplayError('Replay evidence exceeds the submission size limit')
        except Exception as error:
            reason = str(error) if isinstance(error, ReplayError) else type(error).__name__
            logger.warning('[Dedimania MP] Finish for %s not staged: %s', login, reason)
            return
        previous = self._pending.get(login)
        total = self._pending_bytes + len(validation) + len(ghost)
        if previous:
            total -= len(previous['validation']) + len(previous['ghost'])
        if total > MAX_PENDING_BYTES or (login not in self._pending and len(self._pending) >= 500):
            logger.warning('[Dedimania MP] Replay capture capacity reached; finish not staged')
            return
        player = aseco.server.players.get_player(login)
        if player is None:
            return
        row = {'Login': login, 'NickName': player.nickname, 'Best': score, 'Checks': checks,
               'Game': 'TM2', 'NewBest': True}
        self._pending[login] = {'record': row, 'validation': validation, 'ghost': ghost,
                                'player': player_identity(player), 'top1_required': top1_required}
        self._pending_bytes = total
        rows = [record for record in rows if record['Login'] != login] + [row]
        rows.sort(key=lambda record: (record['Best'], record['Login']))
        for position, record in enumerate(rows, 1):
            record.update(Pos=position, rank=position)
        self.reader.dedi_db['Challenge']['Records'] = rows
        if rank <= self.reader.dedi_db.get('LimitRecs', 10):
            action = ('gained the' if old_rank > rank else 'secured his/her') if old else 'claimed the'
            message = (f'{{#server}}>> {{#highlite}}{player.nickname}{{#dedirec}} {action} '
                       f'{{#rank}}{rank}{{#dedirec}}. Dedimania Record!  '
                       f'Time: {{#highlite}}{format_time(score)}{{#dedirec}}')
            if old:
                message += f' $n({{#rank}}{old_rank}{{#highlite}} -{format_time(old["Best"] - score)}{{#dedirec}})'
            await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))
        await aseco.release_event('onDedimaniaRecord', row)
        self.last_submission_status = 'Staged until map end'
        logger.info('[Dedimania MP] Staged %s: %d ms, rank %d; upload at map end', login, score, rank)

    async def end_map(self, aseco, _data=None):
        if not self._pending or self._info is None:
            return
        items = sorted(self._pending.values(), key=lambda item: (item['record']['Best'], item['record']['Login']))
        best = items[0]
        payload = {'map': dict(self._info), 'times': [
            {'Login': item['record']['Login'], 'Best': item['record']['Best'],
             'Checks': ','.join(map(str, item['record']['Checks']))} for item in items],
            'players': [item['player'] for item in items],
            'validation': base64.b64encode(best['validation']).decode('ascii'),
            'ghost': base64.b64encode(best['ghost']).decode('ascii'), 'top1_required': best['top1_required']}
        await self._retainer(aseco).retain(payload, map_uid=self._info['UId'])
        self._pending.clear()
        self._pending_bytes = 0
        self.last_submission_status = 'Queued for submission'
        logger.info('[Dedimania MP] Queued %d time(s) for map %s', len(items), self._info['UId'])

    @staticmethod
    def _prepare_replays(payload):
        info, times = payload['map'], payload['times']
        if not times or len(times) > 500 or not 2 <= info['NbCheckpoints'] <= 10000:
            raise ReplayError('Invalid submission metadata')
        for row in times:
            checks = [int(value) for value in row['Checks'].split(',')]
            if (not safe_login(row['Login']) or type(row['Best']) is not int or row['Best'] < 8000
                    or not eligible_checks(checks, row['Best'], info['NbCheckpoints'])):
                raise ReplayError('Invalid submitted finish/checkpoints')
        if times != sorted(times, key=lambda row: (row['Best'], row['Login'])):
            raise ReplayError('Submission times are not sorted')
        best = times[0]
        replays = []
        for key in ('validation', 'ghost'):
            value = payload[key]
            if not isinstance(value, str) or len(value) > MAX_REPLAY_BYTES * 4 // 3 + 4:
                raise ReplayError('Invalid replay payload size')
            data = base64.b64decode(value, validate=True)
            if key == 'validation' or data:
                check_replay(data, info['UId'], best['Login'], best['Best'], info['NbCheckpoints'])
            replays.append(data)
        validation, ghost = replays
        if sum(map(len, replays)) > MAX_BATCH_BYTES or (payload['top1_required'] and not ghost):
            raise ReplayError('Missing or oversized replay evidence')
        return {'map': info, 'times': times,
                'replays': {'VReplay': Binary(validation), 'VReplayChecks': '',
                            'Top1GReplay': Binary(ghost) if ghost else ''}}

    async def shutdown(self, aseco, _data=None):
        await self.end_map(aseco)
        if self._delivery is None:
            return
        deadline = monotonic() + 20
        while aseco.jobs.running:
            pending = await aseco.record_outbox.list(OWNER, state='pending', limit=1)
            sending = await aseco.record_outbox.list(OWNER, state='sending', limit=1)
            if not pending and not sending:
                break
            if monotonic() >= deadline:
                logger.warning('[Dedimania MP] Shutdown upload wait expired; unsent work needs retained-outbox inspection')
                break
            await self._delivery.tick(aseco)
            await asyncio.sleep(.1)
