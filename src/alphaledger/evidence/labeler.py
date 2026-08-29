"""The seam between a news labeler and the deterministic feature pipeline.

`news.build` consumes `NewsLabel` records and never asks where they came from.
That separation is the reason the whole family stays reproducible: the labeler
is the one component whose output is a model's judgement, and a judgement that
leaked into feature construction would make a rebuilt run disagree with the run
it claims to reproduce.

What lives here is the narrow contract around that call, and nothing else. The
LLM client, its caching by article and prompt hash, and the validation of
Prompt B's consistency rules are a later unit's work, because they need
credentials and a network boundary. `NewsLabeler` is a `Protocol` so that unit,
and every test, can supply an implementation without importing anything from
here.

`labels_by_article` is the deterministic half. It decides which earlier stories
a labeler may see, refuses an article the panel mis-assembled before a model is
paid to read it, and refuses an answer that is about a different article or a
different company than the one asked about. That last check is not paranoia
about models specifically: any adapter that batches requests can mismatch a
reply to a request, and the mismatch would be invisible afterwards because the
label would sit under the right key holding the wrong judgement.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from alphaledger.domain.contracts import NewsLabel
from alphaledger.evidence.news import Article

__all__ = [
    "DEFAULT_MAX_PRIOR_CONTEXT",
    "LabelerContractError",
    "NewsLabeler",
    "labels_by_article",
]

# Prompt B takes "zero or more" earlier headlines and names no bound. An
# unbounded context would grow the prompt with the symbol's news volume, so a
# busy day would be labelled under a different amount of context than a quiet
# one, and the difference would show up in the features as if it were news.
DEFAULT_MAX_PRIOR_CONTEXT = 5


class LabelerContractError(ValueError):
    """A labeler answered about something other than what it was asked."""


@runtime_checkable
class NewsLabeler(Protocol):
    """Label one article for one ticker, as of that article's first sighting.

    `prior_context` holds earlier articles about the same ticker, oldest
    first, already restricted to what was knowable when `subject` was first
    seen. An implementation must not consult anything else: Prompt B forbids
    outside knowledge, and the point-in-time claim rests on it.
    """

    def label(
        self,
        subject: Article,
        ticker: str,
        prior_context: tuple[Article, ...],
    ) -> NewsLabel: ...


def labels_by_article(
    labeler: NewsLabeler,
    ticker: str,
    articles: Iterable[Article],
    *,
    max_prior_context: int = DEFAULT_MAX_PRIOR_CONTEXT,
) -> dict[str, NewsLabel]:
    """Label every article for `ticker`, keyed by `article_id` for `build`.

    Articles are visited oldest first so each one's prior context contains
    only stories that preceded it. Ties are broken by `article_id`, which
    gives a total order and keeps the context a function of the data rather
    than of the order the feed happened to return.
    """
    if isinstance(max_prior_context, bool) or not isinstance(max_prior_context, int):
        raise TypeError(
            f"max_prior_context must be a whole number of articles; got {max_prior_context!r}"
        )
    if max_prior_context < 0:
        raise ValueError(
            f"max_prior_context must not be negative; got {max_prior_context!r}. "
            "Use zero to label each article with no prior context at all"
        )
    subject_ticker = str(ticker).strip()
    if not subject_ticker:
        raise ValueError("ticker must name the company being labelled; it is never defaulted")

    ordered = _in_time_order(articles, subject_ticker)
    labels: dict[str, NewsLabel] = {}
    seen: list[Article] = []
    for item in ordered:
        context = tuple(seen[-max_prior_context:]) if max_prior_context else ()
        produced = labeler.label(item, subject_ticker, context)
        _check_answer(produced, item, subject_ticker)
        labels[item.article_id] = produced
        seen.append(item)
    return labels


def _in_time_order(articles: Iterable[Article], ticker: str) -> Sequence[Article]:
    """Oldest first, refusing an article this ticker's panel should not hold.

    The refusal happens before any labeling, so a mis-assembled panel costs
    nothing to detect. `news.build` refuses the same article again; the check
    is duplicated on purpose, because these two entry points are reachable
    independently and neither may assume the other ran.
    """
    held: list[Article] = []
    for item in articles:
        if ticker not in item.symbols:
            raise LabelerContractError(
                f"{item.article_id} is tagged {item.symbols} and not {ticker}, so it does "
                "not belong to this symbol's panel. Whatever assembled the panel is wrong"
            )
        held.append(item)
    return sorted(held, key=lambda item: (item.timestamps.first_seen_time, item.article_id))


def _check_answer(produced: NewsLabel, subject: Article, ticker: str) -> None:
    """Refuse a label that is about a different article or a different company."""
    if produced.article_id != subject.article_id:
        raise LabelerContractError(
            f"the labeler was asked about {subject.article_id} and answered about "
            f"{produced.article_id}. Filing that answer under the article it was asked "
            "about would attach a judgement to a story nobody judged"
        )
    if produced.ticker != ticker:
        raise LabelerContractError(
            f"the labeler was asked about {ticker} and answered about {produced.ticker} "
            f"for article {subject.article_id}"
        )
