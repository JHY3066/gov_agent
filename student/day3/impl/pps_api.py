# -*- coding: utf-8 -*-
"""
PPS(나라장터) OpenAPI 어댑터
- 목적: 키워드 기반 입찰/공고 검색 결과를 Day3가 쓰는 공통 구조로 반환
- 환경변수:
  - PPS_API_KEY    : API 인증키 (필수)
  - PPS_API_BASE   : 엔드포인트 베이스 URL (선택, 없으면 기본값 사용)
  - PPS_API_PATH   : 검색 API 경로 (선택)
- 참고: 실제 스펙은 기관/버전에 따라 다르니, 필드 매핑은 필요 시 수정하세요.
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
import os, time

try:
    import requests  # requests가 없으면 안전 폴백
except Exception:
    requests = None

DEFAULT_TOPK = 5
DEFAULT_TIMEOUT = 15

# 기관 환경에 맞는 기본값(예시용; 실제 스펙에 맞게 변경 필요)
DEFAULT_BASE = os.getenv("PPS_API_BASE", "https://apis.data.go.kr/1230000/ad/BidPublicInfoService")         # 예시
DEFAULT_PATH = os.getenv("PPS_API_PATH", "/getBidPblancListInfoCnstwk")                  # 예시

def _get_api_key() -> str:
    return os.getenv("PPS_API_KEY", "")

def _normalize_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    공통 스키마 예:
    - title, url, source, published_at, deadline, agency, category, raw
    실제 필드명은 PPS 응답 스펙에 맞게 수정하세요.
    아래는 대표적으로 쓰이는 키 이름 예시를 매핑한 것.
    """
    title = raw.get("bidNtceNm") or raw.get("title") or ""
    url = raw.get("bidNtceDetailUrl") or raw.get("url") or ""
    src = "pps.go.kr"
    pub = raw.get("ntceStartDt") or raw.get("published_at") or ""
    due = raw.get("ntceEndDt") or raw.get("closingDt") or ""
    agency = raw.get("ntceInsttNm") or raw.get("agency") or ""
    cat = raw.get("bidClsfcNoNm") or raw.get("category") or ""

    return {
        "title": title.strip(),
        "url": url.strip(),
        "source": src,
        "published_at": pub,
        "deadline": due,
        "agency": agency,
        "category": cat,
        "raw": raw,
    }

def pps_fetch_bids(query: str, topk: int = DEFAULT_TOPK, timeout: int = DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
    """
    키워드(query)로 PPS OpenAPI를 조회하고 상위 topk를 정규화해 반환.
    - 키/엔드포인트 누락 시: [] 반환(파이프라인은 계속)
    - 네트워크/호출 실패 시: [] 반환
    """
    api_key = _get_api_key()
    if not api_key or requests is None:
        # 키가 없거나 requests 미설치면 조용히 빈 결과 반환(전체 흐름 유지)
        return []

    base = DEFAULT_BASE.rstrip("/")
    path = DEFAULT_PATH
    url = f"{base}{path}"

    # ⚠ 실제 파라미터 이름은 기관 스펙에 맞게 수정 필요
    params = {
        "serviceKey": api_key,      # 예시: 인증키
        "keyword": query,           # 예시: 검색어
        "page": 1,
        "pageSize": min(max(topk, 1), 50),
        # "type": "json"            # 응답 포맷 등 필요시 추가
    }

    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    # ⚠ 응답 구조에 맞게 경로 수정 (아래는 예시)
    items = []
    # 예: {"response":{"body":{"items":[...]}}} 형태일 수 있음
    raw_items = (
        data.get("response", {})
            .get("body", {})
            .get("items", [])
        if isinstance(data, dict) else []
    )
    if not raw_items and isinstance(data, dict) and "items" in data:
        raw_items = data["items"]

    for r in raw_items[:topk]:
        try:
            items.append(_normalize_item(r))
        except Exception:
            continue

    return items
