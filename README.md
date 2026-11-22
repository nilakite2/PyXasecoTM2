# PyXasecoMP v1.0

PyXasecoMP is a TrackMania 2 server controller based on PyXaseco 1.7. It
supports **scripted Time Attack on ManiaPlanet 4**, including RPG and Trial
servers. It provides local records and checkpoint times, ManiaExchange map
search and jukebox tools, admin commands, and customizable in-game widgets.
ShootMania, non-Time Attack modes, and TrackMania Forever are not supported
by this edition.

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

## In Game

- `/help` lists commands. Finish a run and try `/pb`, `/recs`, or `/cptms`.
- `/mxinfo` shows the current map's ManiaExchange listing; `/mxrecs` shows
  its MX times. Admins can use `//add <id>` or [`//addfile <file>`](map_imports/README.md).
- `/hud` adjusts your HUD, and F8 hides or restores supported widgets.
- `//apps` manages apps and server-wide widget settings. The MP controller
  reads [`apps.mp.toml`](apps.mp.toml), not `apps.toml`.

External integrations such as Dedimania, MXKarma, Discord, and PYXA Stats
have their own settings or credentials. See the comments in `.env.example`
and the individual app guides for setup.

## Upgrading From MP 0.1

Back up your controller and database. For servers using the full-ZIP updater,
enable `[apps_manager.updates].enabled` in `apps/apps_manager/app_defaults.toml`,
run `//apps updates`, and review `//apps update controller` before confirming.
The updater requires matching releases from both providers. It preserves live
configuration and locally modified files. Review any retained code before
restarting with `//pyres`.

## Credits And License

See [app credits](APP_CREDITS.md) and the [GPLv3 license](LICENSE).
