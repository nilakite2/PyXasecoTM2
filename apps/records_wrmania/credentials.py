"""Resolve WRMania credentials from the local TM2 dedicated account."""

import os
from pathlib import Path
import re
import tomllib
import xml.etree.ElementTree as ET

from pyxaseco.models import nation_from_zone


MAX_CONFIG_BYTES = 256 * 1024
DEFAULT_NAME = 'dedicated_cfg.default.txt'


def mp_overrides(base, defaults):
    path = base / 'config.toml'
    if path.is_file():
        with path.open('rb') as stream:
            config = tomllib.load(stream).get('records_wrmania', {})
    else:
        config = {}
    if not isinstance(config, dict):
        raise ValueError('config.toml [records_wrmania] must be a table.')
    result = {}
    for key in ('server_login', 'server_password', 'nation', 'dedicated_cfg'):
        value = config.get(key, '')
        if not isinstance(value, str):
            raise ValueError('config.toml [records_wrmania] credentials must be strings.')
        env = os.getenv('PYXASECOMP_WRMANIA_' + key.upper())
        result[key] = env or value or defaults.get(key, '')
    return result


def _xml_password(path, login):
    with path.open('rb') as stream:
        raw = stream.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES or b'<!DOCTYPE' in raw.replace(b'\x00', b'').upper():
        raise ValueError('Unsupported dedicated config XML.')
    root = ET.fromstring(raw)
    accounts = root.findall('masterserver_account') if root.tag == 'dedicated' else []
    if len(accounts) != 1 or accounts[0].findtext('login', '').strip().casefold() != login.casefold():
        return ''
    return accounts[0].findtext('password', '').strip()


def dedicated_password(base, gamedir, trackdir, login, override=''):
    if override:
        path = base / Path(override).expanduser()
        try:
            password = _xml_password(path, login)
        except (OSError, ValueError, ET.ParseError):
            raise ValueError('Could not read the configured WRMania dedicated_cfg file.') from None
        if not password:
            raise ValueError('Configured WRMania dedicated_cfg has no password for the connected login.')
        return password

    folders = [base / 'UserData' / 'Config', base.parent / 'UserData' / 'Config', base.parent / 'Config']
    for value, is_map_dir in ((gamedir, False), (trackdir, True)):
        if not value:
            continue
        directory = Path(value)
        if directory == Path('.') or (is_map_dir and directory.name.casefold() != 'maps'):
            continue
        for root in (base, base.parent) if not directory.is_absolute() else (base,):
            resolved = root / directory
            folders.append((resolved.parent if is_map_dir else resolved) / 'Config')
    candidates = dict.fromkeys(folder / DEFAULT_NAME for folder in folders)
    passwords = set()
    for path in candidates:
        try:
            password = _xml_password(path, login)
        except (OSError, ValueError, ET.ParseError):
            continue
        if password:
            passwords.add(password)
    if len(passwords) > 1:
        raise ValueError('Multiple WRMania dedicated configs match this login. Set dedicated_cfg explicitly.')
    return passwords.pop() if passwords else ''


def nation_code(base, zone):
    name = nation_from_zone(zone)
    if re.fullmatch('[A-Z]{3}', name):
        return name
    try:
        with (base / 'nations.toml').open('rb') as stream:
            nations = tomllib.load(stream).get('nations', {})
    except (OSError, ValueError):
        return ''
    if not isinstance(nations, dict):
        return ''
    matches = [code for code, label in nations.items()
               if re.fullmatch('[A-Z]{3}', code) and str(label).casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else ''
