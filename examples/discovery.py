"""Search a journal, then search its article metadata and prepare an access link."""

from onos import ONOSClient

with ONOSClient() as client:
    journals = client.search_journals('Nature Physics')
    for journal in journals[:1]:
        print(journal.title, journal.issns)
        if journal.issns:
            page = client.search_articles('quantum measurement', issn=journal.issns[0], limit=3)
            for article in page.items:
                print(article.title)
                print(client.access_url(article.url))
