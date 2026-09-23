"""A deliberately small, uncached title/body token-overlap baseline."""
import json
import re

from services.processor.store import required_text


def tokens(text):
    """Distinct Unicode alphanumeric tokens; punctuation/underscores separate."""
    return set(re.findall(r'[^\W_]+', text.casefold()))


class Retriever:
    def __init__(self, store):
        self.store = store

    def search(self, tenant_id, query):
        """Return up to five positive matches, ordered by score then document ID.

        Blank or punctuation-only queries return []. Invalid tenant context or
        non-string queries raise ValueError. Storage failures propagate.
        """
        required_text(tenant_id)
        if not isinstance(query, str):
            raise ValueError('Query must be a string')
        query_tokens = tokens(query)
        if not query_tokens:
            return []
        results = []
        # One SQL snapshot supplies both scored text and returned identity/version.
        for row in self.store.documents(tenant_id):
            payload = json.loads(row['payload_json'])
            matched = sorted(query_tokens & tokens(payload['title'] + ' ' + payload['body']))
            if matched:
                results.append({
                    'tenant_id': row['tenant_id'], 'document_id': row['document_id'],
                    'source_version': row['source_version'], 'title': payload['title'],
                    'score': len(matched), 'matched_tokens': matched,
                })
        return sorted(results, key=lambda r: (-r['score'], r['document_id']))[:5]
