"""Application metadata only; conversation messages belong to the Web API.

Each operation uses a short SQLite transaction in a worker thread. No runtime,
event, or Cota Store imports are needed by this optional application database.
"""
import asyncio
from contextlib import closing
import hashlib
from pathlib import Path
import secrets
import sqlite3
import time
from uuid import uuid4


def text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name} must contain 1–{limit} characters')
    return value.strip()


class ChatRegistry:
    def __init__(self, path, *, mode):
        if mode not in ('direct', 'group'):
            raise ValueError('Chat mode must be direct or group')
        self.path, self.mode = Path(path), mode
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY, title TEXT NOT NULL, mode TEXT NOT NULL,
                    owner_id TEXT NOT NULL REFERENCES users(user_id), created_at REAL NOT NULL,
                    invite_digest TEXT UNIQUE, invite_expires REAL);
                CREATE TABLE IF NOT EXISTS members (
                    session_id TEXT NOT NULL REFERENCES conversations(session_id),
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    PRIMARY KEY (session_id, user_id));
                CREATE TABLE IF NOT EXISTS read_cursors (
                    session_id TEXT NOT NULL, user_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    PRIMARY KEY (session_id, user_id),
                    FOREIGN KEY (session_id, user_id) REFERENCES members(session_id, user_id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS members_by_user ON members(user_id, session_id);
            ''')

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    async def _run(self, operation, *, write=False):
        def execute():
            with closing(self._connect()) as db, db:
                if write:
                    db.execute('BEGIN IMMEDIATE')
                return operation(db)
        return await asyncio.to_thread(execute)

    @staticmethod
    def _user(db, user_id):
        if not isinstance(user_id, str):
            raise PermissionError('Unknown visitor')
        row = db.execute('SELECT user_id, name FROM users WHERE user_id=?', (user_id,)).fetchone()
        if row is None:
            raise PermissionError('Unknown visitor')
        return dict(row)

    def _room(self, db, user_id, session_id, *, owner=False):
        if not isinstance(user_id, str) or not isinstance(session_id, str):
            raise PermissionError('Conversation not accessible')
        row = db.execute('''SELECT c.* FROM conversations c JOIN members m USING(session_id)
            WHERE c.session_id=? AND m.user_id=? AND c.mode=?''',
            (session_id, user_id, self.mode)).fetchone()
        if row is None or (owner and row['owner_id'] != user_id):
            raise PermissionError('Conversation not accessible')
        return row

    @staticmethod
    def _public(row):
        return {key: row[key] for key in ('session_id', 'title', 'mode', 'owner_id', 'created_at')}

    async def add_user(self, user_id, name):
        user_id, name = text(user_id, 'user_id', 255), text(name, 'name', 60)
        await self._run(lambda db: db.execute('INSERT INTO users VALUES (?,?,?)',
                                             (user_id, name, time.time())).rowcount, write=True)

    async def user(self, user_id):
        return await self._run(lambda db: self._user(db, user_id))

    async def authorize(self, user_id, session_id):
        await self._run(lambda db: self._public(self._room(db, user_id, session_id)))

    async def list_conversations(self, user_id, *, offset=0, limit=100):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('offset must be nonnegative; limit must be between 1 and 100')
        def query(db):
            self._user(db, user_id)
            rows = db.execute('''SELECT c.* FROM conversations c JOIN members m USING(session_id)
                WHERE m.user_id=? AND c.mode=? ORDER BY c.created_at DESC, c.session_id
                LIMIT ? OFFSET ?''', (user_id, self.mode, limit + 1, offset)).fetchall()
            return {'conversations': [self._public(row) for row in rows[:limit]], 'has_more': len(rows) > limit}
        return await self._run(query)

    async def create_conversation(self, user_id, title):
        title = text(title, 'title', 100)
        def create(db):
            self._user(db, user_id)
            sid = 'chat:' + uuid4().hex
            db.execute('INSERT INTO conversations(session_id,title,mode,owner_id,created_at) VALUES (?,?,?,?,?)',
                       (sid, title, self.mode, user_id, time.time()))
            db.execute('INSERT INTO members VALUES (?,?)', (sid, user_id))
            return self._public(self._room(db, user_id, sid))
        return await self._run(create, write=True)

    async def conversation(self, user_id, session_id):
        def query(db):
            room = self._public(self._room(db, user_id, session_id))
            room['members'] = [dict(row) for row in db.execute('''SELECT u.user_id,u.name
                FROM users u JOIN members m USING(user_id) WHERE m.session_id=? ORDER BY u.created_at,u.user_id''',
                (session_id,))]
            return room
        return await self._run(query)

    async def invite(self, user_id, session_id):
        def create(db):
            room = self._room(db, user_id, session_id, owner=True)
            if room['mode'] != 'group':
                raise ValueError('Direct conversations cannot invite members')
            token = secrets.token_urlsafe(32)
            expires_at = int(time.time()) + 7 * 86400
            db.execute('UPDATE conversations SET invite_digest=?,invite_expires=? WHERE session_id=?',
                       (hashlib.sha256(token.encode()).hexdigest(), expires_at, session_id))
            return {'invite': token, 'expires_at': expires_at}
        return await self._run(create, write=True)

    async def join(self, user_id, invite):
        invite = text(invite, 'invite', 256)
        def join(db):
            self._user(db, user_id)
            room = db.execute('''SELECT * FROM conversations WHERE invite_digest=?
                AND invite_expires>? AND mode=?''',
                (hashlib.sha256(invite.encode()).hexdigest(), time.time(), self.mode)).fetchone()
            if room is None or room['mode'] != 'group':
                raise PermissionError('Invalid or expired invitation')
            existing = db.execute('SELECT 1 FROM members WHERE session_id=? AND user_id=?',
                                  (room['session_id'], user_id)).fetchone()
            count = db.execute('SELECT count(*) FROM members WHERE session_id=?', (room['session_id'],)).fetchone()[0]
            if not existing and count >= 256:
                raise ValueError('This group has reached its 256-member limit')
            db.execute('INSERT OR IGNORE INTO members VALUES (?,?)', (room['session_id'], user_id))
            return self._public(room)
        return await self._run(join, write=True)

    async def remove(self, user_id, session_id, member_id):
        member_id = text(member_id, 'user_id', 255)
        def remove(db):
            room = self._room(db, user_id, session_id, owner=True)
            if room['mode'] != 'group' or member_id == room['owner_id']:
                raise ValueError('The conversation owner cannot be removed')
            db.execute('DELETE FROM members WHERE session_id=? AND user_id=?', (session_id, member_id))
            db.execute('UPDATE conversations SET invite_digest=NULL,invite_expires=NULL WHERE session_id=?', (session_id,))
        await self._run(remove, write=True)

    async def leave(self, user_id, session_id):
        def leave(db):
            room = self._room(db, user_id, session_id)
            if room['owner_id'] == user_id:
                raise ValueError('The conversation owner cannot leave')
            db.execute('DELETE FROM members WHERE session_id=? AND user_id=?', (session_id, user_id))
            db.execute('UPDATE conversations SET invite_digest=NULL,invite_expires=NULL WHERE session_id=?', (session_id,))
        await self._run(leave, write=True)

    async def read_cursor(self, user_id, session_id):
        def query(db):
            self._room(db, user_id, session_id)
            row = db.execute('SELECT sequence FROM read_cursors WHERE session_id=? AND user_id=?',
                             (session_id, user_id)).fetchone()
            return row[0] if row else 0
        return await self._run(query)

    async def mark_read(self, user_id, session_id, sequence):
        if type(sequence) is not int or not 0 <= sequence < 2**63:
            raise ValueError('sequence must be a nonnegative integer')
        def update(db):
            self._room(db, user_id, session_id)
            db.execute("""INSERT INTO read_cursors VALUES (?,?,?)
                ON CONFLICT(session_id,user_id) DO UPDATE SET sequence=MAX(sequence,excluded.sequence)""",
                (session_id, user_id, sequence))
            return db.execute('SELECT sequence FROM read_cursors WHERE session_id=? AND user_id=?',
                              (session_id, user_id)).fetchone()[0]
        return await self._run(update, write=True)
