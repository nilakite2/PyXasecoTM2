# RPG Records

## Purpose

Integrates the RPG records API at tmrpg.com. Displays recognised maps' records and
uploads replays for qualifying local-record results through the API's upload flow.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/rpgrecs` | Open the current map's RPG leaderboard. | Everyone |

The shared external-records widget opens the same records view when RPG is the
selected provider.

## Configuration

Optional `app/records_rpg`, depending on Platform Core and UI, not Dedimania.
This app currently has no `app_defaults.toml`. `RPG_API_BASE` and `RPG_API_TOKEN`
can be overridden in the controller's existing `.env`; the default base remains
`https://www.tmrpg.com` and the token remains optional. Endpoint paths and replay
settings such as `RPG_SAVE_SUBDIR` remain constants in `service.py`.

## Dual-listed Trial Maps (PyXasecoMP)

When a map is recognised by both providers, Trial Records owns the shared HUD,
score-screen records and the shared `/estat` view. The normal Trial finish
details still go to tmtrialgy.com. In parallel, the existing RPG local-PB replay
capture/upload flow continues to tmrpg.com. Both apps must be enabled, and
tmrpg.com must expose the map through its existing records lookup endpoint.

Widget priority never disables replay submission. These are independent
deliveries, not forwarding from one website to another. Upload confirmation can
refresh the RPG cache without replacing the Trial panel or adding a duplicate
RPG-record announcement. RPG-only maps retain their panel and announcements;
Trial-only maps retain their original behavior. `/rpgrecs` remains available for
explicitly opening tmrpg.com's records on a dual-listed map.

The replay trigger remains a qualifying Local Record/PB, just as for RPG maps;
this does not upload every slower finish or backfill historical replays. Replay
capture, retained delivery, upload confirmation and file cleanup are unchanged.

## Changes And Limits

- Lookups/submissions use background jobs and captured map identity, avoiding
  stale responses overwriting another map's records after a transition.
- Saves best-ghost replays through the dedicated server, then uses the API's
  presigned upload flow. Local dedicated replay-folder access is required.
- Successful uploads can delete their own local replay file; failed delivery is
  not treated as success. Replay storage has file-count/size bounds.
- Player logins/nicknames and replay/record data are sent to the external service.
  An API-compatible server and any required token are prerequisites.
- This is not a direct connection to the website's MySQL database or an import
  of all RPG records into Local Records.

## Credits

PyXaseco integration: Nila / PyXaseco project. Records/API: tmrpg.com / achepta.
