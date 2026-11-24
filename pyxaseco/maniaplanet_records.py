"""MP database configuration and migration from the first local-records test."""

import json
import os
import re


class RecordsError(ValueError):
    """The dedicated MP records database could not be used."""


def db_config(env=None):
    env = os.environ if env is None else env
    name = env.get('MP_DB_NAME', '').strip()
    user = env.get('MP_DB_USER', '').strip()
    password = env.get('MP_DB_PASSWORD', '')
    if not name or not user or not password:
        raise RecordsError('Set MP_DB_NAME, MP_DB_USER and MP_DB_PASSWORD for the separate MP database.')
    if (name.casefold() in {'mysql', 'performance_schema', 'information_schema', 'sys'}
            or name.casefold() == env.get('DB_NAME', '').strip().casefold()):
        raise RecordsError('Choose a separate database for PyXasecoMP, not the configured TMF database.')
    try:
        port = int(env.get('MP_DB_PORT', '3306'))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError as error:
        raise RecordsError('MP_DB_PORT must be a port from 1 to 65535.') from error
    return {'host': env.get('MP_DB_HOST', '127.0.0.1'), 'port': port,
            'db': name, 'user': user, 'password': password}


def _import_values(row):
    uid, login, score, raw = row
    try:
        splits = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise RecordsError('A test record contains invalid splits; no records were imported.') from error
    if (not isinstance(uid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,27}', uid)
            or not isinstance(login, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,50}', login)
            or type(score) is not int or not 0 < score <= 2_147_483_647
            or not isinstance(splits, list) or not 1 <= len(splits) <= 5000
            or any(type(value) is not int or not 0 < value <= score for value in splits)
            or splits[-1] != score or any(a > b for a, b in zip(splits, splits[1:]))):
        raise RecordsError('A test record does not fit the standard schema; no records were imported.')
    return uid, login, score, ','.join(str(value) for value in splits)


async def import_test_records(pool):
    """Copy prototype PBs into standard tables, never overwriting equal or faster PBs."""
    async with pool.acquire() as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() "
                          "AND TABLE_NAME='mp_local_records'")
        if not await cur.fetchone():
            return 0
        await cur.execute("SELECT map_uid, player_login, time_ms, splits_json FROM mp_local_records")
        rows = [_import_values(row) for row in await cur.fetchall()]
        await conn.begin()
        try:
            changed = 0
            for uid, login, score, splits in rows:
                await cur.execute("INSERT INTO challenges (Uid, Name, Environment) VALUES (%s, %s, 'Stadium') "
                                  "ON DUPLICATE KEY UPDATE Id=LAST_INSERT_ID(Id)", (uid, uid))
                challenge_id = cur.lastrowid
                await cur.execute("INSERT INTO players (Login, Game, NickName) VALUES (%s, 'MP4', %s) "
                                  "ON DUPLICATE KEY UPDATE Id=LAST_INSERT_ID(Id)", (login, login))
                player_id = cur.lastrowid
                await cur.execute(
                    "INSERT INTO records (ChallengeId, PlayerId, Score, Date, Checkpoints) "
                    "VALUES (%s, %s, %s, NOW(), %s) ON DUPLICATE KEY UPDATE "
                    "Date=IF(Score <= 0 OR VALUES(Score) < Score, VALUES(Date), Date), "
                    "Checkpoints=IF(Score <= 0 OR VALUES(Score) < Score, VALUES(Checkpoints), Checkpoints), "
                    "Score=IF(Score <= 0 OR VALUES(Score) < Score, VALUES(Score), Score)",
                    (challenge_id, player_id, score, splits))
                changed += cur.rowcount > 0
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise
    return changed
