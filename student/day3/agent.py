# -*- coding: utf-8 -*-
"""
Day3: 정부사업 공고 에이전트
- 역할: 사용자 질의를 받아 Day3 본체(impl/agent.py)의 Day3Agent.handle을 호출
- 결과를 writer로 표/요약 마크다운으로 렌더 → 파일 저장(envelope 포함) → LlmResponse 반환
- 이 파일은 의도적으로 '구현 없음' 상태입니다. TODO만 보고 직접 채우세요.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, List
import re

from google.genai import types
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

# Day3 본체
from student.day3.impl.agent import Day3Agent
# 공용 렌더/저장/스키마
from student.common.fs_utils import save_markdown
from student.common.writer import render_day3, render_enveloped
from student.common.schemas import Day3Plan
from student.day3.impl.pipeline import find_notices, build_proposal_draft

_LAST_SEARCH: Dict[str, Any] = {"query": None, "items": []}
DRAFT_KEYWORDS = ["초안", "제안서", "템플릿", "draft", "proposal", "WBS", "KPI"]

# ------------------------------------------------------------------------------
# TODO[DAY3-A-01] 모델 선택:
#  - 경량 LLM 식별자를 정해 MODEL에 넣으세요. (예: "openai/gpt-4o-mini")
#  - LiteLlm(model=...) 형태로 초기화합니다.
# ------------------------------------------------------------------------------
MODEL = LiteLlm(model="openai/gpt-4o-mini")  # <- LiteLlm(...)


# ------------------------------------------------------------------------------
# TODO[DAY3-A-02] _handle(query):
#  요구사항
#   1) Day3Plan 인스턴스를 만든다. (필요 시 소스별 topk / 웹 폴백 여부 등 지정)
#      - 예: Day3Plan(nipa_topk=3, bizinfo_topk=2, web_topk=2, use_web_fallback=True)
#   2) Day3Agent 인스턴스를 만든다. (외부 키는 본체에서 환경변수로 접근)
#   3) agent.handle(query, plan)을 호출해 payload(dict)를 반환한다.
#  반환 형태(예):
#   {"type":"gov_notices","query":"...", "items":[{title, url, deadline, agency, ...}, ...]}
# ------------------------------------------------------------------------------
def _handle(query: str) -> Dict[str, Any]:
    # 여기에 구현
    plan = Day3Plan(
        nipa_topk=3,
        bizinfo_topk=2,
        web_topk=2,
        use_web_fallback=True,
    )
    agent = Day3Agent()
    return agent.handle(query, plan)

# ------------------------------------------------------------------------------
# TODO[DAY3-A-03] before_model_callback:
#  요구사항
#   1) llm_request에서 사용자 최근 메시지를 찾아 query 텍스트를 꺼낸다.
#   2) _handle(query)로 payload를 만든다.
#   3) writer로 본문 MD를 만든다: render_day3(query, payload)
#   4) 파일 저장: save_markdown(query=query, route='day3', markdown=본문MD)
#   5) envelope로 감싸기: render_enveloped(kind='day3', query=query, payload=payload, saved_path=경로)
#   6) LlmResponse로 최종 마크다운을 반환한다.
#  예외 처리
#   - try/except로 감싸고, 실패 시 "Day3 에러: {e}" 형식의 짧은 메시지로 반환
# ------------------------------------------------------------------------------
def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
    **kwargs,
) -> Optional[LlmResponse]:
    # 여기에 구현
    try:
        if not llm_request.contents:
            raise ValueError("요청에 내용이 없습니다.")
        last = llm_request.contents[-1]
        if getattr(last, "role", None) != "user":
            raise ValueError("마지막 메시지가 user가 아닙니다.")
        if not getattr(last, "parts", None) or not getattr(last.parts[0], "text", None):
            raise ValueError("텍스트 파트를 찾을 수 없습니다.")
        query = last.parts[0].text.strip()

        payload = _handle(query)
        body_md = render_day3(query, payload)
        saved = save_markdown(query=query, route="day3", markdown=body_md)
        md = render_enveloped(kind="day3", query=query, payload=payload, saved_path=saved)

        return LlmResponse(content=types.Content(parts=[types.Part(text=md)], role="model"))
    except Exception as e:
        msg = f"Day3 에러: {e}"
        return LlmResponse(content=types.Content(parts=[types.Part(text=msg)], role="model"))


# ------------------------------------------------------------------------------
# TODO[DAY3-A-04] 에이전트 메타데이터:
#  - name/description/instruction 문구를 명확하게 다듬으세요.
#  - MODEL은 위 TODO[DAY3-A-01]에서 설정한 LiteLlm 인스턴스를 사용합니다.
# ------------------------------------------------------------------------------
day3_gov_agent = Agent(
    name="Day3GovAgent",                        # <- 필요 시 수정
    model=MODEL,                                # <- TODO[DAY3-A-01]에서 설정
    description="정부사업 공고/바우처 정보 수집 및 표 제공",   # <- 필요 시 수정
    instruction="질의를 기반으로 정부/공공 포털에서 관련 공고를 수집하고 표로 요약해라.",
    tools=[],
    before_model_callback=before_model_callback,
)

def _should_offer_draft(items: List[Dict[str, Any]]) -> bool:
    # 검색 결과가 있고, title/agency 같은 최소 필드가 보이면 제안하기
    if not items:
        return False
    top = items[0]
    return bool(top.get("title") and top.get("agency"))

def _detect_draft_reply(query: str) -> Optional[int]:
    """
    사용자가 직전에 제안한 '초안 만들까요?'에 '네/이걸로/2번' 등으로 답한 경우
    → 사용할 인덱스(int) 반환. 없으면 None.
    """
    q = (query or "").strip().lower()
    if re.fullmatch(r"(네|예|응|좋아요|좋아|이걸로|만들어줘|진행|확정)", q):
        return 0  # Top1로
    m = re.search(r"(\d+)\s*번", q)
    if m:
        idx = int(m.group(1)) - 1  # 사람 기준 1번→인덱스 0
        return max(0, idx)
    # '초안' 키워드가 있고 숫자는 없으면 Top1로
    if any(k.lower() in q for k in DRAFT_KEYWORDS):
        return 0
    return None

def _handle(query: str) -> Dict[str, Any]:
    # 1) 사용자가 방금 "네/2번" 등으로 답해온 경우 → 저장된 결과로 초안 생성
    pick_idx = _detect_draft_reply(query)
    if pick_idx is not None and _LAST_SEARCH["items"]:
        profile = {
            "skills": ["데이터분석", "AI모델링"],
            "staff": [{"name": "홍길동", "role": "PM", "availability": "80%", "skills": ["PM","요구분석"]}],
            "pastProjects": [{"name": "스마트병원 PoC", "year": "2024", "summary": "EMR 연계 분석"}],
        }
        return build_proposal_draft(profile=profile,
                                    notices=_LAST_SEARCH["items"],
                                    pick=pick_idx)

    # 2) 평소처럼 검색/추천 먼저 수행
    payload = find_notices(query)
    items = payload.get("items", [])

    # 3) 마지막 검색결과 보관 (다음 턴에 '네/2번' 등으로 이어지게)
    _LAST_SEARCH["query"] = query
    _LAST_SEARCH["items"] = items

    # 4) 결과가 괜찮으면 사용자에게 “초안 생성” 여부를 되묻는 메시지 동봉
    if _should_offer_draft(items):
        payload["meta"] = {
            "follow_up": (
                "Top1로 제안서 초안을 바로 만들어드릴까요? "
                "‘네’, ‘이걸로’, 또는 ‘2번으로 만들어줘’처럼 답해 주세요."
            ),
            "can_build_draft": True,
            "hint_examples": ["네", "이걸로", "2번으로 만들어줘", "초안 만들어줘"],
        }
    else:
        payload["meta"] = {
            "follow_up": "조건을 더 알려주시면(예산/기간/기관) 더 적합한 공고를 찾을게요.",
            "can_build_draft": False,
        }

    return payload