import base64
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from onos import Article, CrossrefClient, HTTPError, ONOSClient, ResponseError, access_url
from onos._parsers import parse_publishers
from onos._utils import normalize_doi, normalize_issn

FIXTURES = Path(__file__).parent / 'fixtures'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock()
        self.transport.request.return_value = '<meta content="test-token" name="csrf-token">'
        self.crossref = Mock()
        self.client = ONOSClient(transport=self.transport, crossref_transport=self.crossref)

    def test_journal_search_uses_verified_form_fields(self):
        self.transport.json.return_value = fixture('journals.json')
        journals = self.client.search_journals('00280836')
        self.assertEqual(journals[0].title, 'Nature')
        self.assertEqual(journals[0].issns, ('0028-0836', '1476-4687'))
        args, kwargs = self.transport.json.call_args
        self.assertEqual(args, ('POST', 'https://www.onos.gov.in/searchJournal'))
        self.assertEqual(kwargs['data'], {'type': 'title', 'searchTitle': '0028-0836'})
        self.assertEqual(kwargs['headers']['X-CSRF-TOKEN'], 'test-token')
        self.client.search_journals('Nature')
        self.assertEqual(self.transport.request.call_count, 1)

    def test_subject_search(self):
        self.transport.json.return_value = fixture('journals.json')
        self.client.search_journals(subject_codes=[1000, '1100'])
        self.assertEqual(self.transport.json.call_args.kwargs['data'],
                         {'type': 'subject', 'subjects[]': ('1000', '1100')})

    def test_empty_search_is_distinct_from_invalid_schema(self):
        self.transport.json.return_value = {'success': True, 'result': []}
        self.assertEqual(self.client.search_journals('missing'), [])
        for payload in ({'success': True, 'result': None}, {'success': False, 'result': []},
                        {}, [], {'result': [None]}, {'result': [{'url': 'https://example.org'}]}):
            with self.subTest(payload=payload):
                self.transport.json.return_value = payload
                with self.assertRaises(ResponseError):
                    self.client.search_journals('test')

    def test_search_validation_precedes_network(self):
        for kwargs in ({}, {'query': ' '}, {'query': 'x', 'subject_codes': [1000]},
                       {'subject_codes': '1000'}, {'subject_codes': ['bad']},
                       {'subject_codes': [1000] * 6}, {'query': 'x', 'limit': 0},
                       {'query': 'x', 'limit': True}, {'query': '0028-0835'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.client.search_journals(**kwargs)
        self.transport.request.assert_not_called()
        self.transport.json.assert_not_called()

    def test_expired_csrf_refreshes_once(self):
        self.transport.request.side_effect = ['<meta name="csrf-token" content="one">',
                                             '<meta name="csrf-token" content="two">']
        self.transport.json.side_effect = [HTTPError(419, 'test'), fixture('journals.json')]
        self.assertEqual(len(self.client.search_journals('Nature')), 1)
        self.assertEqual(self.transport.json.call_args.kwargs['headers']['X-CSRF-TOKEN'], 'two')
        self.assertEqual(self.transport.request.call_count, 2)

    def test_repeated_csrf_failure_propagates(self):
        self.transport.json.side_effect = HTTPError(419, 'test')
        with self.assertRaises(HTTPError):
            self.client.search_journals('Nature')
        self.assertEqual(self.transport.json.call_count, 2)

    def test_missing_csrf_is_reported(self):
        self.transport.request.return_value = '<html>Login page or maintenance</html>'
        with self.assertRaises(ResponseError):
            self.client.search_journals('Nature')
        self.transport.json.assert_not_called()

    def test_subjects(self):
        self.transport.json.return_value = fixture('subjects.json')
        subjects = self.client.list_subjects()
        self.assertEqual(subjects[0].code, '1000')
        self.assertEqual(subjects[1].discipline, 'Agricultural and Biological Sciences')

    def test_publishers_from_live_html_fixture(self):
        self.transport.request.return_value = (FIXTURES / 'publishers.html').read_text()
        publishers = self.client.list_publishers()
        self.assertEqual(len(publishers), 2)
        self.assertEqual(publishers[0].name, 'AAAS- Science')
        self.assertEqual(publishers[0].journal_count, 1)
        self.assertEqual(publishers[0].urls, ('https://www.science.org/journal/science',))
        self.assertEqual(self.client.list_publishers('acm')[0].id, '41')

    def test_publishers_reject_changed_or_partial_html(self):
        for html in ('<html>Service unavailable</html>', '<div class="accordion-item"></div>',
                     '<div class="accordion-item"><button class="view-journal-btn" data-id="1" data-name="x"></button>'):
            with self.subTest(html=html), self.assertRaises(ResponseError):
                parse_publishers(html)

    def test_institution_filters_and_access_type(self):
        self.transport.json.return_value = fixture('institutions.json')
        items = self.client.search_institutions('aligarh', state='uttar pradesh', aishe_code='u-0496')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].id, '1')
        self.assertEqual(items[0].access_type, 'campus_ip')
        self.assertEqual(self.client.search_institutions(state='absent'), [])
        self.assertEqual(len(self.client.search_institutions(limit=1)), 1)
        self.assertEqual(self.client.search_institutions()[-1].access_type, 'institutional_login')
        self.transport.request.assert_not_called()

    def test_missing_optional_institution_fields(self):
        self.transport.json.return_value = {'success': True, 'result': [
            {'id': 123, 'memname': 'Example', 'remark': 'not an AISHE code'}]}
        institute = self.client.search_institutions()[0]
        self.assertIsNone(institute.aishe_code)
        self.assertEqual(institute.access_type, 'unknown')
        self.assertEqual(institute.city, '')

    def test_caller_owns_injected_transports(self):
        self.client.clear_cache()
        self.transport.clear_cache.assert_called_once()
        self.crossref.clear_cache.assert_called_once()
        self.client.close()
        self.transport.close.assert_not_called()
        self.crossref.close.assert_not_called()

    def test_coverage_requires_exact_issn(self):
        article = Article('10.1234/test', 'Test', (), 'Nature', '',
                          ('0028-0836', '1476-4687', '0028-0836'), None, 'https://example.org/test')
        self.transport.json.return_value = fixture('journals.json')
        result = self.client.check_article_access(article)
        self.assertEqual(result.catalog_status, 'matched')
        self.assertEqual(len(result.matched_journals), 1)
        self.assertEqual(self.transport.json.call_count, 2)
        self.assertIn('does not confirm', result.note)
        altered = copy.copy(article)
        altered = Article(altered.doi, altered.title, (), '', '', ('1745-2473',), None, altered.url)
        self.assertEqual(self.client.check_article_access(altered).catalog_status, 'not_found')

    def test_no_valid_issn_gives_unknown_without_onos_request(self):
        article = Article('10.1234/test', '', (), '', '', ('bad',), None, 'https://example.org')
        self.assertEqual(self.client.check_article_access(article).catalog_status, 'unknown')
        self.transport.json.assert_not_called()

    def test_access_lookup_by_doi(self):
        self.crossref.json.return_value = fixture('article.json')
        self.transport.json.return_value = {'success': True, 'result': []}
        result = self.client.check_article_access('10.1038/nphys1170')
        self.assertEqual(result.article.title, 'Measured measurement')
        self.assertEqual(result.catalog_status, 'not_found')


class CrossrefTests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock()
        self.client = CrossrefClient(transport=self.transport, mailto='reader@example.org')

    def test_doi_metadata(self):
        self.transport.json.return_value = fixture('article.json')
        article = self.client.get_article('https://doi.org/10.1038/nphys1170')
        self.assertEqual(article.published, '2009-01')
        self.assertEqual(article.url, 'https://www.nature.com/articles/nphys1170')
        self.assertEqual(article.source, 'crossref')
        url = self.transport.json.call_args.args[1]
        self.assertIn('/works/10.1038%2Fnphys1170', url)
        self.assertEqual(parse_qs(urlsplit(url).query)['mailto'], ['reader@example.org'])

    def test_cursor_and_issn_search(self):
        self.transport.json.return_value = {'status': 'ok', 'message': {
            'items': [fixture('article.json')['message']], 'total-results': 4, 'next-cursor': 'a+/='}}
        page = self.client.search_articles('quantum & light', issn='17452473', limit=1, cursor='a+/=')
        self.assertEqual(page.next_cursor, 'a+/=')
        params = parse_qs(urlsplit(self.transport.json.call_args.args[1]).query)
        self.assertEqual(params['filter'], ['type:journal-article,issn:1745-2473'])
        self.assertEqual(params['query.bibliographic'], ['quantum & light'])
        self.assertEqual(params['cursor'], ['a+/='])
        self.assertEqual(page.total_results, 4)
        page = self.client.search_articles('test', limit=2)
        self.assertIsNone(page.next_cursor)

    def test_empty_page_terminates_pagination(self):
        self.transport.json.return_value = {'status': 'ok', 'message': {
            'items': [], 'total-results': 0, 'next-cursor': 'stale'}}
        self.assertIsNone(self.client.search_articles('absent').next_cursor)

    def test_partial_metadata_uses_doi_landing_page(self):
        self.transport.json.return_value = {'status': 'ok', 'message': {'DOI': '10.1234/test'}}
        article = self.client.get_article('10.1234/test')
        self.assertEqual(article.url, 'https://doi.org/10.1234/test')
        self.assertEqual(article.authors, ())
        self.assertIsNone(article.published)

    def test_invalid_schema_is_reported(self):
        for payload in ({}, {'status': 'error'}, {'status': 'ok', 'message': []},
                        {'status': 'ok', 'message': {'items': None, 'total-results': 1}}):
            self.transport.json.return_value = payload
            with self.subTest(payload=payload), self.assertRaises(ResponseError):
                self.client.search_articles('test')

    def test_invalid_search_arguments(self):
        for kwargs in ({'query': ''}, {'query': 'test', 'limit': 1001},
                       {'query': 'test', 'limit': -1}, {'query': 'test', 'cursor': ''},
                       {'query': 'test', 'issn': '0028-0835'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.client.search_articles(**kwargs)
        self.transport.json.assert_not_called()


class IdentifierTests(unittest.TestCase):
    def test_doi_normalization_and_encoding(self):
        self.assertEqual(normalize_doi(' doi:10.1038/nphys1170 '), '10.1038/nphys1170')
        self.assertEqual(normalize_doi('https://doi.org/10.1234%2Ffoo%28bar%29'), '10.1234/foo(bar)')
        for value in ('abc', 'https://example.org/10.1234/test', '10.1234/has space', '10.1234/a\x1b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_doi(value)

    def test_issn_checksums(self):
        self.assertEqual(normalize_issn('00280836'), '0028-0836')
        self.assertEqual(normalize_issn('2434-561x'), '2434-561X')
        for value in ('123', '0028-0835', 'abcd-efgh'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_issn(value)

    def test_access_target_base64_round_trip(self):
        target = 'https://example.org/article?a=1&b=two#part'
        link = access_url(target)
        value = parse_qs(urlsplit(link).query)['target'][0]
        self.assertEqual(base64.b64decode(value).decode(), target)
        self.assertEqual(access_url(), 'https://www.onos.gov.in/ums/check-access')
        self.assertIn('target=', access_url('10.1038/nphys1170'))

    def test_access_rejects_unsafe_schemes_and_credentials(self):
        for value in ('javascript:alert(1)', 'file:///etc/passwd', 'https://u:p@example.org',
                      'https://example.org/a\nb'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                access_url(value)

    def test_unicode_access_target_is_ascii_uri(self):
        value = parse_qs(urlsplit(access_url('https://example.org/café')).query)['target'][0]
        self.assertEqual(base64.b64decode(value).decode(), 'https://example.org/caf%C3%A9')
