# -*- coding: utf-8 -*-
"""
Day3Agent: 정부사업 공고 에이전트(Agent-as-a-Tool)
- 입력: query(str), plan(Day3Plan)
- 동작: fetch → normalize → rank
- 출력: {"type":"gov_notices","query": "...","items":[...]}  # items는 정규화된 공고 리스트
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional

import os
from student.common.schemas import Day3Plan

# 수집 → 정규화 → 랭크 모듈
from . import fetchers          # NIPA, Bizinfo, 일반 Web 수집
from .normalize import normalize_all   # raw → 공통 스키마 변환
from .rank import rank_items           # 쿼리 관련도/마감 임박/신뢰도 등 정렬

# ------------------------------------------------------------------------------
# TODO[DAY3-I-01]: _set_source_topk
#  - plan의 nipa_topk/bizinfo_topk/web_topk 값을 정수화하여 1 이상으로 보정
#  - fetchers의 NIPA_TOPK/BIZINFO_TOPK/WEB_TOPK 상수에 반영
#  - 보정된 plan을 반환
# 설계·시퀀스 문서 준수.  (sequence/pipeline)  :contentReference[oaicite:6]{index=6} :contentReference[oaicite:7]{index=7}
# ------------------------------------------------------------------------------
def _coerce_positive_int(val: Optional[int], default: int) -> int:
    try:
        v = int(val) if val is not None else int(default)
    except Exception:
        v = int(default)
    if v < 1:
        v = 1
    return v

def _set_source_topk(plan: Day3Plan) -> Day3Plan:
    plan.nipa_topk    = _coerce_positive_int(getattr(plan, "nipa_topk", None),    getattr(fetchers, "NIPA_TOPK", 3))
    plan.bizinfo_topk = _coerce_positive_int(getattr(plan, "bizinfo_topk", None), getattr(fetchers, "BIZINFO_TOPK", 2))
    plan.web_topk     = _coerce_positive_int(getattr(plan, "web_topk", None),     getattr(fetchers, "WEB_TOPK", 2))

    # fetchers 상수에 동기화
    fetchers.NIPA_TOPK    = plan.nipa_topk
    fetchers.BIZINFO_TOPK = plan.bizinfo_topk
    fetchers.WEB_TOPK     = plan.web_topk
    return plan


class Day3Agent:
    # ------------------------------------------------------------------------------
    # TODO[DAY3-I-02]: __init__에서 환경변수 로딩/보관
    #  - 예) TAVILY_API_KEY (없어도 동작은 하나 결과가 빈 배열일 수 있음)
    #  - impl/fetchers는 os.getenv로도 읽지만, 여기서도 보관해 두면 디버깅이 편함
    # ------------------------------------------------------------------------------
    def __init__(self) -> None:
        self.tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
        # 추가 확장 키가 있다면 여기에 보관
        # self.openai_api_key = os.getenv("OPENAI_API_KEY", "")

    # ------------------------------------------------------------------------------
    # TODO[DAY3-I-03]: handle 파이프라인
    #  1) _set_source_topk(plan)
    #  2) fetch 단계: fetchers.fetch_nipa/bizinfo/(옵션)web → raw 리스트 누적
    #  3) normalize_all(raw)
    #  4) rank_items(norm, query)
    #  5) {"type":"gov_notices","query":query,"items":ranked} 반환
    #  예외 발생 시 최소한 빈 결과라도 리턴(스모크/운영안정성)  :contentReference[oaicite:8]{index=8}
    # ------------------------------------------------------------------------------
    def handle(self, query: str, plan: Day3Plan = Day3Plan()) -> Dict[str, Any]:
        # 1) plan 동기화
        plan = _set_source_topk(plan)

        raw: List[Dict[str, Any]] = []
        # 2) fetch 단계 (각 fetch는 설계 가이드에 따라 도메인 제한/키워드 보강 수행)  :contentReference[oaicite:9]{index=9}
        try:
            raw += fetchers.fetch_nipa(query, topk=plan.nipa_topk)
        except Exception:
            # 소스 하나 실패해도 전체 파이프라인은 계속 진행
            pass

        try:
            raw += fetchers.fetch_bizinfo(query, topk=plan.bizinfo_topk)
        except Exception:
            pass

        if getattr(plan, "use_web_fallback", False) and plan.web_topk > 0:
            try:
                raw += fetchers.fetch_web(query, topk=plan.web_topk)
            except Exception:
                pass

        # 3) normalize 단계: 서로 다른 원천 스키마를 공통 구조로  :contentReference[oaicite:10]{index=10}
        try:
            norm = normalize_all(raw)
        except Exception:
            norm = []

        # 4) rank/정렬 단계: 질의 적합도/마감 임박/신뢰도 등  :contentReference[oaicite:11]{index=11}
        try:
            ranked = rank_items(norm, query)
        except Exception:
            ranked = norm  # 최소한 노멀라이즈 결과라도 반환

        # 5) 페이로드 구성 (상위 day3/agent.py가 기대하는 형태)  :contentReference[oaicite:12]{index=12}
        payload: Dict[str, Any] = {
            "type": "gov_notices",
            "query": query,
            "items": ranked,
        }
        return payload
