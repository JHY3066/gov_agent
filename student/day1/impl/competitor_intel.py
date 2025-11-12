#파일 안되시는 분들을 위한 코드

# -*- coding: utf-8 -*-
"""
competitor_intel.py
- Tavily로 수집한 웹 페이지 본문에서 낙찰/개찰 관련 신호를 추출하여
  간단한 경쟁사 인텔 요약을 생성합니다.
- 외부 의존성: 없음 (표준 라이브러리만 사용)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import re
from collections import defaultdict
from datetime import datetime


@dataclass
class Award:
    noticeId: str
    title: str
    agency: str
    winner: str
    amount: Optional[float]
    openDate: Optional[str]
    topicTags: List[str]
    region: Optional[str]
    url: str


@dataclass
class CompetitorIntel:
    topCompetitors: List[Dict[str, Any]]
    marketLandscape: Dict[str, Any]
    evidences: List[Dict[str, str]]  # {url, snippet}


# ------------------------- 정규식 패턴 -------------------------

WINNER_PAT = re.compile(r"(낙찰자|낙찰업체|낙찰\s*사)\s*[:：]\s*([\w\-\(\)&·㈜\s]+)")
AMOUNT_PAT = re.compile(r"(낙찰금액|계약금액|금액)\s*[:：]\s*([0-9,]+)\s*(원|KRW)?")
DATE_PAT = re.compile(r"(개찰일|계약일|발표일)\s*[:：]\s*([0-9]{4}[./-][0-9]{1,2}[./-][0-9]{1,2})")
TITLE_WINNER_PAT = re.compile(r"낙찰\s*(?:자|업체|사)\s*[:：]?\s*([\w\-\(\)&·㈜\s]{2,})")


# ------------------------- 헬퍼 함수 -------------------------

def _norm_amount(s: str) -> Optional[float]:
    try:
        s = s.replace(",", "").strip()
        return float(s)
    except Exception:
        return None


def _guess_agency_from_text(text: str) -> str:
    """간단 휴리스틱: 본문 초반부에서 기관명 힌트 라인 캡처"""
    for line in text.splitlines()[:80]:
        if any(k in line for k in ["조달청", "공단", "청", "원", "부", "시", "기관"]):
            return line.strip()[:60]
    return ""


def _extract_award_fields(title: str, text: str) -> Tuple[str, Optional[float], Optional[str]]:
    # winner
    m = WINNER_PAT.search(text) or TITLE_WINNER_PAT.search(title)
    if m:
        winner = (m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)).strip()
    else:
        winner = ""

    # amount
    am = AMOUNT_PAT.search(text)
    amount = _norm_amount(am.group(2)) if am else None

    # date
    dm = DATE_PAT.search(text)
    open_date: Optional[str] = None
    if dm:
        raw = dm.group(2).replace(".", "-").replace("/", "-")
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
            open_date = dt.strftime("%Y-%m-%d")
        except Exception:
            open_date = raw  # 원문 유지

    return winner, amount, open_date


def _tags_from_title(title: str) -> List[str]:
    """제목에서 간단한 토픽 태그 후보 추출"""
    base = re.sub(r"\[[^\]]+\]", " ", title)
    toks = re.split(r"[\s/·:,]+", base)
    toks = [t for t in toks if len(t) >= 2 and not t.isdigit()]
    return list(dict.fromkeys(toks))[:8]


def _canon(name: str) -> str:
    """회사명 가벼운 정규화(㈜/주식회사/공백)"""
    n = name or ""
    n = n.replace("㈜", "").replace("주식회사", "").strip()
    n = re.sub(r"\s+", " ", n)
    return n


# ------------------------- 메인 빌더 -------------------------

def build_competitor_intel_from_pages(
    pages: List[Dict[str, str]],  # 각 원소: {"url":..., "title":..., "text":...}
    query: str,
) -> CompetitorIntel:
    awards: List[Award] = []
    evidences: List[Dict[str, str]] = []

    for p in pages:
        url, title, text = p.get("url", ""), p.get("title", ""), p.get("text", "")
        if not text:
            continue

        # 낙찰/개찰/입찰 결과 분위기만 선택
        if not any(k in (title + text) for k in ["낙찰", "개찰", "입찰 결과", "낙찰자", "협상대상자", "계약 체결"]):
            continue

        winner, amount, open_date = _extract_award_fields(title, text)
        agency = _guess_agency_from_text(text)

        awards.append(
            Award(
                noticeId=title[:50],
                title=title.strip(),
                agency=agency,
                winner=_canon(winner),
                amount=amount,
                openDate=open_date,
                topicTags=_tags_from_title(title),
                region=None,
                url=url,
            )
        )

        # 증거 스니펫 저장(짧게)
        snippet = " ".join(text.split())[:260]
        evidences.append({"url": url, "snippet": snippet})

    # 집계: 날짜가 없어도 포함
    by_comp: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"wins": 0, "amounts": []})
    for a in awards:
        by_comp[a.winner]["wins"] += 1
        if a.amount:
            by_comp[a.winner]["amounts"].append(a.amount)

    ranked: List[Dict[str, Any]] = []
    for name, agg in by_comp.items():
        if not name:
            continue
        wins = agg["wins"]
        avg_amount = (sum(agg["amounts"]) / len(agg["amounts"])) if agg["amounts"] else None
        ranked.append({"name": name.strip(), "wins": wins, "avgAmount": avg_amount})
    ranked.sort(key=lambda x: (-x["wins"], -(x["avgAmount"] or 0)))

    # 시장경쟁강도(단순): 키워드 빈도
    cci_signal = 0
    total_text = " ".join(p.get("text", "") for p in pages)
    for k in ["입찰", "경쟁", "제안서", "기술평가"]:
        cci_signal += total_text.count(k)
    cci = min(1.0, cci_signal / 40.0)  # 0~1 스케일 임의 정규화

    intel = CompetitorIntel(
        topCompetitors=ranked[:5],
        marketLandscape={"cci": cci, "query": query},
        evidences=evidences[:10],
    )
    return intel
