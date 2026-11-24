# Dedimania Records

## Purpose

Fetches world records from Dedimania and submits eligible results. Supplies a
leaderboard window and the Dedimania provider for the shared external-records HUD.

## Commands

| Command | Purpose |
| --- | --- |
| `/helpdedi`, `/dedihelp` | Explain the Dedimania system. |
| `/dedirecs [help\|pb\|new\|live\|first\|last\|next\|diff\|range]` | Browse records or related information. |
| `/dedipb`, `/dedinew`, `/dedilive` | Show your PB, new records or online players' records. |
| `/dedifirst`, `/dedilast`, `/dedinext` | Show leading, last or next-better records. |
| `/dedidiff`, `/dedirange` | Show record differences/range. |
| `/dedicps` | Select Dedimania checkpoint comparison. |
| `/dedistats` | Show track statistics. |
| `/dedicptms`, `/dedisectms` | Show record checkpoint/sector times. |

## Configuration

Optional `app/records_dedimania`; disable it through `//apps`/the loadout and restart
when the service is not wanted. Use `app_defaults.toml`, supported `//apps` fields
and shared Dedimania controller settings. Account credentials belong in `.env`
or the supported legacy configuration, not in public README examples.

### ManiaPlanet Stadium Time Attack

The MP adapter uses the TM2 Dedimania code in `PYXASECOMP_DEDI_CODE`, not the
TMF or XML-RPC password. It captures eligible improvements with their dedicated
validation replay, updates the live records and `/dedinew`, then uploads a batch
at map end. A prospective new #1 also requires a matching best-ghost replay.
Replay checks compare map UID, player identity, time and checkpoint counts;
Dedimania performs the actual validation and decides final acceptance.

Normally the ghost directory is resolved from `GameDataDirectory`. If that is
ambiguous or inaccessible, set `PYXASECOMP_REPLAYS_DIR` to the absolute dedicated
`UserData/Replays` directory. Temporary ghost files are placed in its
`.pyxaseco-dedimania` subdirectory and removed after reading. No existing replay
files are overwritten or deleted.

At map end, upload evidence is staged under `.pyxaseco-data/records/dedimania/`
in the controller folder. The outbox keeps a reference instead of embedding
replay bytes. Confirmed delivery removes its staged file; failed or uncertain
batches keep their files for inspection. Do not delete staging files for
pending or uncertain batches.

Look for `[Dedimania MP] Staged`, `Queued`, and `Submission processed` in the log.
Failures to obtain replay evidence are logged and never replaced with a time-only
upload. Ambiguous writes become uncertain and are not automatically repeated.
The shared retained outbox controls crash/restart persistence; its default is
memory-only. For persistence, use `[aseco] durable_record_delivery = true` in
`config.toml`. Graceful shutdown waits up to 20 seconds for queued work; check the
log before restarting during an outage.

## Changes And Limits

- Optional isolation allows the controller and RPG/Trial apps to run without this
  app's folder. Disabling Dedimania does not disable those independent providers.
- External work uses background delivery. A network error is not an empty record
  list or proof that a submission was acknowledged.
- Dedimania applies its own eligibility and ranking limits; this is not unlimited
  local PB storage and does not cover Stunts records.
- The shared HUD slot may instead display recognised RPG/Trial records;
  the Local Records widget remains separate.
- The legacy API can use unencrypted HTTP. Submissions disclose the relevant
  player/map/record data to Dedimania; enable with that understanding.

## Credits

XAseco Dedimania integration and commands: Xymph, based on FAST.
PyXaseco adaptation: Nila / PyXaseco project.
