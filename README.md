# PyXasecoMP v1.1

PyXasecoMP is a TrackMania 2 server controller based on PyXaseco 1.7. It
supports **scripted Time Attack on ManiaPlanet 4**, including RPG and Trial
servers. It provides local records and checkpoint times, ManiaExchange map
search and jukebox tools, admin commands, and customizable in-game widgets.
ShootMania, non-Time Attack modes, and TrackMania Forever are not supported
by this edition.

Version 1.1 removes unused TMF code, adds opt-in dedicated-server recovery
with automatic unsafe-transition learning, and keeps large Dedimania replay
batches out of the record queue payload.

## Install

You need Python 3.12, a ManiaPlanet 4 TrackMania dedicated server on the
same host, and a MySQL or MariaDB database separate from any TMF database.
Start the dedicated server with a scripted Time Attack playlist and note its
XML-RPC port and SuperAdmin credentials.

From the controller folder, install the dependencies:

```powershell
py -3.12 -m pip install -r .\requirements.txt
```

Create a `.env` from [`.env.example`](.env.example). Set `MP_DB_NAME`,
`MP_DB_USER`, and `MP_DB_PASSWORD` for the new database. Give that database
account schema and data privileges on its own database only. The controller
creates its tables on first startup; no SQL import is needed for a fresh install.

Set `PYXASECOMP_RPC_LOGIN` and `PYXASECOMP_RPC_PASSWORD` using the dedicated
server's `<authorization_levels>`, not the ManiaPlanet account password. Set
`tmlogin` under `[masteradmins]` in [`config.toml`](config.toml) to the in-game
login or logins that should have controller admin access. Keep `.env` private.

Replace `5000` below with the XML-RPC port from your dedicated server config.
The first command checks the connection without touching the database. The
second starts the controller.

```powershell
py -3.12 .\main.py --probe --port 5000
py -3.12 .\main.py --port 5000
```

Add `--prompt-password` to enter your XML-RPC password interactively or
`--debug` for more detailed logs. `//pyres` restarts only the controller and
keeps its startup arguments.

For map-change diagnostics, `py -3.12 .\main.py --watch --port 5000 --seconds 120`
prints map and match callbacks in the order received. It does not start the
controller or connect to the database. Use the manual startup above; the legacy
TMF installer and its supervised service launcher do not support this edition.

## In Game

- `/help` lists commands. Finish a run and try `/pb`, `/recs`, or `/cptms`.
- `/mxinfo` shows the current map's ManiaExchange listing; `/mxrecs` shows
  its MX times. Admins can use `//add <id>` or [`//addfile <file>`](map_imports/README.md).
- `/hud` adjusts your HUD, and F8 hides or restores supported widgets.
- `//apps` manages apps and server-wide widget settings. The MP controller
  reads [`apps.mp.toml`](apps.mp.toml).

External integrations such as Dedimania, MXKarma, Discord, and PYXA Stats
have their own settings or credentials. See the comments in `.env.example`
and the individual app guides for setup.

## Unsafe Map Transitions

Recovery is off by default. In `config.toml`, enable `[mp_recovery]`.
Unsafe pairs are learned automatically; `unsafe_pairs` can stay empty.
Pairs are directional. The controller prefers eligible live playlist maps
from `bridge_uids`. The fallback is MX `267668` with UID
`A_XjtQOrBTbuiNA3d7_FwitQ5F9`. If that map isn't live, recovery holds the
current map while downloading and checking it, then adds it temporarily.
Use `bridge_mx_id = 0` to disable the MX fallback. To change it, set both
`bridge_mx_id` and `bridge_mx_uid`.

The controller waits for the bridge to load before skipping to the original
target without consuming its Jukebox entry early. Once that target loads,
recovery removes its own temporary map from the rotation and disk. Pre-existing
playlist maps are left alone. MatchSettings saves are blocked while the
temporary map is in use. If no safe bridge can be prepared, the controller
refuses the skip rather than leaving the unsafe target armed.

Unexpected GBX disconnects wait for the same server and title to return.
On Windows, set `dedicated_batch = "auto"` when the controller is installed
one folder below the server launcher and the launcher shares the parent
folder's name. Otherwise, use a path relative to `config.toml` such as
`dedicated_batch = "../ServerName.bat"`, or use an absolute path. Recovery
runs that one `.bat` or `.cmd` from its own folder, never a wildcard match.
If the dedicated `.exe` is not a same-named sibling, set
`dedicated_executable` to its path so recovery can identify the running
process. For direct launch without a batch file, set the executable
and its `dedicated_arguments` instead. Recovery only launches after the
previously identified process is gone and the local RPC port can be bound,
with at most two launches in one recovery chain. It won't terminate a process
that is still running. If a process or port check is inconclusive, recovery
keeps waiting and rechecks it. Leave both paths blank if an external supervisor owns it.

Events are written to `unsafe_transitions_log.txt`, not to the regular
controller log. After an observed transition is interrupted and a dedicated
restart is verified, the controller records the ordered pair as unsafe
before resuming the queued map. A disconnect followed by a reconnect to the
same running process does not mark a pair. Learned pairs are scoped to the
server login and title. To forget a learned pair, stop the controller and
remove its matching `unsafe` or older `suspected` log entries and any manual
override in `unsafe_pairs`. MatchSettings is not rewritten by recovery.

## Upgrading

Back up your controller and database. For servers using the full-ZIP updater,
enable `[apps_manager.updates].enabled` in `apps/apps_manager/app_defaults.toml`,
run `//apps updates`, and review `//apps update controller` before confirming.
The updater requires matching releases from both providers. It preserves live
configuration and locally modified files. Review any retained code before
restarting with `//pyres`.
Keep `unsafe_transitions_log.txt` and `.pyxaseco-data/` when updating manually:
they hold learned map pairs, recovery evidence, and queued record data.

## Credits And License

See [app credits](APP_CREDITS.md) and the [GPLv3 license](LICENSE).
