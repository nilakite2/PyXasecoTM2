# PYXA Stats

## Purpose

Optional publisher for server snapshots and recent local records.
Separate from Server Info and the local ServerStats history app.

## Commands

No direct chat command. `/server` shows the enabled integration's health.

## Configuration

`app/pyxa_stats` is enabled in the shipped MP loadout. For an existing custom
loadout, enable it in `apps.mp.toml` and remove it from the disabled list.
Set `PYXASECOMP_STATS_API_BASE` to your website's HTTPS origin (no `/api` suffix).
`PYXASECOMP_STATS_API_TOKEN` is optional, just as in TMF: leave it blank when the
website does not require a token. If the website has `PUBLIC_STATS_WRITE_TOKEN`
configured, use that value. No destination/token is preconfigured.
Use `app_defaults.toml` or `//apps config pyxa_stats` for publishing,
heartbeat timing and the number of recent records.

The MP bridge deliberately does not reuse TMF stats credentials from generic
environment variables. These settings authorize only the stats receiver; never
use your dedicated SuperAdmin, masterserver or database password here.

For dedicated login `nila_dev`, the website reporting key is `mp4-nila_dev`.
The bridge also sends the actual login, `platform=MP4`, and the active title ID.
The website uses the real login/title for ManiaPlanet links, and the reporting
key for lookups/events so TMF `nila_dev` remains a separate server. For MP event
rotation use `mp4-nila_dev` in the website's event server-login field.

## Changes And Limits

- Sends server/map metadata, version, player/spectator counts and recent local
  record events, including player logins/nicknames.
- Publishes previous/current/next map metadata. Previous means the last different
  map observed during this controller session; it is unknown immediately after
  startup. Next prefers the active Jukebox queue, then the dedicated server.
- If FlexiTime is active in TimeAttack, publishes its timer at initialization,
  then at 75%, 50%, 25% and zero remaining. Pause/resume, manual time changes and
  score-phase changes also correct the timer. Normal presence heartbeats reuse
  the last sample and its age rather than resampling each second.
- Websites can count down locally between timer corrections. Map/queue changes
  trigger an updated heartbeat. No UI or FlexiTime dependency is required.
- This publishes informational rotation/timing, not full remote event standings.
- Does not send IP addresses, complete rosters or server/database passwords.
- MP public PBs retain their full millisecond precision. The website keeps
  legacy TMF formatting and uses ManiaPlanet links for MP servers.
- API routes remain `/api/public-stats/heartbeat` and
  `/api/public-stats/recent-record`.
- Disabling publishing pauses queued records; ambiguous submissions are not
  automatically resent.
- The app must be loaded to publish. Server Info alone does not send statistics.

## Credits

Nila / PyXaseco project.
