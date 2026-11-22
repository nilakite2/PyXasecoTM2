# PyXasecoMP v0.1-DEV

PyXasecoMP is a Python server controller for **TrackMania 2 on ManiaPlanet 4**.
It is based on PyXaseco 1.7 and targets scripted **Time Attack**, including RPG
and Trial servers. It is not an update for TrackMania Forever, Trackmania 2020,
or ShootMania. Use a separate database for MP.

## Setup

1. Start a ManiaPlanet 4 dedicated server with a supported TrackMania title and
   a Time Attack mode script.
2. Install Python 3.12 or newer and the pinned requirements:

   ```powershell
   py -3.12 -m pip install -r .\requirements.txt
   ```

3. Create a local `.env` from [the example](.env.example). Set
   `PYXASECOMP_RPC_LOGIN` and `PYXASECOMP_RPC_PASSWORD` to an account from the
   dedicated server's `<authorization_levels>`, not its master-server password.
   Leave the RPC password blank to be prompted. Configure `MP_DB_*` for a
   separate MP database. Its user needs schema and data privileges on that
   database only. LocalDB creates or checks the standard PyXaseco tables.
4. Add your **player login** under `[masteradmins]` in
   [adminops.toml](adminops.toml). Choose optional apps in
   [apps.mp.toml](apps.mp.toml).

Use the controller on the dedicated host when importing maps, writing playlists,
or saving replay-backed records. These operations require access to the
dedicated server's local files.

## Run

```powershell
py -3.12 .\main.py --probe --host 127.0.0.1 --port 5000
.\PyXasecoMP.bat --host 127.0.0.1 --port 5000 --debug
```

Use the actual XML-RPC port of your dedicated server. `--probe` only reads
server status and map metadata; it does not enable callbacks or touch MySQL.
`--watch --seconds 60` is a test-server diagnostic that can leave mode-script
callbacks enabled. `//pyres` restarts only the controller and preserves its
launch arguments.

The [optional Time Attack script](UserData/Scripts/PyXaseco_TimeAttack.Script.txt)
and [sample playlist](UserData/Maps/MatchSettings/MatchSettings.example.txt)
are dedicated-server files, not required for the controller's ZIP. Replace the
sample map path with an installed map before loading the playlist. Do not
overwrite an existing dedicated preset.

## In Game

- Local records and splits: `/pb`, `/recs`, `/cptms`, `/sectms`, `/cplive`, `/ztrack`.
- ManiaExchange: `/mxinfo`, `/mxrecs`, `/xlist`, and admin `/mxr`, `//add <id>`,
  `//addfile maps.txt`, or `//replacemap <id>`. Bulk ID files belong in
  [map_imports](map_imports/README.md).
- Playlist controls: `/ms` and `//readtracklist <file>` select a local TA preset.
  If the controller cannot identify the active preset, select it before writing
  to it. [Strict titlepack filtering](TA_TITLEPACK_DEPLOYMENT.md) is optional
  and off by default.
- External services: Trial and RPG records use their own providers. Dedimania,
  MXKarma, Discord webhooks and PYXA Stats have separate configuration. Use
  [the environment example](.env.example) to see which values are optional.
  Manual Planets billing is supported; automatic payouts and non-TA modes are
  not part of this build.

## Updates

MP uses [PyXasecoTM2 Releases](https://github.com/nilakite2/PyXasecoTM2/releases)
and the website's `stabletm2` feed. Update checks are off by default. Both
publishers must agree before a ZIP can be staged. Do not install a TMF package
into this repository or into an MP controller.

## Test and Contribute

```powershell
py -3.12 -B -m unittest discover -s tests -p "test_mp_titlepacks.py"
py -3.12 -B -m unittest discover -s tests -p "test_maniaplanet_exchange.py"
```

These checks use temporary files and mocks, not a live dedicated server or
database. Tests that compare sibling TMF, website, sync or publisher sources
use those checkouts only when present. Keep production settings, credentials,
logs, replays, live playlists and runtime data out of commits.

See [app credits](APP_CREDITS.md) for inherited components and [GPLv3](LICENSE)
for the license.
