# -*- coding: utf-8 -*-
"""
Day1 본체
- 역할: 웹 검색 / 주가 / 기업개요(추출+요약)를 병렬로 수행하고 결과를 정규 스키마로 병합
"""

from __future__ import annotations
from dataclasses import asdict
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from student.day1.impl.competitor_intel import build_competitor_intel_from_pages
from student.day1.impl.tavily_client import extract_text
from student.day1.impl.web_search import looks_like_competitor_intel_query

from google.adk.models.lite_llm import LiteLlm
from student.common.schemas import Day1Plan
from student.day1.impl.merge import merge_day1_payload
# 외부 I/O
from student.day1.impl.tavily_client import search_tavily, extract_url
from student.day1.impl.finance_client import get_quotes
from student.day1.impl.web_search import (
    looks_like_ticker,
    search_company_profile,
    extract_and_summarize_profile,
)

DEFAULT_WEB_TOPK = 6
MAX_WORKERS = 4
DEFAULT_TIMEOUT = 20

# ------------------------------------------------------------------------------
# TODO[DAY1-I-01] 요약용 경량 LLM 준비
#  - 목적: 기업 개요 본문을 Extract 후 간결 요약
#  - LiteLlm(model="openai/gpt-4o-mini") 형태로 _SUM에 할당
# ------------------------------------------------------------------------------
_SUM: Optional[LiteLlm] = LiteLlm(model="openai/gpt-4o-mini")


def _summarize(text: str) -> str:
    """
    입력 텍스트를 LLM으로 3~5문장 수준으로 요약합니다.
    실패 시 빈 문자열("")을 반환해 상위 로직이 안전하게 진행되도록 합니다.
    """
    # ----------------------------------------------------------------------------
    # TODO[DAY1-I-02] 구현 지침
    #  - _SUM이 None이면 "" 반환(요약 생략)
    #  - _SUM.invoke({...}) 혹은 단순 텍스트 인자 형태로 호출 가능한 래퍼라면
    #    응답 객체에서 본문 텍스트를 추출하여 반환
    #  - 예외 발생 시 빈 문자열 반환
    # ----------------------------------------------------------------------------
    if not _SUM:
        return ""
    try:
        response = _SUM.invoke(text) if hasattr(_SUM, "invoke") else _SUM(text)
        if isinstance(response, str):
            return response.strip()
        if isinstance(response, dict):
            return (response.get("text") or response.get("content") or "").strip()
        return getattr(response, "text", getattr(response, "content", "")).strip()
    except Exception:
        return ""


class Day1Agent:
    def __init__(self, tavily_api_key: Optional[str], web_topk: int = DEFAULT_WEB_TOPK, request_timeout: int = DEFAULT_TIMEOUT):
        """
        필드 저장만 담당합니다.
        - tavily_api_key: Tavily API 키(없으면 웹 호출 실패 가능)
        - web_topk: 기본 검색 결과 수
        - request_timeout: 각 HTTP 호출 타임아웃(초)
        """
        # ----------------------------------------------------------------------------
        # TODO[DAY1-I-03] 필드 저장
        #  self.tavily_api_key = tavily_api_key
        #  self.web_topk = web_topk
        #  self.request_timeout = request_timeout
        # ----------------------------------------------------------------------------
        self.tavily_api_key = tavily_api_key
        self.web_topk = web_topk
        self.request_timeout = request_timeout

    def handle(self, query: str, plan: Day1Plan) -> Dict[str, Any]:
        """
        병렬 파이프라인:
          1) results 스켈레톤 만들기
             results = {"type":"web_results","query":query,"analysis":asdict(plan),"items":[],
                        "tickers":[], "errors":[], "company_profile":"", "profile_sources":[]}
          2) ThreadPoolExecutor(max_workers=MAX_WORKERS)에서 작업 제출:
             - plan.do_web: search_tavily(검색어, 키, top_k=self.web_topk, timeout=...)
             - plan.do_stocks: get_quotes(plan.tickers)
             - (기업개요) looks_like_ticker(query) 또는 plan에 tickers가 있을 때:
                 · search_company_profile(query, api_key, topk=2) → URL 상위 1~2개
                 · extract_and_summarize_profile(urls, api_key, summarizer=_summarize)
          3) as_completed로 결과 수집. 실패 시 results["errors"]에 '작업명:에러' 저장.
          4) merge_day1_payload(results) 호출해 최종 표준 스키마 dict 반환.
        """
        # ----------------------------------------------------------------------------
        # TODO[DAY1-I-04] 구현 지침(권장 구조)
        #  - results 초기화 (위 키 포함)
        #  - futures 딕셔너리: future -> "web"/"stock"/"profile" 등 라벨링
        #  - 병렬 제출 조건 체크(plan.do_web, plan.do_stocks, 기업개요 조건)
        #  - 완료 수집:
        #      kind == "web"    → results["items"] = data
        #      kind == "stock"  → results["tickers"] = data
        #      kind == "profile"→ results["company_profile"] = text; results["profile_sources"] = urls(옵션)
        #  - 예외: results["errors"].append(f"{kind}: {type(e).__name__}: {e}")
        #  - return merge_day1_payload(results)
        # ----------------------------------------------------------------------------

        # 1) 결과 스켈레톤
        results: Dict[str, Any] = {
            "type": "web_results",
            "query": query,
            "analysis": asdict(plan),
            "items": [],
            "tickers": [],
            "errors": [],
            "company_profile": "",
            "profile_sources": [],
            "extras": {},
        }

        # 실행 파라미터(안전 접근)
        tavily_key = getattr(self, "tavily_api_key", None)
        web_topk = getattr(self, "web_topk", DEFAULT_WEB_TOPK)
        timeout = getattr(self, "request_timeout", DEFAULT_TIMEOUT)

        futures = {}

        # 기업개요 잡(job)
        def _profile_job(q: str) -> Tuple[str, List[str]]:
            # api_key는 내부에서 환경변수 등을 사용할 수 있으므로 None 전달 허용
            urls: List[str] = search_company_profile(q, api_key=None, topk=2)
            text: str = extract_and_summarize_profile(urls, api_key=None, summarizer=_summarize)
            return text, urls

        # 2) 병렬 제출
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            if getattr(plan, "do_web", False):
                futures[ex.submit(search_tavily, query, tavily_key, top_k=web_topk, timeout=timeout)] = "web"

            if getattr(plan, "do_stocks", False):
                tickers = list(getattr(plan, "tickers", []) or [])
                if tickers:
                    futures[ex.submit(get_quotes, tickers, timeout=timeout)] = "stock"

            # 기업개요 조건: 질의가 티커처럼 보이거나, 계획상 티커가 존재
            if looks_like_ticker(query) or bool(getattr(plan, "tickers", [])):
                futures[ex.submit(_profile_job, query)] = "profile"

            # 3) 완료 수집
            for fut in as_completed(futures):
                kind = futures[fut]
                try:
                    data = fut.result()
                    if kind == "web":
                        results["items"] = data or []
                    elif kind == "stock":
                        results["tickers"] = data or []
                    elif kind == "profile":
                        profile_text, src_urls = data
                        results["company_profile"] = profile_text or ""
                        results["profile_sources"] = src_urls or []
                except Exception as e:
                    results["errors"].append(f"{kind}: {type(e).__name__}: {e}")

        # 4) 정규 스키마로 병합하여 반환
        try:
            need_intel = looks_like_competitor_intel_query(query) or getattr(plan, "mode", "") == "competitor_intel"
            if need_intel and results.get("items"):
                web_items = results["items"][:8]
                pages: List[Dict[str, str]] = []
                with ThreadPoolExecutor(max_workers=min(6, len(web_items))) as pool:
                    futmap = {}
                    for it in web_items:
                        url = it.get("url") or it.get("link")
                        title = it.get("title") or ""
                        if not url:
                            continue
                        fut = pool.submit(extract_text, url, self.tavily_api_key, self.request_timeout)
                        futmap[fut] = (url, title)

                    for fut in as_completed(futmap):
                        url, title = futmap[fut]
                        try:
                            text = fut.result() or ""
                            pages.append({"url": url, "title": title, "text": text})
                        except Exception:
                            pages.append({"url": url, "title": title, "text": ""})

                intel = build_competitor_intel_from_pages(pages, query)
                results.setdefault("extras", {})["competitor_intel"] = asdict(intel)
        except Exception as e:
            results["errors"].append(f"competitor_intel: {type(e).__name__}: {e}")

        return merge_day1_payload(results)

    def _get_profile_block(self, query: str) -> Tuple[str, List[str]]:
        """
        기업 개요 블록을 가져오고 요약까지 수행하는 내부 헬퍼.
        """
        try:
            urls = search_company_profile(query, self.tavily_api_key, topk=2)
            if not urls:
                return "", []
            profile_text = extract_and_summarize_profile(urls, self.tavily_api_key, summarizer=_summarize)
            return profile_text, urls
        except Exception:
            return "", []
