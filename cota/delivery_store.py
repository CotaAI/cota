"""Mutable transport receipts pointing to immutable bot_utter facts.

The dispatcher is single-process. Attempts are not distributed leases, and a
crash after the remote send can result in an at-least-once duplicate.
"""
from copy import deepcopy
import math

import sqlalchemy as sa


def validate_target(target):
    if target is None:
        return None
    if not isinstance(target, dict):
        raise ValueError('delivery_target must be a mapping')
    result = {}
    for key, size in (('channel', 64), ('scope', 255), ('chat_id', 255)):
        value = target.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > size:
            raise ValueError(f'delivery_target.{key} must be a nonempty string of at most {size} characters')
        result[key] = value
    return result


def delivery_rows(session_id, events, target):
    if target is None:
        return []
    return [dict(session_id=session_id, event_id=e['event_id'], sequence=e['sequence'],
                 **target, status='pending', attempts=0, next_attempt_at=0, error_type=None)
            for e in events if e['type'] == 'bot_utter']


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _validate_due(targets, now, limit):
    if not isinstance(targets, dict):
        raise ValueError('targets must map channel to scope')
    for channel, scope in targets.items():
        validate_target({'channel': channel, 'scope': scope, 'chat_id': '_'})
    if not _number(now) or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Expected finite now and 1 <= limit <= 1000')


def _finished_values(error, retry_at):
    if error is not None and (not isinstance(error, str) or not error.strip() or len(error) > 255):
        raise ValueError('error must be a nonempty error type of at most 255 characters')
    if retry_at is not None and (not _number(retry_at) or retry_at < 0 or error is None):
        raise ValueError('retry_at requires an error and a finite nonnegative timestamp')
    return {'status': 'delivered' if error is None else ('pending' if retry_at is not None else 'failed'),
            'error_type': error, 'next_attempt_at': retry_at if retry_at is not None else 0}


def make_delivery_table(metadata):
    # utf8mb4 composite indexes remain below MySQL's 3072-byte key limit.
    return sa.Table('deliveries', metadata,
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('session_id', sa.String(255), sa.ForeignKey('sessions.session_id'), nullable=False),
        sa.Column('event_id', sa.String(255), nullable=False),
        sa.Column('sequence', sa.Integer, nullable=False),
        sa.Column('channel', sa.String(64), nullable=False),
        sa.Column('scope', sa.String(255), nullable=False),
        sa.Column('chat_id', sa.String(255), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer, nullable=False),
        sa.Column('next_attempt_at', sa.Double, nullable=False),
        sa.Column('error_type', sa.String(255)),
        sa.UniqueConstraint('session_id', 'event_id'),
        sa.Index('ix_deliveries_due', 'channel', 'scope', 'status', 'next_attempt_at', 'id'),
        sa.Index('ix_deliveries_target_order', 'channel', 'scope', 'chat_id', 'id', 'status'))


class MemoryDeliveryStore:
    async def delivery(self, session_id, event_id):
        return deepcopy(self.delivery_rows.get((session_id, event_id)))

    async def due_deliveries(self, targets, now, limit=16):
        _validate_due(targets, now, limit)
        heads = set()
        result = []
        # Insertion order is the global commit order, including across sessions.
        for row in self.delivery_rows.values():
            if row['status'] == 'delivered' or targets.get(row['channel']) != row['scope']:
                continue
            key = (row['channel'], row['scope'], row['chat_id'])
            if key in heads:
                continue
            heads.add(key)
            if row['status'] == 'pending' and row['next_attempt_at'] <= now:
                result.append(deepcopy(row))
                if len(result) == limit:
                    break
        return result

    async def begin_delivery(self, session_id, event_id):
        row = self.delivery_rows.get((session_id, event_id))
        if row is None or row['status'] != 'pending':
            return None
        row['attempts'] += 1
        return deepcopy(row)

    async def finish_delivery(self, session_id, event_id, *, error=None, retry_at=None):
        values = _finished_values(error, retry_at)
        row = self.delivery_rows.get((session_id, event_id))
        if row is not None and row['status'] == 'pending':
            row.update(values)

    async def retry_delivery(self, session_id, event_id):
        row = self.delivery_rows.get((session_id, event_id))
        if row is None or row['status'] != 'failed':
            return False
        row.update(status='pending', attempts=0, next_attempt_at=0, error_type=None)
        return True


class SQLDeliveryStore:
    async def delivery(self, session_id, event_id):
        def read():
            table = self.SQLDelivery.__table__
            with self.engine.begin() as conn:
                row = conn.execute(sa.select(table).where(table.c.session_id == session_id,
                    table.c.event_id == event_id)).mappings().first()
                return dict(row) if row is not None else None
        return await self._io(read)

    async def due_deliveries(self, targets, now, limit=16):
        _validate_due(targets, now, limit)
        if not targets:
            return []
        def read():
            table = self.SQLDelivery.__table__
            prior = table.alias('prior_delivery')
            older = sa.select(prior.c.id).where(
                prior.c.channel == table.c.channel, prior.c.scope == table.c.scope,
                prior.c.chat_id == table.c.chat_id, prior.c.id < table.c.id,
                prior.c.status != 'delivered').exists()
            scopes = sa.or_(*(sa.and_(table.c.channel == channel, table.c.scope == scope)
                              for channel, scope in targets.items()))
            stmt = sa.select(table).where(scopes, table.c.status == 'pending',
                table.c.next_attempt_at <= now, ~older).order_by(table.c.id).limit(limit)
            with self.engine.begin() as conn:
                return [dict(row) for row in conn.execute(stmt).mappings()]
        return await self._io(read)

    async def begin_delivery(self, session_id, event_id):
        def write():
            table = self.SQLDelivery.__table__
            key = sa.and_(table.c.session_id == session_id, table.c.event_id == event_id)
            with self.engine.begin() as conn:
                result = conn.execute(table.update().where(key, table.c.status == 'pending')
                                      .values(attempts=table.c.attempts + 1))
                if result.rowcount != 1:
                    return None
                return dict(conn.execute(sa.select(table).where(key)).mappings().one())
        return await self._io(write)

    async def finish_delivery(self, session_id, event_id, *, error=None, retry_at=None):
        values = _finished_values(error, retry_at)
        def write():
            table = self.SQLDelivery.__table__
            with self.engine.begin() as conn:
                conn.execute(table.update().where(table.c.session_id == session_id,
                    table.c.event_id == event_id, table.c.status == 'pending').values(**values))
        await self._io(write)

    async def retry_delivery(self, session_id, event_id):
        def write():
            table = self.SQLDelivery.__table__
            with self.engine.begin() as conn:
                result = conn.execute(table.update().where(table.c.session_id == session_id,
                    table.c.event_id == event_id, table.c.status == 'failed')
                    .values(status='pending', attempts=0, next_attempt_at=0, error_type=None))
                return result.rowcount == 1
        return await self._io(write)
