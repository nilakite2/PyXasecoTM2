"""Controller-lane playlist snapshot with explicit invalidation."""

from __future__ import annotations
import time


PAGE_SIZE = 500


def _identity(row):
    return row.get('UId') or row.get('Uid'), row.get('FileName')


async def read_playlist_pages(query, *, method='GetChallengeList', overlap=False):
    rows, offset = [], 0
    while True:
        batch = await query(method, PAGE_SIZE, offset)
        if not isinstance(batch, list) or len(batch) > PAGE_SIZE:
            raise RuntimeError('Invalid playlist response')
        page = [dict(row) for row in batch]
        if overlap and rows:
            if not page or _identity(page[0]) != _identity(rows[-1]):
                raise RuntimeError('Live playlist changed while paging; retry the operation')
            rows.extend(page[1:])
        else:
            rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        # MP faults at offset == count; begin the next page at the last known map.
        offset = len(rows) - int(overlap)


class Playlist:
    def __init__(self, aseco):
        self.aseco = aseco
        self._rows = None
        self._loaded_at = 0.0
        self.revision = 0
        self.by_uid, self.by_filename = {}, {}
        aseco.register_event('onTracklistChanged', self.invalidate)
        aseco.register_event('onChallengeListModified', self.invalidate)

    async def invalidate(self, _aseco, _param=None):
        self.revision += 1
        self._rows = None
        self.by_uid, self.by_filename = {}, {}

    async def snapshot(self, *, refresh=False):
        if refresh or self._rows is None or time.monotonic() - self._loaded_at >= 60:
            rows = await read_playlist_pages(
                self.aseco.client.query, overlap=getattr(self.aseco, 'is_maniaplanet', False) is True
            )
            if self._rows is not None and self._rows != rows:
                self.revision += 1
            self._rows = rows
            self._loaded_at = time.monotonic()
            self.by_uid = {row.get('UId', row.get('Uid', '')): row for row in rows}
            self.by_filename = {row.get('FileName', ''): row for row in rows}
        return [dict(row) for row in self._rows]


def playlist(aseco):
    service = aseco.services.get('playlist')
    if service is None:
        service = Playlist(aseco)
        aseco.services.register('playlist', service, owner='core')
    return service
