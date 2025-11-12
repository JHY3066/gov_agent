# -*- coding: utf-8 -*-
"""
Day1 결과 정규화
- 다양한 원시 결과(results dict)를 "표준 스키마"로 정리
"""

from typing import Dict, Any, List


def _top_results(items: List[Dict[str, Any]], k: int = 5) -> List[Dict[str, Any]]:
    """
    검색 결과에서 상위 k개만 반환 (None/빈 리스트 안전 처리)
    - items가 None이면 [] 반환
    - k가 0 이하이면 [] 반환
    """
    # ----------------------------------------------------------------------------
    # TODO[DAY1-M-01] 구현 지침
    #  - if not items: return []
    #  - return items[: max(0, k)]
    # ----------------------------------------------------------------------------
    if not items or not isinstance(items, list):
        return []

    if k <= 0:
        return []

    return items[:k]


def merge_day1_payload(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    입력(results) 예:
      {
        "type":"web_results",
        "query":"AAPL 주가와 기업 정보",
        "analysis": {... Day1Plan asdict ...},
        "items":[{title,url,snippet,...}, ...],
        "tickers":[{symbol,price,currency}|{symbol,error}, ...],
        "company_profile":"요약 텍스트",
        "profile_sources":[url1,url2,...],
        "errors":[...]
      }

    출력(정규화) 예:
      {
        "type":"day1",
        "query": "...",
        "web_top":[... 상위 N개 ...],
        "prices":[...],
        "company_profile":"...",
        "profile_sources":[...],
        "errors":[...]
      }
    """
    # ----------------------------------------------------------------------------
    # TODO[DAY1-M-02] 구현 지침
    #  - web_top = _top_results(results.get("items"), k=5)
    #  - prices  = results.get("tickers", [])
    #  - company_profile = results.get("company_profile") or ""
    #  - profile_sources = results.get("profile_sources") or []
    #  - errors = results.get("errors") or []
    #  - query  = results.get("query", "")
    #  - return {...} 형태로 표준 스키마 dict 생성
    # ----------------------------------------------------------------------------
    web_top = _top_results(results.get("items"), k=5)
    prices = results.get("tickers", [])
    company_profile = results.get("company_profile") or ""
    profile_sources = results.get("profile_sources") or []
    errors = results.get("errors") or []
    query = results.get("query", "")

    return {
        "type": "day1",
        "query": query,
        "web_top": web_top,
        "prices": prices,
        "company_profile": company_profile,
        "profile_sources": profile_sources,
        "errors": errors
    }

def merge_day2_payload(day2: dict) -> dict:
    """
    DAY2 결과를 상위 응답 스키마로 그대로 pass-through.
    (웹/주가와 혼합 불필요: 독립 섹션으로 UI에서 소비)
    """
    return {"internal_profile": day2}