"""Bounded MP replay-header checks, following XAseco2's GBXReplayFetcher."""

import re
import struct
import xml.etree.ElementTree as ET
from xmlrpc.client import Binary


MAX_REPLAY_BYTES = 24 * 1024 * 1024
MAX_BATCH_BYTES = 32 * 1024 * 1024


class ReplayError(ValueError):
    pass


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
