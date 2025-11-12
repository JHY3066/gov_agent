# -*- coding: utf-8 -*-
"""
Day3 파이프라인
- 기존: fetchers(NIPA/Bizinfo/Web) → normalize → rank
- 변경: PPS OpenAPI(선택) 결과도 함께 병합
  * .env USE_PPS=1 일 때 pps_fetch_bids(query) 실행
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional, Union
from pathlib import Path
import os

from .fetchers import fetch_all             # NIPA/Bizinfo/Web (Tavily)
from .normalize import normalize_all
from .rank import rank_items
from .proposal_generator import generate_proposal_chain

# 공용 스키마
from student.common.schemas import GovNotices, GovNoticeItem

# ▶ 추가: PPS OpenAPI
from student.day3.impl.pps_api import pps_fetch_bids


def _merge_and_dedup(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """URL+제목 기준 단순 중복 제거"""
    seen, out = set(), []
    for it in items or []:
        key = (it.get("title", "").strip(), it.get("url", "").strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def find_notices(query: str) -> dict:
    """
    1) Tavily 기반 수집(fetch_all)
    2) (옵션) PPS OpenAPI 수집(pps_fetch_bids) 추가 병합
    3) normalize → rank → GovNotices 스키마 반환
    """
    # 1) 기존 소스 수집
    raw_items = fetch_all(query)  # Day1형 스키마 리스트(title/url/snippet/...)
    
    # 2) PPS OpenAPI(선택)
    use_pps = os.getenv("USE_PPS", "1")  # 기본 1(ON)으로 두는 게 데모에 유리
    if use_pps and use_pps != "0":
        try:
            pps_items = pps_fetch_bids(query)   # 이미 GovNotice형에 가깝게 매핑됨
            # 정규화 파이프라인에 태우기 위해 Day1형처럼 최소 필드 구성
            # (normalize_all이 기대하는 최소 스키마를 맞추기 위해 변환)
            converted = []
            for it in pps_items:
                converted.append({
                    "title": it.get("title", ""),
                    "url": it.get("url", ""),
                    "source": "pps.data.go.kr",
                    "snippet": it.get("snippet", ""),
                    "date": it.get("announce_date", ""),
                })
            raw_items.extend(converted)
        except Exception:
            pass

    # 3) normalize → rank
    norm = normalize_all(raw_items)         # Day1형 → GovNotice 표준 스키마
    norm = _merge_and_dedup(norm)           # URL+제목 중복 제거
    ranked = rank_items(norm, query)        # 점수 부여/정렬

    model = GovNotices(
        query=query,
        items=[GovNoticeItem(**it) for it in ranked]
    )
    return model.model_dump()

def _pick_notice(items: List[Dict[str, Any]],
                 pick: Union[str, int] = "top1") -> Optional[Dict[str, Any]]:
    """
    items에서 초안 생성에 사용할 공고 1건을 선택.
    - pick == "top1": 0번(최상위) 선택
    - pick == int: 해당 인덱스
    - pick == str: uid 또는 url 일치 항목
    """
    if not items:
        return None

    if pick == "top1":
        return items[0]

    if isinstance(pick, int):
        return items[pick] if 0 <= pick < len(items) else None

    # 문자열이면 uid/url로 탐색
    for it in items:
        if pick and (pick == it.get("uid") or pick == it.get("url")):
            return it
    return None


def build_proposal_draft(
    profile: Dict[str, Any],
    query: Optional[str] = None,
    notices: Optional[List[Dict[str, Any]]] = None,
    pick: Union[str, int] = "top1",
    competitor: Optional[Dict[str, Any]] = None,
    model: str = "openai/gpt-4o",
) -> Dict[str, Any]:
    """
    - profile: DAY2에서 뽑은 CompanyProfile(dict)
    - query: (선택) 공고 검색 질의. notices가 없으면 이걸로 find_notices() 호출
    - notices: (선택) 이미 구해둔 공고 리스트(payload['items'])
    - pick: "top1" | 정수 인덱스 | uid/url 문자열
    - competitor: (선택) DAY1 경쟁사 스냅샷
    - model: LLM 모델명 (현재는 무시; 전역 MODEL 사용)

    return: {"type":"proposal_draft","query":..., "notice":{...}, "markdown":..., "review":..., "intermediates":{...}}
    """
    # 1) 공고 확보
    if notices is None:
        if not query:
            raise ValueError("build_proposal_draft: query 또는 notices 중 하나는 제공해야 합니다.")
        payload = find_notices(query)  # ← 기존 함수 재사용
        notices = payload.get("items", [])

    # 2) 공고 1건 선택
    notice = _pick_notice(notices, pick=pick)
    if not notice:
        return {
            "type": "proposal_draft",
            "query": query,
            "error": "선택할 공고가 없습니다.",
            "items_count": len(notices or []),
        }

    # 3) 제안서 초안 생성 (프롬프트 체인)
    #    generate_proposal_chain은 전역 MODEL을 사용하므로 model 인자를 넘기지 않음
    out = generate_proposal_chain(profile=profile, notice=notice, competitor=competitor)

    processed_dir = Path(__file__).resolve().parents[2] / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    draft_path = processed_dir / f"proposal_draft_{notice.get('id','draft')}.md"
    review_path = processed_dir / f"proposal_review_{notice.get('id','review')}.md"

    draft_md = out.get("draft_md", "")
    review_md = out.get("review_md", "")

    draft_path.write_text(draft_md, encoding="utf-8")
    review_path.write_text(review_md, encoding="utf-8")
    # 4) 페이로드
    return {
        "type": "proposal_draft",
        "query": query,
        "notice": notice,
        "markdown": out.get("draft_md", ""),
        "review": out.get("review_md", ""),
        "intermediates": out.get("intermediates", {}),
    }