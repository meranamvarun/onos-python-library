"""Command-line discovery and access links. JSON goes to stdout; errors to stderr."""

import argparse
import json
import sys
import webbrowser
from dataclasses import asdict, is_dataclass

from . import __version__
from ._utils import access_url
from .client import ONOSClient
from .errors import ONOSError
from .models import AccessResult, ArticlePage


def _positive(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if result < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="onos", description=(
        "Unofficial One Nation One Subscription discovery. Article metadata uses Crossref; "
        "institutional authentication is completed in your browser."))
    root.add_argument("--version", action="version", version=f"onos-india {__version__}")
    root.add_argument("--timeout", type=float, default=30, help="HTTP timeout in seconds (default: 30)")
    root.add_argument("--retries", type=int, default=2, help="transient failure retries, 0-5 (default: 2)")
    root.add_argument("--mailto", help="contact email sent only to Crossref for its polite pool")
    root.add_argument("--no-cache", action="store_true", help="disable the in-memory response cache")
    sub = root.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit structured JSON")

    journals = sub.add_parser("journals", parents=[common], help="search ONOS journal titles or ISSNs")
    journals.add_argument("query", nargs="?")
    journals.add_argument("--subject", action="append", default=[], help="broad subject code; repeat up to five times")
    journals.add_argument("--limit", type=_positive, default=20, help="maximum displayed results (default: 20)")

    sub.add_parser("subjects", parents=[common], help="list ONOS subject codes")
    publishers = sub.add_parser("publishers", parents=[common], help="list participating publishers")
    publishers.add_argument("query", nargs="?", default="")
    institutions = sub.add_parser("institutions", parents=[common], help="search registered institutions")
    institutions.add_argument("query", nargs="?", default="")
    institutions.add_argument("--state")
    institutions.add_argument("--city")
    institutions.add_argument("--aishe", dest="aishe_code")
    institutions.add_argument("--limit", type=_positive, default=20)

    articles = sub.add_parser("articles", parents=[common], help="search Crossref article metadata")
    articles.add_argument("query")
    articles.add_argument("--issn", help="restrict to one journal")
    articles.add_argument("--limit", type=_positive, default=20, help="page size, 1-1000")
    articles.add_argument("--cursor", default="*", help="next_cursor from a previous JSON result")
    article = sub.add_parser("article", parents=[common], help="look up one DOI in Crossref")
    article.add_argument("doi")

    access = sub.add_parser("access", parents=[common], help="generate an ONOS institutional access link")
    access.add_argument("target", nargs="?", help="DOI or HTTP(S) publisher URL")
    access.add_argument("--check", action="store_true", help="look up a DOI and match its ISSNs to ONOS journals")
    access.add_argument("--open", action="store_true", help="open the resulting link in your default browser")
    return root


def _serializable(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (tuple, list)):
        return [_serializable(item) for item in value]
    return value


def _clean(value) -> str:
    # Remote metadata must not inject terminal escape sequences or extra lines.
    return " ".join("".join(c for c in str(value) if c.isprintable() or c.isspace()).split())


def _text(value) -> None:
    if isinstance(value, ArticlePage):
        print(f"Crossref: {value.total_results} results; showing {len(value.items)}.")
        print("ONOS journal coverage has not been checked.")
        _text(value.items)
        if value.next_cursor:
            print("More results available; use --json to retrieve next_cursor.")
        return
    if isinstance(value, AccessResult):
        print(f"Catalog status: {_clean(value.catalog_status)}")
        print(f"Article: {_clean(value.article.title)}")
        for journal in value.matched_journals:
            print(f"Matched journal: {_clean(journal.title)}")
        print(value.access_url)
        print(value.note)
        return
    records = value if isinstance(value, (list, tuple)) else [value]
    if not records:
        print("No results found.")
    for i, record in enumerate(records):
        if i:
            print()
        record = _serializable(record)
        if isinstance(record, dict):
            for key, item in record.items():
                if item is None or item == "" or item == ():
                    continue
                if isinstance(item, (list, tuple)):
                    item = "; ".join(str(v) for v in item)
                print(f"{key.replace('_', ' ').title()}: {_clean(item)}")
        else:
            print(_clean(record))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        with ONOSClient(timeout=args.timeout, retries=args.retries,
                        cache_ttl=0 if args.no_cache else 300, mailto=args.mailto) as client:
            if args.command == "journals":
                result = client.search_journals(args.query, subject_codes=args.subject, limit=args.limit)
            elif args.command == "subjects":
                result = client.list_subjects()
            elif args.command == "publishers":
                result = client.list_publishers(args.query)
            elif args.command == "institutions":
                result = client.search_institutions(args.query, state=args.state, city=args.city,
                                                    aishe_code=args.aishe_code, limit=args.limit)
            elif args.command == "articles":
                result = client.search_articles(args.query, issn=args.issn, limit=args.limit, cursor=args.cursor)
            elif args.command == "article":
                result = client.get_article(args.doi)
            else:
                if args.check:
                    if not args.target:
                        raise ValueError("access --check requires a DOI")
                    result = client.check_article_access(args.target)
                    link = result.access_url
                else:
                    link = access_url(args.target)
                    result = {"access_url": link}
                if args.open and not webbrowser.open(link):
                    print("onos: browser could not be opened; use the printed link", file=sys.stderr)
            if args.json:
                print(json.dumps(_serializable(result), ensure_ascii=True, indent=2))
            else:
                _text(result)
        return 0
    except (ONOSError, ValueError) as exc:
        print(f"onos: {_clean(exc)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
