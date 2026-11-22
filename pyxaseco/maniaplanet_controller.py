"""Run the shared PyXaseco controller on MP4 TrackMania scripted Time Attack."""

import logging

from pyxaseco import BUILD_LABEL, PRODUCT_NAME
from pyxaseco.core.aseco import Aseco
from pyxaseco.core.gbx_client import GbxError
from pyxaseco.maniaplanet_callbacks import decode
from pyxaseco.maniaplanet_client import map_info
from pyxaseco.maniaplanet_records import RecordsError, import_test_records
from pyxaseco.maniaplanet_runtime import ControllerError, course_from_rpc, safe_login
from pyxaseco.maniaplanet_ui import PAGER_ANSWERS, command_window, restore_script_ui


logger = logging.getLogger(__name__)
APPS = frozenset(('platform_core', 'help', 'records_local', 'players', 'mp_panels',
                  'tmx', 'server_info', 'bestfinishes', 'ztrack', 'discord', 'social_chat',
                  'best_cp_times', 'checkpoint_tools', 'platform_ui', 'ui', 'admin',
                  'apps_manager', 'jukebox', 'voting', 'jfreu', 'flexitime', 'pyxa_stats',
                  'records_dedimania', 'records_trial', 'records_rpg', 'endlesstmxr'))
MP_CALLBACKS = {
    'playerconnect': '_cb_player_connect',
    'playerdisconnect': '_cb_player_disconnect',
    'playerchat': '_cb_player_chat',
    'playerinfochanged': '_cb_player_info_changed',
    'playermanialinkpageanswer': '_mp_manialink_answer',
    'statuschanged': '_mp_status_changed',
    'echo': '_cb_echo',
    'maplistmodified': '_cb_challenge_list_modified',
    'voteupdated': '_cb_vote_updated',
    'billupdated': '_cb_bill_updated',
    'beginmap': '_mp_begin_map',
    'beginmatch': '_mp_begin_match',
    'endmap': '_mp_end_map',
    'endmatch': '_mp_end_match',
    'modescriptcallbackarray': '_mp_script',
}
MAX_SCORE = 2_147_483_647


class ManiaPlanetController(Aseco):
    is_maniaplanet = True
    app_loadout_filename = 'apps.mp.toml'

    def __init__(self, client, report, db, rpc, *, import_records=False, debug=False, performance=False):
        super().__init__(debug=debug, performance=performance, client=client)
        self.register_service('ui/command_window', command_window, owner='core')
        self.register_event('onShutdown', restore_script_ui)
        self.mp_database_config = db
        self._mp_rpc = rpc
        self._mp_report = report
        self._mp_import = import_records
        self._mp_course = None
        self._mp_starts = {}
        self._mp_last_start = {}
        self._mp_resume_players = set()
        self._mp_map_ended = False
        from pyxaseco.maniaplanet_maps import TitleGuard
        self.client.map_guard = TitleGuard(self)
        self.register_event('onSync', self.client.map_guard.restore_preset)
        self.register_event('onShutdown', self.client.map_guard.preserve_preset)
        self.register_event('onSync', self.client.map_guard.sweep)
        self.register_event('onNewChallenge2', self.client.map_guard.sweep)
        self.register_event('onTracklistChanged', self.client.map_guard.sweep)
        self.register_event('onChallengeListModified', self.client.map_guard.sweep)

    def _load_configuration(self, config_path):
        if not super()._load_configuration(config_path):
            return False
        (self.settings.server_ip, self.settings.server_port,
         self.settings.server_login, self.settings.server_password) = self._mp_rpc
        return True

    def _load_app_entries(self, apps_path):
        if not apps_path.is_file():
            raise ControllerError('The MP4 app loadout (apps.mp.toml) is missing.')
        requested = super()._load_app_entries(apps_path)
        supported = {f'app/{app}' for app in APPS}
        blocked = [entry for entry in requested if not isinstance(entry, str) or entry not in supported]
        if blocked:
            logger.warning('Apps not enabled on MP4 in this build: %s', ', '.join(map(str, blocked)))
        return list(dict.fromkeys(['app/platform_core', *(entry for entry in requested
                                                         if isinstance(entry, str) and entry in supported)]))

    @staticmethod
    def supports_app(app_id):
        return app_id in APPS

    async def _connect(self):
        if not self.client.is_connected():
            raise ControllerError('The verified ManiaPlanet connection closed before controller startup.')

    async def _configure_dedicated(self):
        report = self._mp_report
        if report['status']['Code'] != 4:
            raise ControllerError('Wait for the ManiaPlanet server to be in Running - Play state.')
        self.server.game = 'ManiaPlanet'
        self.server.version = report['server'].get('Version') or ''
        self.server.build = report['server'].get('Build') or ''
        await self.client.time_attack_settings()

    async def _prepare_server_sync(self):
        pool = await self.database.get_pool()
        if pool is None:
            raise ControllerError('LocalDB is unavailable. Check the preceding database error.')
        if self._mp_import:
            try:
                imported = await import_test_records(pool)
            except RecordsError:
                raise
            except Exception as error:
                raise RecordsError('Could not import test PBs. Check the database permissions and schema.') from error
            self.console('[PyXasecoMP] Test records inserted or improved: {1}', imported)

    async def _server_sync(self):
        await super()._server_sync()
        # The dedicated keeps running while //pyres restarts the controller.
        # Only these already-connected players may resume a missing start.
        from apps.platform_core.checkpoints import checkpoints
        self._mp_resume_players = set(checkpoints) if self._mp_course else set()

    async def _enforce_runtime_server_options(self):
        # Do not override the MP4 dedicated server's networking or voting settings.
        pass

    async def _send_header(self):
        if self._mp_course is None:
            raise ControllerError('The active map did not supply a valid UID and checkpoint count.')
        self.console_text('{1} v{2}: shared controller ready.', PRODUCT_NAME, BUILD_LABEL)
        await self.client.query_ignore_result('ChatSendServerMessage', f'$z$s$fff{PRODUCT_NAME} $8cf{BUILD_LABEL}$fff ready.')

    def _callback_handler_name(self, method):
        prefix, _, name = method.casefold().partition('.')
        if prefix == 'maniaplanet':
            return MP_CALLBACKS.get(name)
        if prefix == 'trackmania' and name in ('playercheckpoint', 'playerfinish'):
            return '_mp_ignore_legacy_race'
        return None

    async def _mp_ignore_legacy_race(self, _params):
        """Script waypoints drive race data; legacy duplicates must not count twice."""
        return

    async def _cb_player_connect(self, params):
        login = safe_login(params[0]) if params else None
        if login and self.server.players.get_player(login) is None:
            await super()._cb_player_connect(params)

    async def _cb_player_disconnect(self, params):
        login = params[0] if params else ''
        self._mp_starts.pop(login, None)
        self._mp_last_start.pop(login, None)
        self._mp_resume_players.discard(login)
        await super()._cb_player_disconnect(params)

    async def _mp_status_changed(self, params):
        self.prevstatus = self.currstatus
        self.currstatus = params[0] if params else 0
        if self.currstatus in (4, 5):
            self.score_phase = self.currstatus == 5 or self._mp_map_ended
        await self.release_event(f'onStatusChangeTo{self.currstatus}', params)

    async def _mp_manialink_answer(self, params):
        if len(params) >= 3 and safe_login(params[1]):
            try:
                action = int(params[2])
            except (ValueError, TypeError):
                return
            await self._cb_manialink_answer([*params[:2], PAGER_ANSWERS.get(action, action), *params[3:]])

    def _invalidate_attempts(self):
        self._mp_starts.clear()
        self._mp_last_start.clear()
        self._mp_resume_players.clear()

    async def _begin_race(self, params):
        self._mp_course = None
        self._invalidate_attempts()
        info = params[0] if params else await self.client.query('GetCurrentChallengeInfo')
        course = course_from_rpc(info)
        if course is None:
            return
        self.warmup_phase = False
        self._mp_map_ended = False
        await super()._begin_race([map_info(info), False, False])
        self._mp_course = course

    async def _current_challenge_info(self, params):
        return params[0]

    async def _mp_begin_map(self, _params):
        self._mp_course = None
        self._invalidate_attempts()

    async def _mp_begin_match(self, params):
        # Map loading already initializes the race. A match boundary must not reset active attempts again.
        await self.release_event('onBeginMatch', params)

    async def _mp_end_map(self, params):
        data = map_info(params[0]) if params else None
        if not isinstance(data, dict) or data.get('UId') != self.server.challenge.uid:
            return
        await self._mp_end_once([], data)

    async def _mp_end_match(self, params):
        if self._mp_course is None:
            return
        ranks = params[0] if params and isinstance(params[0], list) else []
        await self._mp_end_once(ranks, {'UId': self.server.challenge.uid})

    async def _mp_end_once(self, ranks, data):
        if self._mp_map_ended:
            return
        self._mp_map_ended = True
        self._mp_course = None
        self._invalidate_attempts()
        await self._end_race([ranks, data, self.warmup_phase])

    async def _mp_script(self, params):
        name = params[0].casefold() if params and isinstance(params[0], str) else ''
        if name in ('maniaplanet.warmup.start', 'trackmania.warmup.start',
                    'maniaplanet.warmup.end', 'trackmania.warmup.end'):
            self.warmup_phase = name.endswith('.start')
            self._mp_starts.clear()
            self._mp_resume_players.clear()
            return
        event = decode('ManiaPlanet.ModeScriptCallbackArray', params)
        if not event:
            return
        kind = event['event']
        if kind == 'map_unloading':
            await self._mp_begin_map([])
            return
        if kind == 'map_loaded':
            info = await self.client.query('GetCurrentChallengeInfo')
            course = course_from_rpc(info)
            if course and course.uid == event.get('uid'):
                await self._begin_race([info])
            return
        await self._mp_race_event(event)

    async def _mp_race_event(self, event):
        login = safe_login(event.get('login'))
        course = self._mp_course
        if not login or course is None or self.warmup_phase or self.score_phase:
            return
        player = self.server.players.get_player(login)
        if player is None:
            return
        kind = event['event']
        stamp = event.get('server_time_ms')
        start = self._mp_starts.get(login)
        if kind == 'race_start':
            if stamp is not None and stamp > self._mp_last_start.get(login, -1):
                self._mp_resume_players.discard(login)
                self._mp_last_start[login] = self._mp_starts[login] = stamp
                if start is not None or self._mp_run_needs_reset(player):
                    await self.release_event('onPlayerRunReset', player)
            return
        if stamp is None or (start is not None and stamp <= start):
            return
        if kind == 'give_up':
            self._mp_resume_players.discard(login)
            self._mp_starts.pop(login, None)
            await self.release_event('onPlayerRunReset', player)
            return
        if kind not in ('checkpoint', 'finish'):
            return
        index = event.get('checkpoint_index')
        score = event['race_time_ms']
        if not 0 < score <= MAX_SCORE or index is None:
            if kind == 'finish':
                self._mp_starts.pop(login, None)
            return
        splits = event.get('splits_ms')
        complete_splits = (isinstance(splits, list) and len(splits) == index + 1
                           and 0 <= index < course.checkpoints
                           and all(type(value) is int and 0 < value <= score for value in splits)
                           and splits[-1] == score
                           and all(a <= b for a, b in zip(splits, splits[1:])))
        if start is None:
            if login not in self._mp_resume_players or not complete_splits or stamp < score:
                return
            self._mp_resume_players.discard(login)
            self._mp_starts[login] = stamp - score
            # Ignore a delayed pre-recovery StartLine callback for this run.
            self._mp_last_start[login] = stamp
        if kind == 'checkpoint':
            if index < course.checkpoints - 1:
                if complete_splits:
                    from apps.platform_core.checkpoints import checkpoints
                    cp = checkpoints.get(login)
                    if cp is not None:
                        cp.curr_cps = list(splits[:-1])
                await self._cb_player_checkpoint([player.pid, login, score, 0, index])
            return
        self._mp_starts.pop(login, None)
        if not complete_splits or len(splits) != course.checkpoints:
            return
        from apps.platform_core.checkpoints import checkpoints

        cp = checkpoints.get(login)
        if cp is None or not (player.id and self.server.challenge.id):
            return
        # Use the authoritative final splits, even if an individual waypoint was missed.
        cp.curr_cps = splits[:-1]
        await self._cb_player_checkpoint([player.pid, login, score, 0, index])
        cp.curr_cps = list(splits)
        await self._player_finish([player.pid, login, score])

    def _mp_run_needs_reset(self, player):
        from apps.platform_core.checkpoints import checkpoints

        attempt = checkpoints.get(player.login)
        return bool(attempt and attempt.curr_cps)


async def run_controller(client, report, db, rpc, config_path, *, import_records=False,
                         debug=False, performance=False):
    controller = ManiaPlanetController(client, report, db, rpc, import_records=import_records,
                                       debug=debug, performance=performance)
    try:
        await controller.run(str(config_path))
    except Exception as error:
        if controller.restart_requested:
            logger.error('Run failed while restart was requested; proceeding with controller re-exec (%s)',
                         type(error).__name__)
        elif isinstance(error, GbxError):
            raise ControllerError(f'Dedicated server refused a controller RPC (code {error.code}). See the server log.') from error
        else:
            raise
    finally:
        try:
            await controller.close_background()
        finally:
            try:
                localdb = controller.database.get_service()
                if localdb is not None:
                    await localdb.shutdown(None)
            finally:
                await controller.performance.stop()
    return controller.restart_requested
