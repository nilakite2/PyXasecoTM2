# Import MX Map IDs

Put `maps.txt` in this folder on the machine running PyXasecoMP:

```text
PyXasecoMP/
  config.toml
  map_imports/
    maps.txt
```

Use the folder beside the controller's active `config.toml`, not the game's
`UserData/Maps` or `MatchSettings` folder. Create `map_imports` if needed.

Save the list as UTF-8 text. Use commas, spaces or newlines between MX IDs;
`#` starts a comment. Example:

```text
92209,98994,99351
99432
101669 101896 # More MX maps
```

As an unlocked MasterAdmin, run `//addfile maps.txt` (or
`/admin addfile maps.txt`). The limit is 500 IDs and 32 KiB per file.
Invalid text is rejected before the import starts; repeated IDs and maps
already in the live rotation are skipped.

These are limits per import file, not on the server's map count. Use multiple
files for larger imports. PyXasecoMP reads the live rotation in pages; the
dedicated server's own limits and MatchSettings file-size checks still apply.

One import runs at a time, feeding the normal download queue one map at a time.
Normal MX, dedicated-server and duplicate checks still apply, as does the
optional `mp_strict_titlepacks` setting when enabled. Accepted
maps are permanently added to the selected MatchSettings, but are not added to
the play-next jukebox. If the server is running a non-default preset after a
controller restart, select that preset with `/ms` before importing. The owner
gets a final summary; rejected IDs and reasons are in the controller log.

Use `//addfile cancel` to stop. Leaving the server, losing admin access,
changing the selected MatchSettings, or restarting the controller also stops
the batch. Maps already saved stay saved; importing the same list again skips
maps already in the rotation.
