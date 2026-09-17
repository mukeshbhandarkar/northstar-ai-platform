"""SQLite persistence and a single atomic event transition."""
import json
import sqlite3


class InvalidEvent(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def required_text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A nonempty tenant/document identifier is required')
    return value


class Store:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        try:
            tables = {r[0] for r in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            version = self.connection.execute('PRAGMA user_version').fetchone()[0]
            if tables and (tables != {'documents', 'events', 'versions'} or version != 1):
                raise ValueError('Existing database is not a NORTH-003 state database')
            self.connection.executescript('''
                CREATE TABLE IF NOT EXISTS documents (
                    tenant_id TEXT NOT NULL, document_id TEXT NOT NULL,
                    source TEXT NOT NULL, source_version INTEGER NOT NULL,
                    deleted INTEGER NOT NULL CHECK(deleted IN (0, 1)),
                    payload_ref TEXT NOT NULL, checksum TEXT NOT NULL,
                    occurred_at TEXT NOT NULL, created_at TEXT, updated_at TEXT,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, document_id)
                );
                CREATE TABLE IF NOT EXISTS versions (
                    tenant_id TEXT NOT NULL, document_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL, event_type TEXT NOT NULL,
                    source TEXT NOT NULL, created_at TEXT, payload_json TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, document_id, source_version)
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, envelope_json TEXT NOT NULL,
                    outcome TEXT NOT NULL
                );
                PRAGMA user_version = 1;
            ''')
        except Exception:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def documents(self, tenant_id, *, include_deleted=False):
        sql = 'SELECT * FROM documents WHERE tenant_id = ?'
        if not include_deleted:
            sql += ' AND deleted = 0'
        return [dict(r) for r in self.connection.execute(
            sql + ' ORDER BY document_id', (required_text(tenant_id),))]

    def get(self, tenant_id, document_id, *, include_deleted=False):
        sql = 'SELECT * FROM documents WHERE tenant_id = ? AND document_id = ?'
        if not include_deleted:
            sql += ' AND deleted = 0'
        row = self.connection.execute(sql, (required_text(tenant_id),
                                           required_text(document_id))).fetchone()
        return dict(row) if row else None

    def processed_event_count(self):
        return self.connection.execute('SELECT count(*) FROM events').fetchone()[0]

    def has_event(self, event_id):
        return self.connection.execute('SELECT 1 FROM events WHERE event_id = ?',
                                       (event_id,)).fetchone() is not None

    def tenants(self):
        """Tenant names only, for local administrative replay summaries."""
        return [r[0] for r in self.connection.execute(
            'SELECT DISTINCT tenant_id FROM documents ORDER BY tenant_id')]

    def apply(self, event, payload):
        """Called only after payload validation. Database failures propagate."""
        db = self.connection
        envelope, content = canonical(event), canonical(payload)
        key = event['tenant_id'], event['document_id']
        version = event['source_version']
        with db:
            db.execute('BEGIN IMMEDIATE')
            old_event = db.execute('SELECT envelope_json FROM events WHERE event_id = ?',
                                   (event['event_id'],)).fetchone()
            if old_event:
                if old_event[0] != envelope:
                    raise InvalidEvent('Event ID reused with a different envelope')
                return 'DUPLICATE'
            history = db.execute('SELECT * FROM versions WHERE tenant_id=? AND document_id=?',
                                 key).fetchall()
            for previous in history:
                if previous['source'] != event['source']:
                    raise InvalidEvent('Document source is immutable')
                if (payload.get('created_at') is not None and previous['created_at'] is not None
                        and payload['created_at'] != previous['created_at']):
                    raise InvalidEvent('Document creation timestamp is immutable')
                if previous['source_version'] == version and (
                        previous['payload_json'] != content or
                        previous['event_type'] != event['event_type']):
                    raise InvalidEvent('Conflicting content for an observed document version')
            current = self.get(*key, include_deleted=True)
            if current is None or version > current['source_version']:
                outcome = 'APPLIED'
                deleted = int(event['event_type'] == 'delete')
                created = payload.get('created_at') or (current or {}).get('created_at')
                db.execute('''INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, document_id) DO UPDATE SET
                    source=excluded.source, source_version=excluded.source_version,
                    deleted=excluded.deleted, payload_ref=excluded.payload_ref,
                    checksum=excluded.checksum, occurred_at=excluded.occurred_at,
                    created_at=excluded.created_at, updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json''',
                    (*key, event['source'], version, deleted, event['payload_ref'],
                     event['checksum'], event['occurred_at'], created,
                     payload.get('updated_at'), content))
            elif version < current['source_version']:
                outcome = 'STALE'
            else:
                outcome = 'DUPLICATE'
            db.execute('INSERT OR IGNORE INTO versions VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (*key, version, event['event_type'], event['source'],
                        payload.get('created_at'), content))
            db.execute('INSERT INTO events VALUES (?, ?, ?)',
                       (event['event_id'], envelope, outcome))
        return outcome
