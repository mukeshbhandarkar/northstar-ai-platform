"""Validate immutable file payloads before invoking the atomic store operation."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from .store import InvalidEvent

IDENTITY = {'tenant_id', 'document_id', 'source', 'source_version'}
EVENT_FIELDS = IDENTITY | {'event_id', 'event_type', 'occurred_at', 'payload_ref', 'checksum'}
DOCUMENT_FIELDS = IDENTITY | {'created_at', 'updated_at', 'document_type', 'title', 'body'}
TYPES = {'runbook', 'architecture_doc', 'incident', 'pull_request', 'support_ticket', 'deployment'}


def check(condition, message):
    if not condition:
        raise InvalidEvent(message)


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            check(key not in result, f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def timestamp(value):
    check(isinstance(value, str) and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)', value),
        'Expected UTC RFC 3339 timestamp')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def payload_path(root, relative):
    check(isinstance(relative, str) and bool(relative), 'Missing payload reference')
    path = Path(relative)
    check(not path.is_absolute() and '..' not in path.parts, 'Unsafe payload reference')
    resolved = (root / path).resolve()
    check(resolved.is_relative_to(root.resolve()) and resolved.is_file(),
          'Missing payload or reference escapes dataset root')
    return resolved


@dataclass(frozen=True)
class Result:
    outcome: str
    reason: str = ''


class Processor:
    def __init__(self, store, dataset):
        self.store = store
        self.dataset = Path(dataset)

    def process(self, event):
        try:
            check(isinstance(event, dict) and set(event) == EVENT_FIELDS, 'Invalid event fields')
            for field in ('event_id', 'tenant_id', 'document_id', 'source'):
                check(isinstance(event[field], str) and bool(event[field].strip()), f'Invalid {field}')
            check(type(event['source_version']) is int and 0 < event['source_version'] <= 2**63 - 1,
                  'source_version must be a positive SQLite integer')
            check(event['event_type'] in ('upsert', 'delete'), 'Invalid event type')
            timestamp(event['occurred_at'])
            check(isinstance(event['checksum'], str) and
                  re.fullmatch('[0-9a-f]{64}', event['checksum']), 'Invalid SHA-256 checksum')
            raw = payload_path(self.dataset, event['payload_ref']).read_bytes()
            check(hashlib.sha256(raw).hexdigest() == event['checksum'], 'Payload checksum mismatch')
            payload = parse_json(raw.decode('utf-8'))
            fields = IDENTITY if event['event_type'] == 'delete' else DOCUMENT_FIELDS
            check(isinstance(payload, dict) and set(payload) == fields, 'Invalid payload fields')
            check(type(payload['source_version']) is int, 'Invalid payload version')
            check(all(payload[f] == event[f] for f in IDENTITY), 'Payload identity/source/version mismatch')
            if event['event_type'] == 'upsert':
                check(isinstance(payload['document_type'], str) and payload['document_type'] in TYPES,
                      'Invalid document type')
                for field in ('title', 'body'):
                    check(isinstance(payload[field], str) and bool(payload[field].strip()), f'Invalid {field}')
                check(timestamp(payload['created_at']) <= timestamp(payload['updated_at']),
                      'Document update precedes creation')
            return Result(self.store.apply(event, payload))
        except (InvalidEvent, ValueError, OSError, UnicodeError) as exc:
            return Result('INVALID', str(exc))
