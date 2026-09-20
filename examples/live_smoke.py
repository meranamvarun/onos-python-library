"""Opt-in integration check. Run after installing the package; requires internet."""

from onos import ONOSClient


def main():
    with ONOSClient(timeout=30, retries=1) as client:
        journals = client.search_journals('0028-0836')
        assert any(j.title == 'Nature' for j in journals), 'Nature missing from ISSN search'
        print(f'Journal search: {len(journals)} result(s)')
        subjects = client.list_subjects()
        assert any(s.code == '1000' for s in subjects), 'Expected broad subject missing'
        print(f'Subject metadata: {len(subjects)} entries')
        subject_journals = client.search_journals(subject_codes=[1000], limit=2)
        assert subject_journals, 'Broad subject search is empty'
        print('Broad subject search: OK')
        publishers = client.list_publishers()
        assert publishers, 'No publisher cards recognized'
        print(f'Publishers: {len(publishers)}')
        institutions = client.search_institutions(aishe_code='U-0496')
        assert any(i.name == 'Aligarh Muslim University' for i in institutions)
        print('Institution search: OK')
        article = client.get_article('10.1038/nphys1170')
        assert article.title == 'Measured measurement'
        print(f'DOI lookup: {article.title}')
        page = client.search_articles('quantum measurement', issn='1745-2473', limit=1)
        assert page.items, 'Crossref returned no articles'
        if page.next_cursor:
            next_page = client.search_articles('quantum measurement', issn='1745-2473',
                                               limit=1, cursor=page.next_cursor)
            assert next_page.items and next_page.items[0].doi != page.items[0].doi
        print('Article search and cursor pagination: OK')
        access = client.check_article_access(article)
        assert access.catalog_status == 'matched', 'Expected journal catalog match'
        print(f'Article journal membership: {access.catalog_status} (entitlement not checked)')
        print('Live integration checks passed.')


if __name__ == '__main__':
    main()
