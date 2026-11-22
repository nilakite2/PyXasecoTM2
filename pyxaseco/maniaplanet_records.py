"""MP database configuration and migration from the first local-records test."""

from contextlib import asynccontextmanager
import json
import os
import re


class RecordsError(ValueError):
    """The dedicated MP records database could not be used."""


SAVE_PB = '''
INSERT INTO mp_local_records (map_uid, player_login, time_ms, splits_json)
VALUES (%s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    splits_json = IF(VALUES(time_ms) < time_ms, VALUES(splits_json), splits_json),
    time_ms = LEAST(time_ms, VALUES(time_ms))
'''


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


class LocalRecords:
    def __init__(self, pool):
        self.pool = pool

    async def rows(self, sql, args=()):
        async with self.pool.acquire() as connection, connection.cursor() as cursor:
            await cursor.execute(sql, args)
            return await cursor.fetchall()

    async def save(self, uid, login, time_ms, splits):
        data = json.dumps(splits, separators=(',', ':'))
        async with self.pool.acquire() as connection, connection.cursor() as cursor:
            await cursor.execute(SAVE_PB, (uid, login, time_ms, data))
            return cursor.rowcount > 0

    async def personal(self, uid, login):
        rows = await self.rows('SELECT time_ms FROM mp_local_records WHERE map_uid=%s AND player_login=%s',
                               (uid, login))
        return rows[0][0] if rows else None

    async def top(self, uid):
        return await self.rows('SELECT player_login,time_ms FROM mp_local_records WHERE map_uid=%s '
                               'ORDER BY time_ms,player_login LIMIT 10', (uid,))


@asynccontextmanager
async def connect_records(config):
    try:
        import aiomysql
    except ImportError as error:
        raise RecordsError('Install the Python requirements before running the MP controller.') from error
    try:
        pool = await aiomysql.create_pool(**config, minsize=1, maxsize=2, autocommit=True,
                                          charset='utf8mb4', connect_timeout=5)
    except (aiomysql.Error, OSError) as error:
        raise RecordsError('Could not open the MP database. Check its address, credentials and grants.') from error
    try:
        records = LocalRecords(pool)
        try:
            await records.rows('SELECT map_uid,player_login,time_ms,splits_json FROM mp_local_records LIMIT 0')
        except aiomysql.Error as error:
            raise RecordsError('The MP table is not accessible. Import database/pyxasecomp_local_records.sql first.') from error
        try:
            yield records
        except aiomysql.Error as error:
            raise RecordsError('MP records stopped after a connection or database error.') from error
    finally:
        pool.close()
        await pool.wait_closed()
