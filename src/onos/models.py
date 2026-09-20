"""Immutable typed results, serializable with dataclasses.asdict."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Journal:
    title: str
    publisher: str
    url: str
    print_issn: str | None = None
    online_issn: str | None = None
    subject: str = ""

    @property
    def issns(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(i for i in (self.print_issn, self.online_issn) if i))


@dataclass(frozen=True)
class Publisher:
    id: str
    name: str
    urls: tuple[str, ...] = ()
    journal_count: int | None = None
    backfiles_from: str | None = None


@dataclass(frozen=True)
class Institution:
    id: str
    name: str
    aishe_code: str | None
    city: str
    state: str
    access_type: str  # campus_ip, institutional_login, or unknown


@dataclass(frozen=True)
class Subject:
    code: str
    name: str
    discipline: str


@dataclass(frozen=True)
class Article:
    doi: str
    title: str
    authors: tuple[str, ...]
    journal: str
    publisher: str
    issns: tuple[str, ...]
    published: str | None
    url: str
    source: str = "crossref"


@dataclass(frozen=True)
class ArticlePage:
    items: tuple[Article, ...]
    total_results: int
    next_cursor: str | None


@dataclass(frozen=True)
class AccessResult:
    article: Article
    matched_journals: tuple[Journal, ...]
    catalog_status: str  # matched, not_found, or unknown (no valid article ISSNs)
    access_url: str
    note: str = (
        "Journal matching does not confirm article-level entitlement or year coverage. "
        "Use your institution's campus network or complete institutional login through ONOS."
    )
