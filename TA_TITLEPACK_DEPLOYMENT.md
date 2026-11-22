# TA Titlepack Guard

Strict titlepack filtering is **off by default**. The dedicated server still
validates maps for the active title and script, so compatible maps made for
another titlepack can be added. With filtering off, PyXasecoMP does not archive,
remove, or hide maps just because of their titlepack.

To opt in, put this key under the existing `[server]` section in the live
`settings.toml` and restart with `//pyres`:

```toml
mp_strict_titlepacks = true
```

Setting the key to `false` or omitting it disables strict filtering. Previously
archived maps are not restored automatically; add them normally if desired.
The exclusion file remains protected from normal playlist load/save commands.

Restart the MP controller with `//pyres` after changing the setting. This policy
does not require a DB migration, website change or a change to TMF. Manual
Planets billing is independent of the titlepack policy.

## Dedicated Server Files

The controller needs local access to the dedicated server's Maps directory, as
reported by `GetMapsDirectory`. It validates Time Attack presets even with
strict titlepack filtering off. On startup, it identifies a preset only when
one local TA file matches the live map list, or when a verified `//pyres` handoff
preserves a previously selected preset. If the active filename is ambiguous,
load it explicitly through `/ms` or `//readtracklist <file>` before persistent
writes. The controller cannot see another process's `/game_settings` argument
or the filename used by an out-of-band XML-RPC load; use the controller to
switch presets while it is running.

With strict filtering enabled, the archive is created automatically beside that preset:
`Maps/MatchSettings/MatchSettings.exclude.txt`.
Never overwrite an existing archive or replace your current MatchSettings or
TA script just to enable filtering.

## Behavior With Strict Filtering Enabled

- `RPG@tmrpg` accepts RPG maps and `TMStadium`/`TMStadium@nadeo` base maps when
  the server's base environment is Stadium. Other custom packs are refused.
- Official Stadium, Canyon, Valley and Lagoon servers accept their own base
  maps, not custom packs or another official environment. ShootMania is excluded.
- Checks cover MX downloads before installation, final add/insert calls
  (including replacements), jukebox selection, map lists, preset loading, and
  next-map selection by filename, index or UID.
  Aliases/fire-and-forget calls use the same checks.
- Existing confirmed foreign map entries are archived first, removed from the
  saved preset, and removed from the live rotation. They are hidden from jukebox
  lists even if the dedicated server refuses removal. Queued foreign entries
  are dropped. If the refused map is next, the controller tries to choose a
  compatible successor without skipping. Check the logs if the dedicated also
  refuses that choice. Map files and all records are retained.
- The archive preserves existing entries and deduplicates by filename. Preset
  game/script settings and comments are retained; startindex is adjusted.
- Local writes use backups and revision checks. Failure to archive prevents
  cleanup. Concurrent preset edits are not overwritten. An archive copy may
  remain after a later failure, intentionally preserving the source.
- Unreadable/unknown existing maps are left unchanged and logged. New additions
  and selections fail closed. If cleanup would empty the saved/live rotation,
  it is refused and logged; correct the preset manually rather than stopping play.
- `/ms` hides the archive; controller calls cannot load or overwrite it as a
  regular preset. External tools or manual dedicated-server RPC calls are not
  intercepted; their live rotation is checked at the next playlist/map event.

## Short Live Check With Strict Filtering Enabled

1. On the RPG server, add one RPG map and one official Stadium map; both should
   work. Adding a different custom title or Canyon map should be refused.
2. With at least one compatible map in the active preset, include one foreign
   map entry and restart. Verify only that entry moves to the archive, with its
   original map file and records still present. Check `[Titlepack]` log messages.
3. Restart again: the archive must not grow duplicate entries. `/ms` should not
   offer the exclusion file. Loading another valid preset should apply the same
   filtering without changing its script settings.

## Offline Checks

`tests/test_mp_titlepacks.py` covers title admission, bounded headers, unreadable
maps, backups, archive preservation/deduplication, concurrent edits, failure
safety, empty-rotation protection, live-only exclusions and final RPC guards.
The focused MX download test also covers foreign-title rejection and temporary
file cleanup. All checks use temporary files/mocked RPC, not live servers or SQL.
