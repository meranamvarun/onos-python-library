# Public-response fixtures

Trimmed responses observed on 2026-09-20:

- `journals.json`: POST `https://www.onos.gov.in/searchJournal`, `type=title`, `searchTitle=0028-0836`.
- `subjects.json`: two groups from POST `https://www.onos.gov.in/fetchSubject`.
- `institutions.json`: three rows from GET `https://www.onos.gov.in/instituteDetails`; only public directory fields retained.
- `publishers.html`: first two publisher cards from `https://www.onos.gov.in/publishers`.
- `article.json`: selected metadata from `https://api.crossref.org/works/10.1038%2Fnphys1170`.

No cookies, CSRF tokens, login credentials, or institutional contact records are included. Fixtures test response structure, not current catalog totals. Additional malformed/error cases are constructed in tests.
