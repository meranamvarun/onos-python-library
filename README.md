# onos-india

An **unofficial** Python library and command-line tool for India's **One Nation One Subscription (ONOS)** initiative. Python 3.10+, with no third-party runtime dependencies.

Search ONOS journals, subjects, publishers, and registered institutions; discover article metadata through Crossref; match article ISSNs to the ONOS catalog; and generate links into ONOS's institutional access workflow.

This project is not affiliated with ONOS, INFLIBNET, or the Government of India. It is unrelated to the Open Network Operating System project.

## Install

From this repository:

```sh
python -m pip install .
```

For development:

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

The distribution is named `onos-india`; the Python import and CLI command are `onos`. It has not been published to PyPI. The CLI is also available as `python -m onos` if the scripts directory is not on your PATH.

## Python quick start

```python
from onos import ONOSClient

with ONOSClient() as client:
    for journal in client.search_journals("0028-0836"):
        print(journal.title, journal.publisher, journal.issns)
        print(client.access_url(journal.url))

    institutions = client.search_institutions(
        "Aligarh", state="Uttar Pradesh"
    )
    for institution in institutions:
        print(institution.name, institution.aishe_code, institution.access_type)

    publishers = client.list_publishers("Springer")
    subjects = client.list_subjects()
    multidisciplinary = client.search_journals(subject_codes=[1000])
```

Results are immutable dataclasses. Use `dataclasses.asdict(result)` for a dictionary.

### Articles and access

Article search uses **Crossref**, which is a separate metadata provider. Search results are not automatically restricted to journals covered by ONOS. Restrict a search to a discovered journal's ISSN, or explicitly check a DOI against ONOS:

```python
from onos import ONOSClient

with ONOSClient(mailto="you@example.org") as client:
    page = client.search_articles("quantum measurement", issn="1745-2473", limit=5)
    for article in page.items:
        print(article.title, article.doi, article.url)

    if page.next_cursor:
        next_page = client.search_articles(
            "quantum measurement", issn="1745-2473",
            limit=5, cursor=page.next_cursor,
        )

    article = client.get_article("10.1038/nphys1170")
    result = client.check_article_access(article)
    print(result.catalog_status)  # matched, not_found, or unknown
    print(result.matched_journals)
    print(result.access_url)
    print(result.note)
```

The optional `mailto` value is sent only to Crossref for its polite access pool. Keep the query, ISSN, and page size unchanged when continuing a cursor. A final short or empty page has `next_cursor=None`. Pagination is explicit, so the library does not automatically download large result sets.

`check_article_access()` compares valid ISSNs exactly. `matched` means an article's journal appears in the catalog; it does **not** confirm the article's subscription-year coverage, your institution's entitlement, or full-text access. `not_found` means none of the supplied valid ISSNs matched; `unknown` means the article has no usable ISSNs. Provider failures raise exceptions rather than returning `not_found`.

Generate a link without any network requests:

```python
from onos import access_url

print(access_url("10.1038/nphys1170"))
print(access_url("https://www.nature.com/articles/nphys1170"))
print(access_url())  # institution selection page
```

Open the link and complete ONOS's normal institution selection and login, or use your institution's campus network. This version does not log in, store institutional credentials, download article PDFs, or bypass publisher access controls. Crossref metadata availability is independent of full-text availability.

## Command-line interface

```sh
onos journals "Nature" --limit 5
onos journals "0028-0836" --json
onos journals --subject 1000 --limit 10
onos subjects --json
onos publishers "Springer"
onos institutions "Aligarh" --state "Uttar Pradesh"
onos institutions --aishe U-0496 --json
onos articles "quantum measurement" --issn 1745-2473 --limit 5 --json
onos article "10.1038/nphys1170" --json
onos access "10.1038/nphys1170"
onos access "10.1038/nphys1170" --check --json
onos access "10.1038/nphys1170" --open
```

Global options go **before** the subcommand:

```sh
onos --timeout 20 --retries 1 --no-cache journals "Nature"
onos --mailto you@example.org articles "climate change" --limit 5 --json
```

`--json` goes after the subcommand and produces machine-readable JSON on stdout. Errors go to stderr. Exit codes are 0 for success (including an empty result), 1 for input/service errors, 2 for argument-parser errors, and 130 for interruption. `--open` launches a browser only when explicitly supplied. `access --check` takes a DOI or doi.org URL, while plain `access` also accepts publisher URLs.

For articles, JSON includes `items`, `total_results`, and `next_cursor`; pass the last value using `--cursor`. Discovery list commands emit arrays. CLI journal and institution results default to a local limit of 20; increase `--limit` to show more. Library calls return all matching catalog entries unless a limit is supplied.

## API reference

| Method | Behavior |
| --- | --- |
| `search_journals(query, *, subject_codes=(), limit=None)` | Search title/ISSN, or up to five broad subject codes such as 1000 or 1100 |
| `list_subjects()` | Subject descriptions and codes grouped by discipline |
| `list_publishers(query="")` | Publishers, portal IDs, URLs, journal counts, backfile start years |
| `search_institutions(query="", *, state=None, city=None, aishe_code=None, limit=None)` | Directory search; optional exact filters ignoring case |
| `search_articles(query, *, issn=None, limit=20, cursor="*")` | One Crossref page, with a maximum size of 1000 |
| `get_article(doi)` | Crossref metadata for a DOI or doi.org URL |
| `check_article_access(article_or_doi)` | Exact ISSN catalog matching and an ONOS access link |
| `access_url(target=None)` | Offline DOI/publisher URL handoff to ONOS |
| `clear_cache()` | Discard both services' cached metadata |
| `close()` | Clear owned sessions and caches; also called by a context manager |

`CrossrefClient` is available independently if only article metadata is needed. `normalize_doi()` and checksum-validating `normalize_issn()` are also exported.

Institution `access_type` is `campus_ip`, `institutional_login`, or `unknown`, based on the public directory's status. It is descriptive metadata, not an active check of the current user's access.

### Errors and request behavior

```python
from onos import ONOSClient, ONOSError, RateLimitError

try:
    with ONOSClient(timeout=30, retries=2, cache_ttl=300) as client:
        journals = client.search_journals("machine learning")
except RateLimitError:
    print("The service is busy; try again later.")
except ONOSError as exc:
    print(f"Discovery failed: {exc}")
```

Public exceptions are `ONOSError`, `NetworkError`, `HTTPError`, `NotFoundError`, `RateLimitError`, and `ResponseError`. Invalid inputs raise `ValueError`. A changed response schema raises `ResponseError` rather than silently returning no matches.

Each service uses its own cookie session, a 0.5-second minimum interval between requests, up to two retries for transient connection/HTTP failures, and a five-minute in-memory cache capped at 128 responses. TLS verification is enabled. `Retry-After` is respected; waits above 60 seconds return an HTTP error immediately so the caller can retry later. Cache entries are not written to disk. ONOS's expired CSRF token is refreshed once. Public ONOS POSTs are read-only searches.

For custom pacing or test doubles, inject an `HTTPTransport` through `transport=` or `crossref_transport=`. Injected transports remain owned by their caller. Sessions are synchronous and not thread safe; create a separate client for each thread.

## Data sources and limitations

The ONOS website does not provide a documented public API that this project could identify. The adapter reproduces read-only requests used by the public website. These interfaces may change without notice; this is an alpha release. Interfaces were inspected and live-tested on **2026-09-20**.

| Source | Interface used |
| --- | --- |
| [ONOS journal search](https://www.onos.gov.in/journalSearch) | GET session page; POST `/searchJournal` with `type`, `searchTitle`, or `subjects[]` |
| [ONOS journal search script](https://www.onos.gov.in/assets/custom/journal.js) | Subject metadata through POST `/fetchSubject`; access handoff format |
| [ONOS registered institutions](https://www.onos.gov.in/instituteList) | GET `/instituteDetails`, then local filtering |
| [ONOS publishers](https://www.onos.gov.in/publishers) | Public HTML publisher cards |
| [ONOS access portal](https://www.onos.gov.in/ums/check-access) | `target` query value containing a URL-encoded Base64 target URL |
| [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | `/works` and `/works/{doi}` for metadata |
| [Crossref authentication](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/) | Optional polite-pool email |

ONOS currently returns all institution entries and all journal matches for each request; local filtering/limits do not reduce those response sizes. The package does not maintain an offline catalog. Publisher cards are parsed from HTML, making that adapter particularly sensitive to portal layout changes. Subject search accepts the broad discipline codes, such as 1100; individual subject-area entries in `list_subjects()` are informational in this version.

## Development and verification

```sh
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
```

Tests are offline and use trimmed public response fixtures plus mocked transports. They cover request contracts, CSRF refresh, parsing, exact ISSN matching, error handling, retry limits, caching, cursor pagination, access URLs, and CLI output. The CI workflow runs offline tests on Linux and Windows with Python 3.10, 3.12, and 3.14.

For an explicit live integration check (performs a small number of public requests):

```sh
python examples/live_smoke.py
```

## License

MIT. See [LICENSE](LICENSE). The code license does not grant rights to publisher content; resource access remains subject to institutional eligibility and publisher terms.
