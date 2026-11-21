# PyXasecoMP v0.1-DEV

Experimental TrackMania 2 controller based on PyXaseco 1.7. The initial
target is **ManiaPlanet 4 TrackMania, scripted Time Attack**, without a titlepack
allow-list. ShootMania is excluded. This is a separate
development copy, not an upgrade for TMF servers.

## What Runs Today

Use Python 3.12 and a separate ManiaPlanet test server. From this folder:

```powershell
py -3.12 .\main.py --version
py -3.12 .\main.py --probe --host 127.0.0.1 --port 5000
```

The probe uses `PYXASECOMP_RPC_LOGIN` and `PYXASECOMP_RPC_PASSWORD` from
the environment or `.env`. The default login is `SuperAdmin`. It prompts
when no password is configured or when you pass `--prompt-password`.
Use `--login` to override the configured login. It reads the server version, status,
and current map without enabling callbacks, loading apps, or touching a
database. It refuses a server that does not identify itself as ManiaPlanet.

The probe has been verified on `nila_dev`, on MP4 build `2019-10-23_20_00`,
with `TMStadium@nadeo`. On that test host, start a timed callback watch with:

```powershell
py -3.12 .\main.py --watch --host 127.0.0.1 --port 5090 --seconds 300
```

Drive through a checkpoint and finish a run while the watch is active. The
output distinguishes scripted events from legacy callbacks and omits chat
messages. Use this only on the test server: it enables the mode script's
callback output, which can remain enabled after the watch exits. It does not
change game settings, load maps, or save records.

## Run the Shared Controller

`main.py` starts the MP controller by default; `--run` remains accepted.
`--probe` and `--watch` explicitly select diagnostics instead. Use
`PyXasecoMP.bat --debug` or `py -3.12 .\main.py --port 5090 --debug` for debug
logging. `--perf` enables performance summaries. The launcher already forwards
these flags. `//pyres` restarts only the controller, preserving the startup
arguments (including `--debug`), after releasing its connections and instance lock.

Keep the separate `niladevtm2` database and your existing MP `.env`. The
shared LocalDB creates or checks the standard PyXaseco tables on startup,
including `players`, `challenges`, `records`, `players_extra`, and
`rs_times`. Its database account needs schema and data privileges on
**that database only** (including `CREATE`, `ALTER`, `SELECT`, `INSERT`,
`UPDATE`, and `DELETE`). The account from the earlier table-only test may
need its grants updated. Do not import the old test schema for a fresh install.

On the dedicated server host, install dependencies:

```powershell
py -3.12 -m pip install -r .\requirements.txt
```

To carry over your PBs from the first playable build, stop the old controller,
back up `niladevtm2`, then start once with:

```powershell
.\PyXasecoMP.bat --import-test-records
```

The import copies `mp_local_records` into the standard tables. It keeps
equal or faster PBs already in `records` and leaves the old table intact.
Afterward, start normally by double-clicking [PyXasecoMP.bat](PyXasecoMP.bat).
On a fresh database, skip the import.

If authentication fails, verify the login and password in
`<authorization_levels>` in the dedicated server config you actually started
with. These are not the ManiaPlanet master account or MySQL credentials.
To test the credentials without using a saved password or a database:

```powershell
py -3.12 .\main.py --probe --host 127.0.0.1 --port 5090 --login SuperAdmin --prompt-password
```

In game, try `/help`, `/pb`, `/recs`, `/cptms`, and `/sectms`. The Current
Track and Local Records panels use native MP4 ManiaLink. A slower or equal
finish should keep the earlier PB and its splits.
Give up during a run and restart the same map to verify that neither action
saves a partial run. Restart the controller and check that the PB is still
there. A run already in progress when the controller starts does not count.

The controller uses scripted finishes only, even when the dedicated server
reports the same finish through its legacy callback. MP4 Stadium counts the
finish as the last split. Same-map restarts clear attempts without changing
saved records. Probe and watch still work without a database.

The [MP4 loadout](apps.mp.toml) also enables ManiaExchange, Server Info,
Best Finishes and zTrack. Discord webhooks can be enabled separately in
`apps.mp.toml` when the MP server has its own intended webhook configuration.
The remaining priority apps and their porting requirements are tracked in
[MP_PORTING.md](MP_PORTING.md). Unsupported apps are blocked at startup.
Updater downloads remain disabled. Do not install this over TMF or run it
against a TMF database.

### ManiaExchange

The `tmx` app uses the TM2 ManiaExchange v2 API on MP4. Try:

- `/mxinfo` for the current map, or `/mxinfo 101492` for Rome by MX ID.
- `/mxrecs 101492` for its ManiaExchange leaderboard. These are separate from `/recs`.
- `/mxsearch This is Rome` for a Stadium-only map name search.

`/tmxinfo` and `/tmxrecs` still work as aliases. Map details contain the
public page and download link. Adding the downloaded map to the dedicated
server, map-pack handling, and the old TMF video/tracklist features are
separate porting work.

Use Nadeo's ManiaPlanet XML-RPC documentation and UASECO for scripted mode
behavior, PyPlanet as a Python reference, and XAseco2 for legacy workflows.
See [app credits](APP_CREDITS.md) for the inherited code and [GPLv3](LICENSE)
for the license.
