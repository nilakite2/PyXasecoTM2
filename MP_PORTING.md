# PyXasecoMP App Port

Target: ManiaPlanet 4 TrackMania, scripted Time Attack, without a titlepack
allow-list. ShootMania is excluded. Keep the standard SQL
table names in a separate MP database. The shipped MP loadout is
[`apps.mp.toml`](apps.mp.toml); it is not the inherited TMF loadout.

## Current Status (2026-11-22)

See [MP_PARITY.md](MP_PARITY.md) for the prioritized TA backlog and evidence,
and [MP_BASELINE.diff](MP_BASELINE.diff) for the raw comparison against the current
`PyXaseco_v1.7` source. This section supersedes historical pending items below.

- **Confirmed in-game:** persistent local records, Trial display and `/trialinfo`,
  `/xlist`, explicit MX add, bulk `//addfile` on a working batch, MXKarma, CP Live,
  panel controls, and the initial score-screen formatting. All four MP instances
  reported to the stats site. The latest MX `/recpanel` update, HTTPS links, and
  full-tile Join Discord click target also have user confirmation.
- **Latest live confirmations:** 700+ maps reloaded almost instantly, and
  checkpoint tracking continued correctly after `//pyres`. Planets billing
  works. The dual-listed PB was saved locally and submitted to tmrpg.com and
  Dedimania; tmtrialgy.com finish-detail submission also works. Dedimania
  replay submission was confirmed on the test map.
- **Optional dev spot checks:** hour-long times render as `H:MM:SS.mmm` and
  start closer to the rank without widening panels. Shared windows now use the
  XASECO2 pagination icons. Keep exact 500-row playlist boundaries and uncertain
  provider/bill outcomes as regression checks, not open acceptance items.
- **Implemented, awaiting dev spot check:** MP rejects non-TA presets before
  loading them and preserves a verified active preset across `//pyres`. If the
  active filename cannot be established, persistent writes and strict cleanup
  stop until an admin loads the intended file. Trial rank/tie behavior now
  matches 1.7 and valid RPG/Trial ranks carry through to the MP score screen.
- **Remaining live checks:** scope them to script-dependent TA controls
  (`//endround`, respawn and FlexiTime if used) and any future runtime changes.
  The confirmed record and billing paths do not need another acceptance pass.
- **Deferred:** non-TA modes, automatic Planets payouts and Karma lottery,
  random MX downloads, HUD import/export acceptance, and MP release packaging.

The user updated `pyxaseco/maniaplanet_client.py` and supplied dedicated-server
files under `UserData`:

```text
UserData/Scripts/PyXaseco_TimeAttack.Script.txt
UserData/Maps/MatchSettings/MatchSettings.txt
```

The client accepts the custom `PyXaseco_TimeAttack.Script.txt` name. The supplied
MatchSettings selects that script, sets `S_TimeLimit = 0`, and sets
`S_StartCountdownDuration = 0`. Treat this playlist and script as user-maintained
server files, not generic defaults to overwrite on other installations.
The script extends the standard TrackMania base mode; this is still a Time
Attack integration, not an implementation of other modes.

The current priority is TA/RPG/Trial servers. Non-TimeAttack gameplay (including
round/team/lap/scoring callbacks) remains deferred. Removing the TA guard or
selecting another script alone does not provide working mode parity. Older batch
notes below describe the state when those changes were made.

### Native Map-Change Crash

The RPG and Trial crash dumps point to the dedicated process loading a Stadium
sky/scene asset from `dedicated_TMStadium.pak`. Multiple maps are involved; the
dumps do not prove the archive is corrupt, a controller bug, or an actual change
of the running `/title=`. BigBang (GBX.NET) will investigate the native crash
separately from controller parity. If reproducing on dev,
compare the exact source/destination pair in both directions, the destination
after a cold start, and the same transition with the controller stopped. Leave a
reproducibly failing transition out of live rotation rather than blocking all
cross-title maps. An engine crash requires dedicated-process recovery, not just
`//pyres`; any watchdog should limit retries if the same map fails again.

## Planets Commands And Track Overview Follow-up

MP uses `/planets` for the server balance, `/donate <amount>` for a native
confirmation bill, and `/pay <login> <amount>` (also `//pay`) for authorized
server payouts. Payouts have a single-use, 30-second confirmation and recheck
permissions on click. Donation totals are updated only on a paid bill callback.
Pending bill tracking is in memory; do not restart with outstanding transactions
or assume an unacknowledged RPC did not create a bill. Automatic payout and
lottery features are not enabled by this change. The user confirmed manual
Planets billing works in-game.

MP Track Overview uses inline text links, and its MX images use the `?.jpg`
hint used by the MP Records Eyepiece reference. MX returned a JPEG with that
hint; actual rendering is still an in-game check. The MXKarma reminder title
and badge stay inside the bar. No change to map imports or record score cards.

## Optional TA Titlepack Admission

`[server].mp_strict_titlepacks` is **off by default**. In that mode the dedicated
validates compatibility, and the controller does not archive maps based on their
titlepack. When enabled, MP checks the downloaded/installed GBX header against
the active title. It allows that exact custom title plus its official base game
(Stadium, Canyon, Valley or Lagoon). For a custom title, the official base is
inferred from the dedicated server's current environment at initial sync; an
unknown base is not guessed. The dedicated server still performs its normal
map/script compatibility validation. There is no hard-coded Stadium/RPG allow-list.

With strict filtering enabled, startup, map changes and playlist changes scan the selected
`settings.default_tracklist` preset and live rotation. Confirmed foreign entries
are appended/deduplicated into sibling `MatchSettings.exclude.txt`, then removed
from the active preset and rotation. Map files and SQL records remain untouched.
Unreadable/unverified entries remain unchanged with a warning; new adds/queues
with unreadable title metadata are refused. Cleanup refuses an empty rotation.
No map skip is forced. The exclusion archive is hidden in `/ms` and cannot be
loaded/saved through controller playlist calls. Revision-checked updates create
backups; the archive is written before removing source entries.

Deployment and the short live check list: [TA_TITLEPACK_DEPLOYMENT.md](TA_TITLEPACK_DEPLOYMENT.md).

The server RPC does not expose the active MatchSettings filename. A successful
controller load records the exact name. The `//pyres` handoff is single-use and
requires matching dedicated identity, uptime and live rotation. On a cold start,
only a unique local TA playlist with the same live map filenames is selected.
If two files match or none does, use `/ms` or `//readtracklist <file>` before
`//addfile`, `//replacemap`, or saving to the active preset without a filename.
Use the controller for preset changes; external loads with the same rotation
cannot be distinguished by filename. Strict titlepack filtering stays optional.

## Compatibility Rule

Use PyXaseco 1.7 on TMF as the reference for each port. Preserve the HUD
layout and state changes, chat wording, command names, syntax, and
permissions. Adapt callbacks, RPCs, event registration, and rendering
syntax at the MP boundary rather than redesigning the in-game behavior.
When an integration changes providers, the labels and commands may reflect
the new provider, such as ManiaExchange and `/mxinfo` in place of TMX and
`/tmxinfo`.

Use Current Track and Local Records in `apps/mp_panels/app.py` as the
reference for clickable HUD panels: the action quad matches the visible
panel bounds, text stays passive, and separate buttons keep their own actions.

## XAseco2 Records Eyepiece Reference

The XAseco2 1.03 copy in `Other Controllers/xaseco2_103/xaseco2` includes
Records Eyepiece 1.1.1 (`plugins/plugin.records_eyepiece.php` and
`records_eyepiece.xml`). Use it to cross-check TM2 widget styles, click
targets, and race-to-score screen changes. PyXaseco 1.7 remains the source
of truth for player-facing behavior, and the existing MP4 callback adapter
owns event delivery. The older plugin uses legacy ManiaLink markup and
explicitly disables its Dedimania widget in Script mode; it does not validate
that provider for our scripted Time Attack target.

## MP4 Test Order

1. Start with the shipped loadout. Verify local records and splits, `/me`,
   `/cp`, `/mycp`, `/cplive`, `/bcps`, `/ztrack local 1`, and the full-panel
   click targets. Check a respawn, a give-up, and spectating another player.
2. The shipped `apps.mp.toml` enables Admin, Apps Manager, Jukebox, Voting,
   JFreu, Platform UI and Eyepiece. After a controller restart, check
   `//help`, `/menu`, `/elist`, `/hud`, `//apps config ui`, and the score preview.
   Use your MP player login under `[masteradmins]` in `adminops.toml` for
   MasterAdmin commands, not the dedicated server's login or RPC username.
   Current Track and Local Records are drawn by Eyepiece, using its layout
   settings and the player's HUD preset. Click Current Track for the track
   overview or Local Records for the record browser (including My PB).
   `mp_panels` is an optional fallback for installs that disable `ui`.
   MP's own script HUD remains on; TMF-only native HUD flags are not sent.
   Confirm the Menu, Karma details, and the score-screen vote reminder live.
3. Use a test playlist to check `/jukebox`, `/skip`, `//restart`, and
   `//add <MX ID>` or `//replacemap <MX ID>`. Keep a backup of MatchSettings
   first. MX downloads need the local Maps path returned by the dedicated
   server. MX metadata, the file UID, and dedicated map validation are checked
   before insertion; a same-UID replacement does not delete existing records.
   `/xlist` and `/mxsearch` both browse MX. `//addfile maps.txt` reads from the
   controller's `map_imports/` folder. Test shuffle, cleanup and bulk import on
   dev before using them on a live playlist. Random MX downloads and non-TA
   mode switching are not supported.
4. Test `flexitime` separately. Set `S_TimeLimit` to `0` in the MP Time Attack
   MatchSettings before enabling it. FlexiTime refuses to run with a positive
   native limit and does not change MatchSettings itself. Verify `/tl`, pause,
   resume, and exactly one advance at expiry. Restore a positive native limit
   if you disable FlexiTime and want automatic rotation.

## Optional Services

| App | MP status |
| --- | --- |
| `discord` | Optional. Set up the intended MP webhook and verify delivery separately. |
| `ui` / MXKarma | Local by default. Set `PYXASECOMP_MX_KARMA_KEY` in the live `.env` to the MXKarma key issued for the dedicated login and restart PyXasecoMP. It uses the MXKarma API2 protocol used by PyPlanet. Global average and count are shown separately; newly cast or changed votes are submitted at map transitions, with no bulk upload of older local votes. Check the log for `[MXKarma] Connected`. |
| `records_dedimania` | TM2 lookups and eligible replay-backed TA submissions, enabled by `PYXASECOMP_DEDI_CODE`. That is a TM2 Dedimania code, not the dedicated password. Validation evidence is captured at finish; uploads run at map end. The TM2 endpoint uses HTTP. |
| `pyxa_stats` | Configure the receiver for `mp4-<server-login>`. Set `PYXASECOMP_STATS_API_BASE` (HTTPS); `PYXASECOMP_STATS_API_TOKEN` is optional unless the website requires it. Does not fall back to TMF credentials. |
| `records_trial`, `records_rpg` | Enabled in the MP loadout. Trial uses the MP-aware website API and RPG uses its UID-checked records/replay-upload flow. Trial has display priority on dual-listed maps while both delivery paths remain active. Provider coverage and live upload confirmation are separate checks; these apps are no longer blocked solely for lacking an MP contract. |

Apps Manager can edit `apps.mp.toml` but cannot download or apply TMF release
packages. No TMF database, website, or dedicated configuration was changed.

## Files Changed In This Batch

- Controller and config: `.env.example`, `apps.mp.toml`, `pyxaseco/maniaplanet_client.py`, `pyxaseco/maniaplanet_controller.py`.
- Checkpoints and HUD: `apps/platform_core/checkpoints.py`, `apps/checkpoint_tools/listing.py`, `apps/checkpoint_tools/live.py`, `apps/best_cp_times/best_cp_times_v2.py`, `apps/ztrack/overlay.py`, `apps/mp_panels/app.py`, `apps/records_local/records_widget.py`, `apps/platform_ui/hud_layout.py`, `apps/platform_ui/record_browser.py`.
- Eyepiece: `apps/ui/app.py`, `apps/ui/callbacks.py`, `apps/ui/challenge_widget.py`, `apps/ui/config.py`, `apps/ui/handlers/events.py`, `apps/ui/karma.py`, `apps/ui/menu.py`, `apps/ui/menu_layout.py`.
- Maps and admin: `apps/tmx/maniaplanet.py`, `apps/jukebox/backend.py`, `apps/jukebox/jukebox.py`, `apps/jukebox/tmx_jobs.py`, `apps/voting/backend.py`, `apps/admin/command_router.py`, `apps/admin/map.py`, `apps/admin/matchsettings.py`, `apps/admin/replace_map.py`, `apps/admin/server.py`, `apps/admin/stalker_tools.py`, `apps/apps_manager/commands.py`, `apps/apps_manager/service.py`, `apps/apps_manager/views.py`.
- Timer and external services: `apps/flexitime/flexitime.py`, `apps/records_dedimania/app.py`, `apps/records_dedimania/commands.py`, `apps/records_dedimania/maniaplanet.py` (new), `apps/pyxa_stats/service.py`.
- Tests and notes: `tests/test_maniaplanet_controller.py`, `tests/test_maniaplanet_exchange.py`, `MP_PORTING.md`.

## MP4 Menu and Karma Follow-up

- Runtime: `pyxaseco/maniaplanet_client.py`, `apps/platform_ui/presentation.py`, `apps/ui/karma.py`, `apps/ui/karma_mx.py` (new), `apps/server_info/overview.py`.
- Config, notes and tests: `.env.example`, `MP_PORTING.md`, `tests/test_maniaplanet_controller.py`, `tests/test_maniaplanet_karma.py` (new).

## MP4 Eyepiece Race Panels

- Runtime files: `apps/ui/challenge_widget.py`, `apps/ui/app.py`, `apps/records_local/records_widget.py`, `apps/mp_panels/app.py`, `pyxaseco/maniaplanet_client.py`.
- The shipped `apps.mp.toml` now disables the fallback. Existing installs can keep their loadout if `app/ui` is enabled.

## MP4 Widget Movement and MX Labels

Best Finishes now uses the configured vertical position without a hidden cap.
The `//apps config bestfinishes` position and scale controls are regression-tested
with positive and negative 0.1, 1, and 10 steps, including runtime reloads.

MXKarma's race and score widgets now draw their background, header, cups, rating
and personal vote buttons on one page. Older separate cups and marker pages are
explicitly cleared. Race and score previews use this same renderer. Modern uses
the standard Eyepiece header sizing, with no interactive header skin.

Player-facing provider names, menu entries, HUD editor labels, map badges, and
command descriptions use MX/MXKarma. `/mxinfo`, `/mxrecs`, and `/mxsearch` are
the public commands. Old TMX info/record commands remain hidden compatibility
commands. Internal `app/tmx`, TOML keys and HUD preference identities are retained;
do not rename folders or database columns.

The supplied Eyepiece layout values and `platform_ui.panels.records.offset_y = 9.0`
are applied. Other supplied Platform UI values already matched.

### Runtime Files To Copy

- `apps/bestfinishes/widget.py`
- `apps/ui/karma.py`, `apps/ui/menu.py`, `apps/ui/menu_layout.py`
- `apps/ui/race_preview.py`, `apps/ui/score_preview.py`, `apps/ui/widgets/bar_widgets.py`
- `apps/platform_ui/player_hud.py`, `apps/platform_ui/panels.py`
- `apps/apps_manager/service.py`, `apps/admin/map.py`
- `apps/tmx/app.py`, `apps/tmx/service.py`, `pyxaseco/maniaplanet_ui.py`
- Settings: `apps/ui/app_defaults.toml`, `apps/platform_ui/app_defaults.toml`

Tests changed: `tests/test_maniaplanet_controller.py`, `tests/test_controller_ux.py`.
After copying, restart PyXasecoMP. Check Best Finishes movement in `//apps`,
MXKarma in Classic and Modern, a locked/unlocked/already-cast vote, and both
race and score previews. No live server or external vote submission was used
for the automated checks.

### MX Queue Message Follow-up

Copy `apps/jukebox/tmx_jobs.py` and restart PyXasecoMP. Queue acknowledgements,
duplicate/full/stopping/cooldown messages, cancellations and download errors now
use MX on ManiaPlanet. TMF retains TMX wording. Regression coverage was added in
`tests/test_maniaplanet_exchange.py`; all 142 tests pass.

## Nations and Checkpoint Widget Follow-up

Copy these four runtime files, then restart PyXasecoMP:

- `pyxaseco/models/__init__.py`
- `apps/players/players.py`
- `apps/checkpoint_tools/live.py`
- `apps/best_cp_times/best_cp_times_v2.py`

Nation extraction now follows XAseco2's `includes/types.inc.php`: a path such as
`World|Europe|Slovakia` resolves to Slovakia/SVK, not Europe/EUR. The continent
remains part of the full zone shown in player details. Existing player rows are
corrected by normal player loading/reconnection; countries for offline players
are not guessed from the erroneous continent codes.

CP Live resets and redraws after MP map loading without waiting for a TMF-only
`BeginRound` callback. Returning from score to play can also resume its UI
without discarding current checkpoint times or a player's collapsed preference.
Explicitly disabling CP Live still keeps it disabled.

Best CP Times draws its backdrop and rows on the same MP page, clearing the
older standalone background page. The full-panel ProgressBar skin is replaced
with the standard card skin. Classic and Modern are covered, including row
refreshes and clearing at scores.

All 149 automated tests pass. New coverage is in
`tests/test_maniaplanet_controller.py`. Live checks: confirm your nation after
restart/rejoin, skip or restart a map and check CP Live returns, and inspect
Best CP Times with new checkpoints in both Classic and Modern.

## Debug and Controller Restart Follow-up

The initial MP probe runner did not forward the inherited `--debug`/`--perf`
options and incorrectly treated `//pyres` as a fatal connection loss. Both now
use the shared controller behavior. `main.py` starts the controller by default;
explicit `--probe` and `--watch` remain diagnostics with no controller/DB startup.
MP server verification, local-host restriction and separate MP credentials remain.

Copy these three runtime files, then manually restart the old MP controller once:

- `main.py`
- `pyxaseco/maniaplanet_probe.py`
- `pyxaseco/maniaplanet_controller.py`

The batch launcher is unchanged and already forwards additional arguments.
Start `PyXasecoMP.bat --debug` (optionally add `--perf`), then use `//pyres`.
The controller should save/close its resources, release the RPC connection and
instance lock, and re-execute with the same interpreter and original arguments
after two seconds. It must not restart the map or stop the dedicated server.
An existing restart request also survives a run-loop error, as in the TMF runner;
errors without a restart request remain errors rather than triggering a restart.

New regression coverage: `tests/test_maniaplanet_lifecycle.py`. Documentation
also changed in `README.md`. All 162 automated tests pass. Tests use simulated
connections, not the live server.

## Banner, Admin and Best Finishes Backgrounds

The three MP HUD surfaces now match CP Live's background: `BgsPlayerCard/BgCard`
in Classic and the same header color/transparency as CP Live in Modern presets.
The MP adapter normalizes the existing backgrounds rather than adding another
overlay. Best Finishes' native v3 page also receives full-length MP color values.
CP Live itself, widget geometry, icons, actions, and stored HUD settings are unchanged.
This change does not alter the TMF rendering path or require edited TOML defaults.

Copy these two runtime files, then use `//pyres`:

- `pyxaseco/maniaplanet_client.py`
- `apps/platform_ui/presentation.py`

Tests also changed in `tests/test_maniaplanet_controller.py`. Coverage compares
actual delivery of Banner, empty/populated Best Finishes and every Admin template
against CP Live across the installed Classic/Modern palettes, preserving geometry,
button actions and image quads. Confirm the three backgrounds visually in-game
after restart, including Best Finishes before and after a finish.

All 165 automated tests pass; live visual confirmation remains pending.

## Legacy Race Callback Debug Noise

`TrackMania.PlayerCheckpoint` and `TrackMania.PlayerFinish` are now recognized as
intentionally ignored duplicates on MP, instead of logged as unhandled. Script
waypoints remain the authoritative source for checkpoints, finishes and splits;
the legacy callbacks must not cause duplicate records or reset an active attempt.
Genuinely unknown callbacks remain visible with `--debug`.

Copy `pyxaseco/maniaplanet_controller.py`, then use `//pyres`. Regression tests
were added in `tests/test_maniaplanet_controller.py`. Check that the repeated
legacy messages stop and a driven checkpoint/finish still updates normally.

All 167 automated tests pass, including single-delivery script finish/split tests.

## Native Game HUD / Custom UI

MP4 scripted modes now receive visibility changes through
`TriggerModeScriptEventArray` / `Trackmania.UI.SetProperties`; TMF `<custom_ui>`
alone does not control those script modules. The existing per-player block is
still sent separately for personal chat/window/preview preferences. A personal
override never changes the server-wide script policy for other players.

References checked: XAseco2 `includes/manialinks.inc.php` and
`plugins/plugin.records_eyepiece.php`, the added Best Checkpoint Times 1.0.2
plugin, PyPlanet's `core/ui/ui_properties.py`, and UASECO's modescript handler.
The MP protocol is documented at
https://github.com/maniaplanet/script-xmlrpc/blob/master/XmlRpcListing.md#trackmaniauisetproperties.

Existing Custom UI settings drive the map-info, checkpoint-list, round-score,
chat and full-scoreboard visibility. `checkpoint_ranking = false` was added to
`[ui.custom_ui]` for the additional native checkpoint-ranking overlay. Missing
keys default to false for this setting, so replacing a live layout TOML is not
required. Preserve your existing positions and other custom settings.

With the shipped Eyepiece/Best CP Times configuration, duplicate map information,
checkpoint list, checkpoint ranking and small round-score panel are hidden.
The native timer, speed/distance, checkpoint-time display, chat and Tab scoreboard
are not hidden by default. Best CP Times' `custom_ui` switch can take ownership
of the checkpoint list or release it back to Eyepiece configuration; it also works
without Eyepiece. Visibility requests are cached, reapplied on map load, and only
the controller-owned visibility attributes are released at shutdown. Positions
and unrelated script UI properties are not reset.

Copy these five runtime files, then use `//pyres`:

- `pyxaseco/maniaplanet_ui.py`
- `pyxaseco/maniaplanet_controller.py`
- `apps/ui/handlers/events.py`
- `apps/ui/config.py`
- `apps/best_cp_times/best_cp_times_v2.py`

Defaults also changed in `apps/ui/app_defaults.toml`. Tests changed in
`tests/test_maniaplanet_controller.py`; new focused coverage is in
`tests/test_maniaplanet_custom_ui.py`. All 180 automated tests pass.

Live checks: finish and cross checkpoints, rejoin, skip/restart a map and use
`//pyres`; the unwanted native ranking panel should stay hidden. Confirm CP Live
and Best CP Times still draw, and the timer, speed, chat and Tab scoreboard remain
available. Test visibility changes in `//apps config ui` and disabling Best CP
Times' `custom_ui` option. No live dedicated server was accessed for these tests.

## TM2 Dedimania Submissions

The MP Dedimania adapter was still read-only. It now stages eligible finishes,
updates the shared records view and `/dedinew`, and submits a sorted batch at map
end (or graceful controller shutdown). This follows XAseco2/PyPlanet's TM2
`dedimania.SetChallengeTimes` protocol, not TMF's `ChallengeRaceTimes` API.

Player eligibility/bans and server/player rank limits are checked. TA maps need
at least two reported checkpoints (including finish), author time >=10 seconds,
and finish time >=8 seconds. New results require complete, consistent splits,
a matching dedicated validation replay, and a matching ghost for a prospective
world record. Already equal/faster external times are not resubmitted. Periodic
lookups preserve locally staged improvements until map-end submission.

The replay reader checks bounded GBX header metadata without modifying replays
or claiming to simulate/validate driving physics. References: XAseco2's
`GBXReplayFetcher` and Dedimania plugin, PyPlanet's Dedimania adapter, and GBX.NET's
`CGameCtnReplayRecord.HeaderChunk03093000`. Final validation belongs to Dedimania.
Protocol/eligibility reference: https://www.gamers.org/tm2/Features_103.html.

Copy these seven runtime files, then use `//pyres`:

- `apps/records_dedimania/app.py`
- `apps/records_dedimania/maniaplanet.py`
- `apps/records_dedimania/mp_submission.py` (new)
- `apps/records_dedimania/mp_replays.py` (new)
- `apps/records_dedimania/commands.py`
- `pyxaseco/core/gbx_client.py`
- `pyxaseco/maniaplanet_client.py`

Keep the current `PYXASECOMP_DEDI_CODE`. New optional setting in `.env.example`:
`PYXASECOMP_REPLAYS_DIR` is the absolute dedicated `UserData/Replays` directory,
needed only when it cannot be resolved from `GameDataDirectory`. Do not replace
the live `.env` with the example. Ghost saves use unique names in
`Replays/.pyxaseco-dedimania`; only the temporary file created for that request is
removed. MP accepts replay replies up to a bounded 40 MiB packet size; TMF retains
its 4 MiB limit.

Replay-backed batches use the shared retained outbox. Preparation/authentication
failures do not perform a record write; ambiguous sends are retained as uncertain
and are never blindly retried. Old-map replies cannot repaint another map's HUD.
Only `[Dedimania MP] Submission processed` confirms a well-formed API response;
the final record/rank still depends on the provider. Graceful shutdown waits up
to 20 seconds. The outbox is memory-only unless `aseco.durable_record_delivery`
is enabled in `config.toml`; unresolved memory-only work does not survive exit.

Also changed: `.env.example`, `apps/records_dedimania/README.md`, and new regression
tests in `tests/test_maniaplanet_dedimania_submit.py`. Tests use synthetic headers
and simulated RPC/HTTP, including new #1 ghosts, multiple players, rank limits,
wrong evidence, bans, map changes, and ambiguous writes. Live submission has not
been attempted by the coding agent.

The user subsequently confirmed a Dedimania record and replay on the test map.
For future regressions, drive an eligible improved time and confirm `Staged` in the log and
the live records. End/skip the map and wait for `Queued` followed by `Submission
processed`, then check `/dedirecs` after a fresh provider lookup. If replay-path
or eligibility warnings appear, address them before assuming a time was sent.

All 204 automated tests pass. These are local protocol/metadata regression tests,
not proof of acceptance by the live Dedimania service.

## Eligibility And Score-Screen Recovery

The November 19 log shows a finish rejected before staging because player
eligibility was unavailable. The previous validator accepted only exact Python
boolean/integer fields. It now also normalizes explicit numeric/text boolean
flags and integral rank values. A mismatched login, missing/ambiguous ban flag,
invalid rank or banned player still cannot authorize a submission. Both initial
eligibility checks and retained submission preparation use this validation.
Warnings now identify the rejected field/type or request failure class without
printing the response, session or private code. Debug logging also shows a
successful eligibility check. The original log does not contain enough detail
to prove which response field or request failed on the live service.

Fresh LocalDB schemas lacked four fields used by score lists: `mostfinished`,
`visits`, `roundpoints` and `winningpayout`. Startup now adds missing fields with
zero defaults and preserves existing fields/values. This requires database ALTER
permission; do not reset the database. It does not reconstruct historical
statistics or introduce counter tracking. Existing maps, players, records and
personal UI settings remain intact. Aggregate toplist queries also explicitly
group their selected name/login columns for strict SQL configurations.

Failed score queries now have a bounded ten-second per-query backoff, cannot
trigger a service-wide cooldown for unrelated healthy queries, and display
`Data unavailable` instead of appearing to be loading indefinitely. Warnings
include the MySQL error number and a query fingerprint, not SQL parameters or
credentials. `ManiaPlanet.BeginMatch` is recognized and emitted as `onBeginMatch`
without resetting map state or active player attempts a second time.

Copy these five runtime files from `PyXasecoMP_v0.1-DEV`, then use `//pyres`:

- `apps/records_dedimania/mp_submission.py`
- `apps/platform_core/localdb.py`
- `apps/ui/score_data.py`
- `apps/ui/toplists.py`
- `pyxaseco/maniaplanet_controller.py`

No TOML, `.env`, layout or SQL reset is needed. The restart applies additive
schema changes automatically. Other changed files are this document,
`tests/test_maniaplanet_dedimania_submit.py`,
`tests/test_maniaplanet_controller.py`, and new
`tests/test_maniaplanet_score_recovery.py`. The existing Best Finishes movement
test now reads the configured starting position rather than assuming X=35;
the user's X=37.2 setting has not been changed.

Live checks:

1. Restart and check for successful player eligibility in debug output. If it
   still fails, retain the new warning with its specific reason.
2. Drive another eligible improved time. Look for `Staged`, then end/skip the
   map and look for `Queued` and `Submission processed`. The previously rejected
   finish is not recovered from the local database or submitted retrospectively.
3. Check the score screen: repeated OperationalError/ServiceCooldown messages
   should be gone. Any remaining warning now includes the database error number.
4. Confirm `ManiaPlanet.BeginMatch` no longer appears as unhandled, and a new
   run still records each checkpoint and finish once.

All 216 automated tests pass using simulated database/RPC/provider responses.
No live database migration or Dedimania submission was performed by the agent.

## RPG Title Startup

The startup/watch allow-list now accepts `RPG@tmrpg` as well as
`TMStadium@nadeo`, case-insensitively. Previously the initial Stadium-only guard
rejected the RPG title immediately after successful RPC authentication. Other
titles remain blocked. The existing scripted-mode and `TimeAttack.Script.txt`
checks remain in place; allowing the title does not claim compatibility with
uninspected custom mode scripts or other game modes.

Copy these four runtime files, then start the controller normally:

- `pyxaseco/maniaplanet_callbacks.py`
- `pyxaseco/maniaplanet_client.py`
- `pyxaseco/maniaplanet_controller.py`
- `pyxaseco/maniaplanet_probe.py`

Use `/title=RPG@tmrpg` in the dedicated server launch arguments. PyXasecoMP
detects the title from the server; it needs no new launcher argument or database
reset. The startup error/help wording now refers to the supported titles rather
than a Stadium-only test server. This change does not widen the existing
Stadium-specific ManiaExchange download/search filters.

Also updated: `README.md`, this document, `tests/test_maniaplanet_callbacks.py`
and `tests/test_maniaplanet_controller.py`. All 220 tests pass, including simulated
RPG callback subscription and full shared-controller startup. Live RPG titlepack
behavior has not been tested by the agent.

## TrackMania Titles And CP Live Rows

This supersedes the Stadium/RPG restrictions above. Controller startup no longer
uses a title allow-list. Stock ShootMania titles and custom ShootMania titles
identified by the current map's Storm environment or ShootMania map type are
rejected. The existing scripted Time Attack requirement remains; this is not
an implementation of additional game modes or arbitrary custom mode scripts.

MX downloads no longer require TMStadium/RPG titlepack labels or the Stadium
environment. `/mxsearch` searches the TrackMania MX site without a titlepack
filter. Before insertion the dedicated server must still accept the map for its
active title/script. Size limits, GBX/UID verification and transactional playlist
handling are unchanged. Expected map refusals now return a clear chat message
without triggering the download service's outage cooldown. Unexpected transport
and parser failures retain the usual protections. MP queue messages use MX.

MXKarma now sends the active server title instead of always sending
TMStadium@nadeo. The compatibility packmask is derived from the current map
environment rather than always claiming Stadium. CP Live spectator row click
targets use translucent backgrounds and hover feedback, including after personal
Modern styling; their actions and positions are preserved.

Copy these eight runtime files from `PyXasecoMP_v0.1-DEV`, then restart:

- `pyxaseco/maniaplanet_callbacks.py`
- `pyxaseco/maniaplanet_probe.py`
- `pyxaseco/maniaplanet_controller.py`
- `pyxaseco/maniaplanet_client.py`
- `apps/tmx/maniaplanet.py`
- `apps/tmx/service.py`
- `apps/jukebox/tmx_jobs.py`
- `apps/ui/karma_mx.py`

No configuration replacement or SQL reset is required. Also changed: README,
this document, and the obsolete title/search assertions in
`tests/test_maniaplanet_callbacks.py` and `tests/test_maniaplanet_exchange.py`.
Only a syntax check was run for this patch, not the full suite or live validation,
as requested. Live checks: add/search an MX map, spectate with CP Live in Classic
and Modern, and confirm MXKarma still loads on the selected title.

## PYXA Stats Website Bridge

The shipped MP loadout now enables `app/pyxa_stats`. It remains inactive until
`PYXASECOMP_STATS_API_BASE` (HTTPS website origin) is configured. Like TMF,
`PYXASECOMP_STATS_API_TOKEN` is optional unless the website requires a write token.
Publishing remains API-only; this app needs no access to the website database.

Heartbeat/PB reports now include `platform`, `dedicated_login`, and `title_id`.
The existing `mp4-<login>` reporting namespace is retained, so TMF/MP instances
with the same dedicated login never share public-server rows. Timer/rotation
reporting follows the existing FlexiTime sampling behavior. Presence changes
request a fresh snapshot; normal heartbeats remain bounded/coalesced. Heartbeat
responses must acknowledge `ok: true`; clean shutdown makes a bounded five-second
attempt to finish the offline report. A crash still relies on website staleness.

Controller deployment: copy `apps/pyxa_stats/service.py`; enable
`app/pyxa_stats` in your live `apps.mp.toml` if missing; add the MP stats base
(and token only if required) to your existing `.env`. Preserve other loadout/custom settings and
never replace the live `.env` with `.env.example`. No controller database change
is needed. Also changed: `apps/pyxa_stats/app_defaults.toml`, `.env.example`, and
`apps/pyxa_stats/README.md` (comments/setup instructions), plus this document.

Website changes and the complete copy list are documented in
`tmtrialgy-web&scrapper/pyxaseco-website-stats/PYXASECOMP_STATS_DEPLOYMENT.md`.
No website deployment, live API write, credential change or database access was
performed by the agent. Validation is intentionally limited to focused checks,
not the full regression suites or a live server run.

## Current Track Time Text And Remaining Work

The screenshot's smaller time was the inherited Eyepiece label scale of 0.8;
the date uses 1.0. It was not caused by the Compact HUD preset. MP's legacy-page
adapter now renders that Current/Next Track time at 1.0, including race/score
previews, without changing frame positions, personal HUD density
or the TMF copy. Copy `pyxaseco/maniaplanet_client.py` and use `//pyres`.
Only syntax and a focused XML conversion check are required for this adjustment;
visual confirmation remains on the dev server.

Current remaining scope, rather than repeating earlier completed steps:

1. Finish the visual parity pass: font proportions, long names/times, alignment
   and hit targets in Classic/Modern, standard/compact/minimal and score screens.
   The follow-up below standardizes the inherited 80/90-percent body labels;
   layout positions remain owner-configured and visual checks remain pending.
2. Validate `records_trial` and `records_rpg` live. Both are now allowed and enabled
   in the shipped MP loadout, using the existing providers. Trial maps must be
   registered as TM2; RPG uses the dedicated UserData/Replays path. Other disabled
   optional apps are not automatically MP-supported.
3. Add game modes beyond scripted Time Attack. The runtime still requires
   TimeAttack.Script.txt; accepting more TrackMania titlepacks did not implement
   Rounds, Team, Laps, Stunts, Cup or arbitrary custom scripts.
4. Finish remaining MP command differences, including random MX downloads and
   explicitly blocked shuffle/endround actions where the mode can support them.
5. Prepare MP-specific release/update packaging. TMF packages remain blocked.
   Final live checks should cover replay-backed Dedimania submission confirmation,
   clean/forced restarts, map changes, spectating/rejoining and cross-server HUD
   transfer. Implemented behavior is not a substitute for unreported live checks.

User-confirmed results so far include MXKarma, explicit MX adds, CP Live, public
reporting from all four MP servers and the website's MP database-statistics page.
Those do not need to be treated as unimplemented work again.

## Trial/RPG, MX Browser And Text Parity Follow-up

MP now renders explicit label scales 0.8/0.9 at 1.0, after personal styling and
legacy conversion. Smaller captions, frame positions, widget dimensions and
personal Compact density are unchanged. Trial/RPG time text retains milliseconds.

The existing Trial HTTP provider and shared Trial database are reused; the MP
controller itself does not connect to that database. Registration uses section
TM2. MP finishes carry game=TM2, validated against the registered map before
writing, and use a distinct retained-delivery sink. Trial server heartbeats use
mp4-<login> to avoid replacing same-login TMF rows. Old TMF finish requests without
the optional game field remain compatible.

RPG keeps the same API, eligible-map lookup, replay upload and cleanup workflow.
Only the MP replay root and delivery sink differ. PYXASECOMP_REPLAYS_DIR can point
to an absolute UserData/Replays folder if automatic resolution is ambiguous.
TRIAL_API_BASE/TOKEN and RPG_API_BASE/TOKEN are optional overrides; existing
provider defaults and empty optional tokens are retained.

/xlist now supports MX name/author search, recent maps and tags, with the existing
info/add/author click actions. It browses TrackMania maps without enforcing a
Stadium/RPG titlepack allowlist; the dedicated server still validates map insertion.

Full controller/website/sync copy lists and manual checks are in the workspace's
PYXASECOMP_TRIAL_RPG_DEPLOYMENT.md. Dedimania stability, HUD transfer and widget
placement were not changed. Seven focused offline checks and syntax checks passed;
no live controller/API writes, sync jobs or database operations were run.

## Checkpoint Recovery After Controller Restart

The MP run gate previously discarded checkpoints/finishes unless it had observed
that run's StartLine callback. After //pyres, already-running players therefore
could not update CP Live, BestCPs, the UI counter or the shared checkpoint store.

After initial server sync, already-connected players can resume from their next
valid script waypoint's complete split list, including a direct finish. The shared
checkpoint prefix is restored before the usual onCheckpoint event, so all apps
receive the same current checkpoint. This does not poll progress or restart runs.
It does not redraw the pre-restart position until a new waypoint arrives.

Recovery is one-time per player, requires consistent indices/times, and is revoked
by a normal start, give-up, disconnect, warmup or map change. Duplicate finishes
remain ignored. For this restart fix alone, copy
pyxaseco/maniaplanet_controller.py and use //pyres. Live check: restart the controller
mid-run, cross the next checkpoint, then finish; verify the HUD resumes and only
one finish is recorded. The focused offline test covers recovery and duplicate/
malformed/give-up handling; no live server was accessed.

## Millisecond Record Columns

Classic and Modern record cards size the rank column from the visible ranks and
keep a compact four-unit time column. Times use the game's narrow ($n) formatting
before any further text-size reduction, leaving more space for nicknames without
making ordinary time rows shorter. Numeric labels use a fitted text size when
the configured card is too narrow. Full time values and nickname formatting are
preserved. Card positions, outer widths, heights, row spacing, highlights, actions
and personal HUD density are unchanged. The same sizing applies to Local,
Dedimania, Trial/RPG and other shared-provider record cards, plus the Local/Dedi/
average-time score-screen lists. TMF rendering remains unchanged.

Copy all six runtime files, including the new shared helper:

```text
apps/platform_ui/record_layout.py
apps/platform_ui/modern.py
apps/platform_ui/uistyle.py
apps/ui/widgets/records_common.py
apps/ui/widgets/score_widgets.py
apps/records_local/records_widget.py
```

Then use //pyres. No app_defaults.toml, HUD profile or website change is needed.
Also changed: this document and tests/test_mp_trial_bridge.py. A focused offline
check verifies non-overlapping columns for rank 1647 and time 1:39:19.023 across
Classic, Modern and score-screen XML, preserving the configured card width and
position. Final visual confirmation remains on the live/dev server.

## Dual-listed Trial Replay Submission (MP Only)

Trial Records has display priority over RPG Records when both providers recognise
the current map. This applies to the shared HUD, /estat, pagination and score
screen. The Trial app exposes a read-only, UID-checked cached snapshot through its
registered service, avoiding network requests during provider selection.

Normal finish details continue to tmtrialgy.com using the unchanged Trial finish
hook and delivery sink. Qualifying local PBs continue through RPG's existing
replay capture/upload flow to tmrpg.com, even when the Trial panel is selected.
The provider confirmed it will list Trial maps on the same records endpoint.
Upload confirmation updates the RPG cache but does not produce a second RPG
record announcement while Trial owns the panel. Explicit /rpgrecs remains usable.

Copy these five runtime files and use //pyres:

```text
pyxaseco/app_services.py
apps/records_trial/service.py
apps/records_rpg/service.py
apps/ui/record_views.py
apps/ui/widgets/score_widgets.py
```

Both app/records_trial and app/records_rpg must be enabled, as in the current
shipped MP loadout. No website, database, .env or TMF-controller change is needed.
Also changed: apps/records_rpg/README.md, tests/test_mp_trial_bridge.py and this
document. Four focused offline checks cover map-scoped cache/priority, separate
retention of Trial details and RPG replay payloads, announcement suppression and
score-screen provider selection. No live uploads or API/database writes were run.

The user subsequently confirmed the dual-listed PB and tmtrialgy.com submission.
If touching this flow again, check the Trial panel before/after a PB, both providers,
the score screen and /estat. Use an RPG-only and a Trial-only map as regressions.
The existing uploader's map-eligibility,
local-PB and retained-failure policies are unchanged; this is not historical
backfill or upload of every non-PB finish.

## Admin and Panel Command Parity Pass

Removed the shared panel runtime's TMF-only guards for TrackMania MP. Personal
admin/records/vote selection, listing, off/default, numeric/picker selection,
startup defaults, stats panels and HUD panel discovery now use the same handlers
as TMF. Admin picker selections recheck the panel ability and admin unlock state.
Panel choices continue using the existing players_extra storage, without a schema
or configuration change. MP records-panel PB/local/Dedimania times retain milliseconds
and its exchange button dispatches /mxrecs.

The previously missing server-default handler is implemented in both MP and the
TMF 1.7 development source: //style, //admpanel, //donpanel, //recpanel and //votepanel.
Use a template name, off, or list. The default picker dispatches back through the
admin router so permissions and the admin lock are checked again. These legacy
commands change runtime defaults, not personal selections or settings.toml; edit
settings.toml for a permanent server-default change. //panel is still the personal
admin panel, distinct from //admpanel.

MP //endround uses Trackmania.ForceEndRound, as in UASECO/PyPlanet. //shuffle uses
the MP remove/add-list API, validates the complete rotation and attempts recovery
to its previous order on failure. Both operations wait for acknowledgement before
the shared admin handler reports success. Download controls map to the MP method
names; respawn controls use S_AllowRespawn rather than inactive legacy settings.
Referee password no longer has a TMF-only guard. Force-show status reads the MP
server and ALL uses its native value. Cleanup now preserves MP map entries and
script settings, while retaining mandatory backups, MasterAdmin permissions,
confirmation, revision checks and database isolation protections.

Copy these MP runtime files together and restart with //pyres:

```text
apps/platform_ui/panels.py
apps/admin/map.py
apps/admin/server.py
apps/admin/cleanup.py
pyxaseco/maniaplanet_client.py
```

For the shared default-handler/permission fix on TMF 1.7, copy only
PyXaseco_v1.7/apps/platform_ui/panels.py to the matching TMF instance.
Do not put the MP file into TMF. No settings, app loadouts, SQL, website files or
saved HUD positions need replacing. Also changed: tests/test_mp_admin_ui_parity.py
and this document. Focused offline tests use fake RPC/DB objects, not live cleanup,
payments or server administration.

Suggested dev-server checks: //panel list/off/default, selected templates after
//pyres, /recpanel list (including Inline), /votepanel list/off/default and an actual
vote, /hud's legacy panels, and //admpanel list followed by //panel default. Check
//shuffle and //endround only on the dev server, plus //acdl and //disablerespawn.

At the time of the admin pass, non-TimeAttack script modes and Planets payments
were outstanding. Non-TA is still deferred. For the later manual Planets
implementation and its live acceptance checks, see Current Status above.

## Score Screen Formatting

Score-screen record previews now use the live record-list columns and the MP
millisecond formatter. The top/statistical lists share the record score header,
including its flat background override and legacy background normalization.
MP numeric totals fit their fixed column and nickname boxes stay inside the card.
Round Score's main entries use the same fixed rank/time/name layout and standard
body size, formatting raw milliseconds instead of previously formatted TMF strings.
Small side points badges remain unchanged. Empty Round Score markup is valid XML.
Preview styling receives the MP context before panels are combined, including the
same MP-specific panel styling as live delivery. OG preview names are unchanged.

Copy these MP runtime files together and use //pyres:

```text
apps/ui/score_preview.py
apps/ui/toplists.py
apps/ui/widgets/score_widgets.py
```

No config, position, width, height, SQL, website, or TMF-source change is needed.
Also changed: tests/test_mp_score_formatting.py and this document. Five focused
offline checks compare live/preview records, shared headers/background overrides,
numeric column bounds, Round Score text/precision, and MP preview styling context.
Live status (2026-11-20): the user confirmed this formatting pass works in-game.
Retain //apps scorepreview and an actual score screen as regression checks for
future UI changes, rather than treating this pass as still awaiting validation.
