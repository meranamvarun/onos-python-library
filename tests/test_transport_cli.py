import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from unittest.mock import Mock, patch
from urllib.error import HTTPError as UrlHTTPError, URLError
from urllib.parse import parse_qs

from onos import HTTPError, HTTPTransport, NetworkError, NotFoundError, RateLimitError, ResponseError
from onos.cli import main
from onos.models import Article, ArticlePage, Journal


class Response:
    def __init__(self, body=b'{}'):
        self.body = body
        self.headers = Message()
        self.headers['Content-Type'] = 'application/json; charset=utf-8'

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def http_error(status, retry_after=None):
    headers = Message()
    if retry_after:
        headers['Retry-After'] = retry_after
    return UrlHTTPError('https://example.org', status, 'failure', headers, io.BytesIO())


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.transport = HTTPTransport(min_interval=0)
        self.opener = Mock()
        self.transport._opener = self.opener
        self.opener.open.return_value = Response()
        self.sleep = patch('onos._http.time.sleep').start()
        self.addCleanup(patch.stopall)

    def test_form_encoding_and_timeout(self):
        self.transport.request('POST', 'https://example.org', data={'subjects[]': ['1000', '1100'],
                               'searchTitle': 'A & B'}, headers={'X-CSRF-TOKEN': 'test'})
        request = self.opener.open.call_args.args[0]
        self.assertEqual(parse_qs(request.data.decode())['subjects[]'], ['1000', '1100'])
        self.assertEqual(parse_qs(request.data.decode())['searchTitle'], ['A & B'])
        self.assertEqual(request.get_header('X-csrf-token'), 'test')
        self.assertEqual(self.opener.open.call_args.kwargs['timeout'], 30)

    def test_cache_returns_independent_json_objects(self):
        self.opener.open.return_value = Response(b'{"items": []}')
        first = self.transport.json('GET', 'https://example.org')
        first['items'].append('local mutation')
        self.assertEqual(self.transport.json('GET', 'https://example.org'), {'items': []})
        self.assertEqual(self.opener.open.call_count, 1)
        self.transport.clear_cache()
        self.transport.json('GET', 'https://example.org')
        self.assertEqual(self.opener.open.call_count, 2)

    def test_cache_expiry_and_disabled_cache(self):
        with patch('onos._http.time.monotonic', return_value=0):
            self.transport.request('GET', 'https://example.org')
        with patch('onos._http.time.monotonic', return_value=301):
            self.transport.request('GET', 'https://example.org')
        self.transport.request('GET', 'https://example.org', cache=False)
        self.assertEqual(self.opener.open.call_count, 3)

    def test_cache_has_a_size_bound(self):
        for i in range(130):
            self.transport.request('GET', f'https://example.org/{i}')
        self.assertEqual(len(self.transport._cache), 128)

    def test_retry_429_honors_retry_after(self):
        self.opener.open.side_effect = [http_error(429, '7'), Response()]
        self.transport.request('GET', 'https://example.org')
        self.sleep.assert_any_call(7)
        self.assertEqual(self.opener.open.call_count, 2)

    def test_long_retry_after_fails_without_retrying_too_early(self):
        self.opener.open.side_effect = http_error(429, '120')
        with self.assertRaises(RateLimitError):
            self.transport.request('GET', 'https://example.org')
        self.assertEqual(self.opener.open.call_count, 1)

    def test_transient_http_retry_exhaustion(self):
        self.opener.open.side_effect = lambda *a, **k: (_ for _ in ()).throw(http_error(503))
        with self.assertRaises(HTTPError) as error:
            self.transport.request('GET', 'https://example.org')
        self.assertEqual(error.exception.status, 503)
        self.assertEqual(self.opener.open.call_count, 3)

    def test_404_is_not_retried(self):
        self.opener.open.side_effect = http_error(404)
        with self.assertRaises(NotFoundError):
            self.transport.request('GET', 'https://example.org')
        self.assertEqual(self.opener.open.call_count, 1)

    def test_network_error_after_bounded_retries(self):
        self.opener.open.side_effect = URLError('connection failed')
        with self.assertRaises(NetworkError):
            self.transport.request('GET', 'https://example.org')
        self.assertEqual(self.opener.open.call_count, 3)

    def test_non_json_maintenance_page_is_reported(self):
        self.opener.open.return_value = Response(b'<html>Maintenance</html>')
        with self.assertRaises(ResponseError):
            self.transport.json('GET', 'https://example.org')

    def test_retry_after_http_date(self):
        self.assertEqual(HTTPTransport._retry_delay('Wed, 21 Oct 2015 07:28:00 GMT', 0), 0)
        self.assertEqual(HTTPTransport._retry_delay('invalid', 1), 2)

    def test_invalid_transport_configuration(self):
        for kwargs in ({'timeout': 0}, {'timeout': float('nan')}, {'retries': 6},
                       {'retries': -1}, {'min_interval': -1}, {'cache_ttl': float('inf')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                HTTPTransport(**kwargs)


class CLITests(unittest.TestCase):
    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = main(args)
        return result, out.getvalue(), err.getvalue()

    def test_access_json_needs_no_network_or_browser(self):
        with patch('onos._http.HTTPTransport.request') as network, patch('onos.cli.webbrowser.open') as browser:
            code, out, err = self.invoke(['access', '10.1038/nphys1170', '--json'])
        self.assertEqual(code, 0)
        self.assertIn('target=', json.loads(out)['access_url'])
        self.assertEqual(err, '')
        network.assert_not_called()
        browser.assert_not_called()

    def test_browser_open_is_explicit(self):
        with patch('onos.cli.webbrowser.open', return_value=True) as browser:
            code, _, _ = self.invoke(['access', '--open'])
        self.assertEqual(code, 0)
        browser.assert_called_once_with('https://www.onos.gov.in/ums/check-access')

    def test_json_journal_results(self):
        with patch('onos.cli.ONOSClient') as factory:
            client = factory.return_value.__enter__.return_value
            client.search_journals.return_value = [Journal('Nature', 'Springer', 'https://nature.com')]
            code, out, err = self.invoke(['journals', 'nature', '--limit', '2', '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]['title'], 'Nature')
        self.assertEqual(err, '')
        client.search_journals.assert_called_once_with('nature', subject_codes=[], limit=2)

    def test_article_page_json_preserves_cursor(self):
        article = Article('10.1234/test', 'Test', (), '', '', (), None, 'https://example.org')
        with patch('onos.cli.ONOSClient') as factory:
            client = factory.return_value.__enter__.return_value
            client.search_articles.return_value = ArticlePage((article,), 10, 'next+/=')
            code, out, _ = self.invoke(['articles', 'test', '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['next_cursor'], 'next+/=')
        self.assertEqual(json.loads(out)['items'][0]['source'], 'crossref')

    def test_service_error_has_no_traceback_or_stdout(self):
        with patch('onos.cli.ONOSClient') as factory:
            factory.return_value.__enter__.return_value.list_publishers.side_effect = ResponseError('changed')
            code, out, err = self.invoke(['publishers'])
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertEqual(err.strip(), 'onos: changed')

    def test_access_check_requires_a_doi(self):
        code, out, err = self.invoke(['access', '--check'])
        self.assertEqual(code, 1)
        self.assertIn('requires a DOI', err)
        self.assertEqual(out, '')

    def test_invalid_cli_limit_is_a_usage_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['journals', 'Nature', '--limit', '0'])
        self.assertEqual(error.exception.code, 2)
