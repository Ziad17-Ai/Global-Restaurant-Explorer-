"""Orchestration service for rate-limited natural-language restaurant search."""

from __future__ import annotations

import logging
from typing import Literal

from web.backend.constants import QUERY_LOG_MAX_CHARS
from web.backend.logging_config import truncate_query_for_log
from web.backend.repositories.meta_repository import MetaRepository
from web.backend.repositories.restaurant_repository import (
    RestaurantFilter,
    RestaurantRepository,
)
from web.backend.schemas.nlp import (
    NLSearchRequest,
    NLSearchResponseOut,
    SearchParams,
)
from web.backend.services.hf_semantic_matcher import get_cached_semantic_matcher
from web.backend.services.nlp_adapter import (
    HuggingFaceAdapter,
    NLPAdapter,
    NLPProviderError,
    RuleBasedParser,
    load_cuisine_synonyms,
)
from web.backend.services.rate_limiter import SlidingWindowRateLimiter
from web.backend.settings import BackendSettings, settings

logger = logging.getLogger(__name__)


class SearchService:
    """Service coordinating NLP parsing, fallback, logging, and DB search."""

    def __init__(
        self,
        restaurant_repository: RestaurantRepository,
        meta_repository: MetaRepository,
        rate_limiter: SlidingWindowRateLimiter,
        app_settings: BackendSettings | None = None,
        primary_adapter: NLPAdapter | None = None,
        fallback_adapter: NLPAdapter | None = None,
    ) -> None:
        """Initialize SearchService with repositories, limiter, and NLP adapters."""
        self._restaurant_repository = restaurant_repository
        self._meta_repository = meta_repository
        self._rate_limiter = rate_limiter
        self._settings = app_settings or settings
        self._primary_adapter = primary_adapter
        self._fallback_adapter = fallback_adapter

    def _resolve_adapters(self) -> tuple[NLPAdapter, NLPAdapter]:
        """Build or return primary and fallback NLP adapters using live vocabulary."""
        if self._primary_adapter is not None and self._fallback_adapter is not None:
            return self._primary_adapter, self._fallback_adapter

        vocabulary = self._meta_repository.get_vocabulary()
        synonyms = load_cuisine_synonyms(self._settings.cuisine_map_path)
        semantic_matcher = get_cached_semantic_matcher(vocabulary, self._settings)
        fallback = self._fallback_adapter or RuleBasedParser(
            vocabulary=vocabulary,
            cuisine_synonyms=synonyms,
            semantic_matcher=semantic_matcher,
        )
        primary = self._primary_adapter or HuggingFaceAdapter(
            vocabulary=vocabulary,
            cuisine_synonyms=synonyms,
            app_settings=self._settings,
        )
        return primary, fallback

    def search_natural_language(
        self,
        request_payload: NLSearchRequest,
        client_key: str,
    ) -> NLSearchResponseOut:
        """Rate-limit, parse, log safely, and execute a natural-language search."""
        self._rate_limiter.check_and_record(client_key)

        primary_adapter, fallback_adapter = self._resolve_adapters()
        parser_used: Literal["huggingface", "huggingface_semantic", "rule_based"] = (
            "huggingface"
        )
        fallback_used = False
        interpreted_params: SearchParams

        if isinstance(primary_adapter, RuleBasedParser):
            interpreted_params = primary_adapter.parse(request_payload.query)
            parser_used = (
                "huggingface_semantic"
                if primary_adapter.has_active_semantic_matcher
                else "rule_based"
            )
            fallback_used = False
        else:
            try:
                interpreted_params = primary_adapter.parse(request_payload.query)
            except (NLPProviderError, TimeoutError, ValueError, RuntimeError) as exc:
                semantic_active = (
                    isinstance(fallback_adapter, RuleBasedParser)
                    and fallback_adapter.has_active_semantic_matcher
                )
                parser_used = (
                    "huggingface_semantic" if semantic_active else "rule_based"
                )
                logger.warning(
                    "Primary NLP parser failed; falling back to local parser",
                    extra={
                        "parser_used": parser_used,
                        "fallback_used": True,
                        "details": str(exc)[:QUERY_LOG_MAX_CHARS],
                    },
                )
                interpreted_params = fallback_adapter.parse(request_payload.query)
                fallback_used = True

        truncated_query = truncate_query_for_log(
            request_payload.query,
            max_chars=self._settings.logging_query_max_chars,
        )
        logger.info(
            "Processed natural-language search query",
            extra={
                "parser_used": parser_used,
                "fallback_used": fallback_used,
                "query_preview": truncated_query,
            },
        )

        if interpreted_params.needs_clarification is not None:
            return NLSearchResponseOut(
                query=request_payload.query,
                interpreted_params=interpreted_params,
                parser_used=parser_used,
                fallback_used=fallback_used,
                items=[],
                total=0,
                limit=request_payload.limit,
                offset=request_payload.offset,
            )

        criteria = RestaurantFilter(
            country=interpreted_params.country,
            city=interpreted_params.city,
            locality=interpreted_params.locality,
            cuisine=tuple(interpreted_params.cuisine),
            cuisine_group=interpreted_params.cuisine_group,
            min_rating=interpreted_params.min_rating,
            max_cost_for_two=interpreted_params.max_cost_for_two,
            max_cost_usd=interpreted_params.max_cost_usd,
            price_range=interpreted_params.price_range,
            has_online_delivery=interpreted_params.has_online_delivery,
            has_table_booking=interpreted_params.has_table_booking,
            search_query=interpreted_params.search_query,
            sort_by="rating",
            limit=request_payload.limit,
            offset=request_payload.offset,
        )
        items, total = self._restaurant_repository.search_restaurants(criteria)
        return NLSearchResponseOut(
            query=request_payload.query,
            interpreted_params=interpreted_params,
            parser_used=parser_used,
            fallback_used=fallback_used,
            items=items,
            total=total,
            limit=request_payload.limit,
            offset=request_payload.offset,
        )
