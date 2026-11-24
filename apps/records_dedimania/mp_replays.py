"""Bounded MP replay-header checks, following XAseco2's GBXReplayFetcher."""

import json
import os
from pathlib import Path
import re
import stat
import struct
import xml.etree.ElementTree as ET
from uuid import uuid4
from xmlrpc.client import Binary

from pyxaseco.management.config_store import data_path


MAX_REPLAY_BYTES = 24 * 1024 * 1024
MAX_BATCH_BYTES = 32 * 1024 * 1024
MAX_BATCH_METADATA_BYTES = 64 * 1024 * 1024
MAX_SPOOL_FILES = 1000
MAX_SPOOL_BYTES = 2 * 1024 * 1024 * 1024
SPOOL_HEADER = struct.Struct('<4sIII')
SPOOL_MAGIC = b'DMP1'


class ReplayError(ValueError):
    pass


def _spool_path(root: Path, token: str) -> Path:
    if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token):
        raise ReplayError('Invalid retained Dedimania batch reference')
    return data_path(root, 'records', 'dedimania', token + '.batch')


def spool_batch(root, payload, validation, ghost):
    metadata = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode('ascii')
    if (len(metadata) > MAX_BATCH_METADATA_BYTES or not 17 <= len(validation) <= MAX_REPLAY_BYTES
            or len(ghost) > MAX_REPLAY_BYTES or len(validation) + len(ghost) > MAX_BATCH_BYTES):
        raise ReplayError('Retained Dedimania batch exceeds the evidence limit')
    header = SPOOL_HEADER.pack(SPOOL_MAGIC, len(metadata), len(validation), len(ghost))
    token = uuid4().hex
    path = _spool_path(root, token)
    part = data_path(root, 'records', 'dedimania', token + '.part')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    size, count = len(header) + len(metadata) + len(validation) + len(ghost), 0
    for entry in path.parent.iterdir():
        if not re.fullmatch(r'[0-9a-f]{32}\.(?:batch|part)', entry.name):
            continue
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(info.st_mode):
            count += 1
            size += info.st_size
        if count >= MAX_SPOOL_FILES or size > MAX_SPOOL_BYTES:
            raise ReplayError('Dedimania replay spool is full; existing batches were kept')
    created = False
    try:
        with part.open('xb') as stream:
            created = True
            for block in (header, metadata, validation, ghost):
                stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        part.replace(path)
    finally:
        if created:
            part.unlink(missing_ok=True)
    return token


def read_spooled_batch(root, token):
    path = _spool_path(root, token)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ReplayError('Retained Dedimania batch is not a regular file')
    with path.open('rb') as stream:
        header = stream.read(SPOOL_HEADER.size)
        if len(header) != SPOOL_HEADER.size:
            raise ReplayError('Truncated retained Dedimania batch')
        magic, meta_size, valid_size, ghost_size = SPOOL_HEADER.unpack(header)
        if (magic != SPOOL_MAGIC or not 1 <= meta_size <= MAX_BATCH_METADATA_BYTES
                or not 17 <= valid_size <= MAX_REPLAY_BYTES or ghost_size > MAX_REPLAY_BYTES
                or valid_size + ghost_size > MAX_BATCH_BYTES):
            raise ReplayError('Invalid retained Dedimania batch size')
        meta, validation, ghost = stream.read(meta_size), stream.read(valid_size), stream.read(ghost_size)
        if ((len(meta), len(validation), len(ghost)) != (meta_size, valid_size, ghost_size) or stream.read(1)):
            raise ReplayError('Incomplete or oversized retained Dedimania batch')
    return json.loads(meta), (validation, ghost)


def remove_spooled_batch(root, token):
    _spool_path(root, token).unlink(missing_ok=True)


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0
        self.lookbacks = []
        self.lookback_version = False

    def read(self, count):
        if count < 0 or self.offset + count > len(self.data):
            raise ReplayError('Truncated replay header')
        result = self.data[self.offset:self.offset + count]
        self.offset += count
        return result

    def integer(self):
        return struct.unpack('<I', self.read(4))[0]

    def string(self):
        size = self.integer()
        if size > 1024 * 1024:
            raise ReplayError('Replay header string exceeds limit')
        return self.read(size).decode('utf-8-sig')

    def lookback(self):
        if not self.lookback_version:
            if self.integer() != 3:
                raise ReplayError('Unsupported replay lookback version')
            self.lookback_version = True
        index = self.integer()
        if index == 0xFFFFFFFF:
            return ''
        if index & 0xC0000000 == 0:
            return ''  # Built-in environment identifiers are not needed here.
        index &= 0x3FFFFFFF
        if index == 0:
            value = self.string()
            self.lookbacks.append(value)
            return value
        if index > len(self.lookbacks):
            raise ReplayError('Invalid replay lookback index')
        return self.lookbacks[index - 1]


def replay_bytes(value):
    data = value.data if isinstance(value, Binary) else value
    if not isinstance(data, bytes) or not 17 <= len(data) <= MAX_REPLAY_BYTES:
        raise ReplayError('Validation/ghost replay is missing or exceeds the size limit')
    return data


def check_replay(value, uid, login, score, checkpoints):
    data = replay_bytes(value)
    header = Reader(data)
    if header.read(3) != b'GBX' or header.read(2) != b'\x06\x00' or header.read(4)[1:2] != b'U':
        raise ReplayError('Unsupported replay header')
    if header.integer() not in (0x03093000, 0x2403F000, 0x2407E000):
        raise ReplayError('Not a supported replay GBX class')
    size = header.integer()
    if not 4 <= size <= 1024 * 1024:
        raise ReplayError('Replay header size exceeds limit')
    block = Reader(header.read(size))
    count = block.integer()
    if not 1 <= count <= 64:
        raise ReplayError('Invalid replay header chunk count')
    chunks = [(block.integer() & 0xFFF, block.integer() & 0x7FFFFFFF) for _ in range(count)]
    contents = {}
    for identifier, chunk_size in chunks:
        chunk = block.read(chunk_size)
        if identifier in contents:
            raise ReplayError('Duplicate replay header chunk')
        contents[identifier] = chunk
    if block.offset != size or 0 not in contents or 1 not in contents:
        raise ReplayError('Incomplete replay header')
    metadata = Reader(contents[0])
    version = metadata.integer()
    if not 2 <= version <= 8:
        raise ReplayError('Unsupported replay metadata version')
    replay_uid = metadata.lookback()
    metadata.lookback()
    metadata.lookback()
    replay_score = metadata.integer()
    metadata.string()  # Nickname; login is the stable player identity.
    replay_login = metadata.string() if version >= 6 else ''
    xml = Reader(contents[1]).string()
    if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        raise ReplayError('Unsafe replay XML')
    xml = re.sub(r'&(?!(?:amp|quot|apos|lt|gt|#\d+|#x[0-9a-fA-F]+);)', '&amp;', xml)
    try:
        root = ET.fromstring(xml)
        checks = root.find('checkpoints')
        current, per_lap = int(checks.get('cur')), int(checks.get('onelap'))
    except (ET.ParseError, AttributeError, TypeError, ValueError) as error:
        raise ReplayError('Missing replay checkpoint metadata') from error
    if (replay_uid != uid or replay_score != score or (replay_login and replay_login != login)
            or current != checkpoints or per_lap != checkpoints):
        raise ReplayError('Replay map, player, time or checkpoint count does not match the finish')
    return data
