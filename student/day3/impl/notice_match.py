# -*- coding: utf-8 -*-
"""
정부/공공 포털 및 일반 웹에서 '사업 공고'를 찾기 위한 검색 래퍼

설계 포인트
- '도메인 제한' + '키워드 보강'을 동시에 사용해 노이즈를 줄입니다.
- Tavily Search API를 통해 결과를 가져오며, 결과 스키마는 Day1 web 결과와 동일한 단순 형태를 사용합니다.
- 여기선 '검색'만 담당합니다. 정규화/랭킹은 normalize.py / rank.py에서 수행합니다.

권장 쿼리 전략
- NIPA(정보통신산업진흥원):  site:nipa.kr  +  ("공고" OR "모집" OR "지원")
- Bizinfo(기업마당):       site:bizinfo.go.kr + 유사 키워드
- 일반 웹(Fallback):       쿼리 + "모집 공고 지원 사업" 같은 보조 키워드로 recall 확보
"""

import urllib.parse
from typing import List, Dict, Any, Optional
import os
# Day1에서 제작한 Tavily 래퍼를 사용합니다.
from student.day1.impl.tavily_client import search_tavily 
import requests

import os
from typing import List, Dict, Any, Optional

PPS_API_KEY = os.getenv("PPS_API_KEY")  # 공공데이터포털/조달청 API 키

# 기본 설정값
DEFAULT_TOPK = 7
DEFAULT_TIMEOUT = 20

# 기본 TopK(권장: NIPA 3, Bizinfo 2, Web 2)
NIPA_TOPK = 3
BIZINFO_TOPK = 2
WEB_TOPK = 2
NARAJANGTER_TOPK = 2

def fetch_narajangter(query: str, topk: int = NARAJANGTER_TOPK) -> List[Dict[str, Any]]:
    """
    나라장터(조달청, g2b.go.kr) 도메인에 한정한 입찰/공고 검색.
    - include_domains=["g2b.go.kr"]
    - '입찰/공고/용역/물품' 키워드 보강
    """

    # 나라장터 내 입찰/공고 관련 문서를 찾기 위한 쿼리
    search_query = f"{query} 입찰 공고 용역 물품 site:g2b.go.kr"

    # Tavily 검색 호출 (NIPA/Bizinfo와 동일한 패턴)
    results = search_tavily( 
        query=search_query,
        top_k=topk,
        timeout=DEFAULT_TIMEOUT,
        include_domains=["g2b.go.kr"],
    )

    return results

def fetch_nipa(query: str, topk: int = NIPA_TOPK) -> List[Dict[str, Any]]:
    """
    NIPA 도메인에 한정한 사업 공고 검색.
    - include_domains=["nipa.kr"] 힌트를 주고, 검색 쿼리에도 site:nipa.kr을 붙입니다.
    - '공고/모집/지원' 같은 키워드로 사업 공고 문서를 우선 노출시킵니다.
    
    반환: Day1 Web 스키마 리스트 [{title, url, content/snippet, ...}, ...]
    """
    # api_key = os.getenv("TAVILY_API_KEY", "")
    
    search_query = f"{query} 공고 모집 지원 site:nipa.kr"

    results = search_tavily(
        query=search_query,
        top_k=topk,
        timeout=DEFAULT_TIMEOUT,
        include_domains=["nipa.kr"]
    )
    
    return results

    # TODO[DAY3-F-01]:
    # 1) os.getenv("TAVILY_API_KEY","")로 키를 읽습니다.
    # 2) 질의 q를 만들 때: f"{query} 공고 모집 지원 site:nipa.kr"
    # 3) search_tavily(q, key, top_k=topk, timeout=DEFAULT_TIMEOUT, include_domains=["nipa.kr"])
    # 4) 그대로 반환

def fetch_bizinfo(query: str, topk: int = BIZINFO_TOPK) -> List[Dict[str, Any]]:
    """
    Bizinfo(기업마당) 도메인에 한정한 사업 공고 검색
    - include_domains=["bizinfo.go.kr"]
    - '공고/모집/지원' 키워드 보강
    """

    search_query = f"{query} 공고 모집 지원 site:bizinfo.go.kr"
    
    # search_tavily를 사용하여 bizinfo.go.kr 도메인으로 한정 검색
    # top_k=topk, timeout=DEFAULT_TIMEOUT, include_domains=["bizinfo.go.kr"]
    results = search_tavily( 
        query=search_query,
        top_k=topk,
        timeout=DEFAULT_TIMEOUT,
        include_domains=["bizinfo.go.kr"]
    )

    return results

    # TODO[DAY3-F-02]:
    # 위 NIPA와 동일한 패턴이며, site:bizinfo.go.kr / include_domains=["bizinfo.go.kr"] 를 사용

def fetch_web(query: str, topk: int = WEB_TOPK) -> List[Dict[str, Any]]:
    """
    일반 웹 Fallback: 사업 공고와 관련된 키워드를 넣어 Recall 확보
    - 도메인 제한 없이 Tavily 기본 검색 사용
    - 가짜/홍보성 페이지 노이즈는 뒤 단계(normalize/rank)에서 걸러냅니다.
    """
    # TODO[DAY3-F-03]:
    # 1) 키 읽기
    # 2) q = f"{query} 모집 공고 지원 사업"
    # 3) search_tavily(q, key, top_k=topk, timeout=DEFAULT_TIMEOUT)
    try:
        # 1) API 키 읽기
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            print("[fetch_web] Warning: TAVILY_API_KEY not set")
            return []
        
        # 2) 사업 공고 관련 키워드를 추가한 쿼리 생성
        q = f"{query} 모집 공고 지원 사업"
        
        # 3) Tavily 검색 호출 (도메인 제한 없음)
        results = search_tavily(
            q, 
            api_key, 
            top_k=topk, 
            timeout=DEFAULT_TIMEOUT
        )
        
        return results
    
    except Exception as e:
        print(f"[fetch_web] Error during web search: {e}")
        return []

def fetch_all(query: str) -> List[Dict[str, Any]]:
    """
    편의 함수: 현재 설정된 전 소스에서 가져오기
    주의) 실전에서는 소스별 topk를 plan을 통해 주입받아야 합니다.
    """
    # TODO[DAY3-F-04]:
    # - 위 세 함수를 순서대로 호출해 리스트를 이어붙여 반환
    # - 실패 시 빈 리스트라도 반환(try/except로 유연 처리 가능)
    all_results = []
    
    try:
        # NIPA 검색
        print(f"[fetch_all] Fetching from NIPA...")
        nipa_results = fetch_nipa(query, topk=NIPA_TOPK)
        all_results.extend(nipa_results)
        print(f"[fetch_all] NIPA: {len(nipa_results)} results")
    except Exception as e:
        print(f"[fetch_all] NIPA search failed: {e}")
    
    try:
        # Bizinfo 검색
        print(f"[fetch_all] Fetching from Bizinfo...")
        bizinfo_results = fetch_bizinfo(query, topk=BIZINFO_TOPK)
        all_results.extend(bizinfo_results)
        print(f"[fetch_all] Bizinfo: {len(bizinfo_results)} results")
    except Exception as e:
        print(f"[fetch_all] Bizinfo search failed: {e}")
    
    try:
        # 일반 웹 검색
        print(f"[fetch_all] Fetching from Web...")
        web_results = fetch_web(query, topk=WEB_TOPK)
        all_results.extend(web_results)
        print(f"[fetch_all] Web: {len(web_results)} results")
    except Exception as e:
        print(f"[fetch_all] Web search failed: {e}")

    try:
        # 나라장터(조달청) 검색
        print(f"[fetch_all] Fetching from NaraJangter...")
        narajangter_results = fetch_narajangter(query, topk=NARAJANGTER_TOPK)
        all_results.extend(narajangter_results)
        print(f"[fetch_all] NaraJangter: {len(narajangter_results)} results")
    except Exception as e:
        print(f"[fetch_all] NaraJangter search failed: {e}")
    
    
    print(f"[fetch_all] Total results: {len(all_results)}")
    return all_results
    