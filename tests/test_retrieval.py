"""Arsenal Phase D: hybrid retrieval, rerank fallback, Qdrant REST shape (offline)."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from capability_permits import PermitAuthority, audit_permit_ledger, digest
from config import RunConfig
from native_transition_broker import NativeTransitionBroker
from retrieval import (
    FallbackReranker, HostedReranker, LocalHybridIndex, QdrantRetriever, RetrievalEvidenceRetriever,
    as_sources, chunk_text, rrf,
)
from test_native_transition_broker import SPEC, FakeCodex

DOCS = {
    'deploy.md': 'Deployment checklist.\n\nEvery release needs a rollback plan and an owner.\n\n'
                 'Run the smoke tests after deploy.',
    'billing.md': 'Billing notes.\n\nInvoices are generated monthly from usage receipts.',
    'secret.md': 'Restricted runbook.\n\nRotate the signing key before every release.',
}


def toy_embedder(texts, kind):
    """Deterministic bag-of-words vectors; not a real model."""
    vectors = []
    for text in texts:
        vector = [0.0] * 32
        for word in text.lower().split():
            vector[int(hashlib.md5(word.strip('.,').encode()).hexdigest(), 16) % 32] += 1.0
        vectors.append(vector)
    return vectors


class FakeResponse(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(json.dumps(data).encode('utf-8'))
        self.headers = headers or {'Content-Type': 'application/json'}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class RecordingOpener:
    def __init__(self, response):
        self.response, self.requests = response, []

    def __call__(self, req, timeout=None):
        self.requests.append({'url': req.full_url, 'method': req.get_method(),
                              'headers': dict(req.header_items()),
                              'body': json.loads(req.data) if req.data else None})
        return FakeResponse(self.response(self.requests[-1]) if callable(self.response) else self.response)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.index = LocalHybridIndex(Path(self.temp.name) / 'index.db')
        for doc_id, text in DOCS.items():
            self.index.add_document('ops', doc_id, text, title=doc_id,
                                    access=['security'] if doc_id == 'secret.md' else None)

    def tearDown(self):
        self.index.close()
        self.temp.cleanup()

    def test_chunks_are_bounded_and_overlap(self):
        text = '\n\n'.join('Paragraph %d ' % i + 'word ' * 120 for i in range(6))
        chunks = chunk_text(text)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(c) <= 1100 for c in chunks))

    def test_lexical_search_binds_chunk_ids_and_hashes(self):
        found = self.index.search('ops', 'rollback plan release owner', k=3)
        top = found['results'][0]
        self.assertEqual(top['doc_id'], 'deploy.md')
        self.assertEqual(top['content_hash'], digest(top['text']))
        self.assertEqual(found['authority'], 'ranking_evidence_only')

    def test_access_groups_are_payload_filters(self):
        public = self.index.search('ops', 'rotate signing key release', k=5)
        self.assertNotIn('secret.md', [r['doc_id'] for r in public['results']])
        allowed = self.index.search('ops', 'rotate signing key release', k=5, access_groups=['security'])
        self.assertEqual(allowed['results'][0]['doc_id'], 'secret.md')

    def test_unchanged_document_is_not_rechunked(self):
        first = self.index.add_document('ops', 'deploy.md', DOCS['deploy.md'], title='deploy.md')
        second = self.index.add_document('ops', 'deploy.md', DOCS['deploy.md'], title='deploy.md')
        self.assertEqual(first, second)

    def test_dense_vectors_are_cached_and_fused_with_rrf(self):
        built = self.index.build_vectors('toy', toy_embedder)
        self.assertEqual(built['embedded'], built['chunks'])
        self.assertEqual(self.index.build_vectors('toy', toy_embedder)['embedded'], 0)
        found = self.index.search('ops', 'invoices usage receipts', dense_model='toy', embedder=toy_embedder)
        self.assertEqual(found['rankings_used'], ['dense', 'lexical'])
        self.assertEqual(found['results'][0]['doc_id'], 'billing.md')
        self.assertEqual(set(found['results'][0]['scores']['ranks']), {'dense', 'lexical'})

    def test_rrf_rewards_agreement(self):
        fused = rrf({'a': ['x', 'y'], 'b': ['y', 'z']})
        self.assertEqual(fused[0][0], 'y')

    def test_sources_are_bounded_and_skip_known_ids(self):
        results = self.index.search('ops', 'release', k=5)['results']
        packet = as_sources(results, exclude={results[0]['chunk_id']})
        self.assertNotIn(results[0]['chunk_id'], packet)
        self.assertTrue(all(len(s['text']) <= 1200 and len(s['title']) <= 120 for s in packet.values()))


class RerankTests(unittest.TestCase):
    def test_hosted_reranker_request_shape(self):
        opener = RecordingOpener({'results': [{'index': 1, 'relevance_score': 0.9},
                                              {'index': 0, 'relevance_score': 0.2}]})
        ranked = HostedReranker('cohere', 'rerank-model', 'test-key', opener=opener).rerank('q', ['a', 'b'])
        self.assertEqual(ranked['order'][0], (1, 0.9))
        request = opener.requests[0]
        self.assertEqual(request['url'], 'https://api.cohere.com/v2/rerank')
        self.assertEqual(request['body']['top_n'], 2)
        self.assertEqual(request['headers']['Authorization'], 'Bearer test-key')

    def test_rejects_rerank_response_with_missing_indices(self):
        opener = RecordingOpener({'data': [{'index': 0, 'relevance_score': 0.5}]})
        with self.assertRaises(Exception):
            HostedReranker('voyage', 'm', 'k', opener=opener).rerank('q', ['a', 'b'])

    def test_fallback_only_when_local_fails_or_is_weak(self):
        class Local:
            def __init__(self, score=None, fail=False):
                self.score, self.fail = score, fail

            def rerank(self, query, docs):
                if self.fail:
                    raise RuntimeError('no model')
                return {'provider': 'local', 'order': [(0, self.score)]}

        class Hosted:
            calls = 0

            def rerank(self, query, docs):
                Hosted.calls += 1
                return {'provider': 'hosted', 'order': [(0, 0.99)]}

        strong = FallbackReranker(Local(0.9), Hosted(), min_top_score=0.5).rerank('q', ['a'])
        self.assertFalse(strong['fallback_used'])
        weak = FallbackReranker(Local(0.1), Hosted(), min_top_score=0.5).rerank('q', ['a'])
        self.assertTrue(weak['fallback_used'])
        broken = FallbackReranker(Local(fail=True), Hosted()).rerank('q', ['a'])
        self.assertEqual(broken['fallback_reason'], 'local_unavailable:RuntimeError')
        self.assertEqual(Hosted.calls, 2)


class QdrantTests(unittest.TestCase):
    def test_upsert_and_hybrid_query_shapes_with_hash_check(self):
        good = {'chunk_id': 'kb-1', 'namespace': 'ops', 'doc_id': 'd', 'ordinal': 0, 'title': 't',
                'text': 'evidence', 'content_hash': digest('evidence'), 'access': []}
        tampered = dict(good, chunk_id='kb-2', text='changed')

        def respond(request):
            if request['url'].endswith('/points/query'):
                return {'status': 'ok', 'result': {'points': [{'score': 0.8, 'payload': good},
                                                              {'score': 0.7, 'payload': tampered}]}}
            return {'status': 'ok', 'result': {'operation_id': 1}}

        opener = RecordingOpener(respond)
        qdrant = QdrantRetriever('https://qdrant.example.test', 'cidm', api_key='k', opener=opener)
        qdrant.upsert([good], [[0.1, 0.2]], sparse=[{'indices': [1], 'values': [0.5]}])
        found = qdrant.search('ops', [0.1, 0.2], sparse={'indices': [1], 'values': [0.5]},
                              access_groups=['security'])
        self.assertEqual([r['chunk_id'] for r in found['results']], ['kb-1'])
        upsert, query = opener.requests
        self.assertEqual(upsert['method'], 'PUT')
        self.assertEqual(upsert['headers']['Api-key'], 'k')
        self.assertEqual(query['body']['query'], {'fusion': 'rrf'})
        self.assertEqual(len(query['body']['prefetch']), 2)

    def test_plain_http_remote_qdrant_is_rejected(self):
        with self.assertRaises(Exception):
            QdrantRetriever('http://qdrant.example.test', 'cidm')


class KnowledgeJev:
    def __call__(self, phase, options, state):
        if phase == 'authorize_unit':
            choice = 'compute' if 'compute' in options else 'luna_low'
        elif phase == 'after_worker':
            known = any(entry['id'].startswith('kb-') for entry in state['source_manifest'])
            choice = 'retrieve_evidence' if state['unit']['id'] == 'hidden2' and not known else 'forward'
        else:
            raise AssertionError(phase)
        return {'choice': choice, 'model': 'typesafe/jev-1.13-20260917', 'live': True,
                'usage': {'input_tokens': 25, 'output_tokens': 5, 'cost': 0.000001}}


class RetrievalRecoveryTests(unittest.TestCase):
    def test_retrieval_feeds_recovery_with_hashed_new_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            index = LocalHybridIndex(Path(temp) / 'index.db')
            for doc_id, text in DOCS.items():
                index.add_document('ops', doc_id, text, title=doc_id)
            authority = PermitAuthority()
            retriever = RetrievalEvidenceRetriever(index, authority, namespace='ops', k=1)
            broker = NativeTransitionBroker(FakeCodex(), KnowledgeJev(), RunConfig(), Path(temp) / 'run',
                                            gate_policy='recovery', evidence_retriever=retriever)
            result = broker.run(SPEC)
            index.close()
        self.assertEqual(result['status'], 'complete')
        added = [e for e in result['events'] if e['kind'] == 'recovery_evidence_added']
        self.assertEqual(len(added), 1)
        self.assertTrue(added[0]['added'][0]['id'].startswith('kb-'))
        self.assertEqual(result['evidence_receipts'][0]['status'], 'ok')
        self.assertTrue(audit_permit_ledger(authority.events())['valid'])


if __name__ == '__main__':
    unittest.main()
