# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ✅ Direct OpenAI SDK (independent from ADK/LiteLlm)
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
MODEL_NAME = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 4096

# project-root/student/day3/impl/…/proposal_prompt.md
DAY3_ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = DAY3_ROOT / "prompts" / "proposal_prompt.md"

# Client (reads OPENAI_API_KEY from env)
_client_singleton: Optional[OpenAI] = None
def _client() -> OpenAI:
    global _client_singleton
    if _client_singleton is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client_singleton = OpenAI(api_key=api_key)
    return _client_singleton

# ─────────────────────────────────────────────────────────────────────────────
# Utils
# ─────────────────────────────────────────────────────────────────────────────
def _dumps(obj: Any) -> str:
    """Pydantic HttpUrl, datetime 등 비직렬화 타입을 안전하게 문자열화."""
    return json.dumps(obj, ensure_ascii=False, default=str)

def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def _split_sections(md: str) -> Dict[str, str]:
    """
    '# 시스템 역할', '# 단계 1.' ~ '# 단계 5.' 헤더로 구간 분리
    반환 키: system, step1, step2, step3, step4, step5
    """
    out: Dict[str, str] = {"system": ""}
    # 시스템 역할
    sys_m = re.search(r"(?s)^#\s*시스템 역할\s*(.+?)(?=^#\s*단계\s*1\.|\Z)", md, flags=re.MULTILINE)
    if sys_m:
        out["system"] = sys_m.group(1).strip()

    # 단계들
    for n, body in re.findall(r"(?s)^#\s*단계\s*(\d+)\.\s*(.+?)(?=^#\s*단계\s*\d+\.|\Z)", md, flags=re.MULTILINE):
        out[f"step{n}"] = body.strip()

    # 누락 방지
    for k in ("step1","step2","step3","step4","step5"):
        out.setdefault(k, "")
    return out

def _ensure_json(s: str) -> Dict[str, Any]:
    """모델이 코드펜스를 붙여도 안전하게 파싱."""
    if not isinstance(s, str):
        return {}
    cand = s.strip()
    # 코드펜스 제거
    cand = re.sub(r"^```(?:json)?\s*|\s*```$", "", cand, flags=re.MULTILINE).strip()
    # 후행 텍스트 잘리는 경우 대비: 첫 JSON 오브젝트만 추출 시도
    m = re.search(r"\{.*\}", cand, flags=re.DOTALL)
    if m:
        cand = m.group(0)
    try:
        return json.loads(cand)
    except Exception:
        return {}

def _to_md_list(items: Optional[List[Any]]) -> str:
    if not items:
        return "- 자료 없음"
    # 리스트 요소를 문자열로 변환
    norm = []
    for x in items:
        if isinstance(x, dict) and "리스크" in x:
            norm.append(str(x.get("리스크", "")).strip())
        else:
            norm.append(str(x).strip())
    norm = [v for v in norm if v]
    return "\n".join(f"- {v}" for v in norm) if norm else "- 자료 없음"

def _render_team_table(staff: List[Dict[str, Any]]) -> str:
    if not staff:
        return "- 자료 없음"
    rows = [
        "| 역할 | 성명 | 투입률 | 보유역량 |",
        "|---|---|---:|---|",
    ]
    for m in staff:
        rows.append(
            f"| {m.get('role','')} | {m.get('name','')} | {m.get('availability','')} | {', '.join(m.get('skills',[]))} |"
        )
    return "\n".join(rows)

# ─────────────────────────────────────────────────────────────────────────────
# OpenAI call with simple retry
# ─────────────────────────────────────────────────────────────────────────────
def _call_llm(prompt: str, *, temperature: float = DEFAULT_TEMPERATURE, max_tokens: int = DEFAULT_MAX_TOKENS,
              retries: int = 2, backoff: float = 1.5) -> str:
    """
    OpenAI Chat Completions API 호출. 간단한 재시도 포함.
    """
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = _client().chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            txt = (resp.choices[0].message.content or "").strip()
            return txt
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff ** attempt)
            else:
                raise
    # 논리상 도달 불가
    raise last_err or RuntimeError("Unknown LLM error")

# ─────────────────────────────────────────────────────────────────────────────
# Main chain
# ─────────────────────────────────────────────────────────────────────────────
def generate_proposal_chain(
    profile: Dict[str, Any],
    notice: Dict[str, Any],
    competitor: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,   # 호환성 인자(무시). 외부에서 넘겨도 에러 안 나게.
) -> Dict[str, Any]:
    """
    단일 프롬프트(proposal_prompt.md)를 단계별 호출:
      - requirements(JSON)
      - match(JSON)
      - strategy(JSON)
      - draft(Markdown)
      - review(Markdown)
    """
    # 입력 정규화
    notice = json.loads(_dumps(notice))
    profile = json.loads(_dumps(profile))
    competitor = json.loads(_dumps(competitor or {}))

    # 0) 프롬프트 로드 & 분리
    prompt_all = _read_text(PROMPT_FILE)
    parts = _split_sections(prompt_all)

    system = parts["system"]
    step1 = parts["step1"]
    step2 = parts["step2"]
    step3 = parts["step3"]
    step4 = parts["step4"]
    step5 = parts["step5"]

    # ── 1) 요구사항 분석(JSON)
    p1 = f"{system}\n\n{step1}\n\n[CallForProposal]\n{_dumps(notice)}"
    j1_raw = _call_llm(p1)
    requirements = _ensure_json(j1_raw)

    # ── 2) 역량 매칭/리스크(JSON)
    p2 = (
        f"{system}\n\n{step2}\n\n"
        f"[CompanyProfile]\n{_dumps(profile)}\n\n"
        f"[단계1 결과]\n{_dumps(requirements)}"
    )
    j2_raw = _call_llm(p2)
    match = _ensure_json(j2_raw)

    # ── 3) 차별화/KPI(JSON)
    p3 = (
        f"{system}\n\n{step3}\n\n"
        f"[단계2 결과]\n{_dumps(match)}\n\n"
        f"[CompetitorSnapshot]\n{_dumps(competitor)}"
    )
    j3_raw = _call_llm(p3)
    strategy = _ensure_json(j3_raw)

    # ── 4) 제안서 초안(Markdown)
    helper_vars = {
        "agency": notice.get("agency", ""),
        "purpose": requirements.get("목적", ""),
        "budget": notice.get("budget", "") or requirements.get("예산범위", ""),
        "duration": notice.get("duration", "") or requirements.get("사업기간", ""),
        "requirements": _to_md_list(requirements.get("주요요구사항")),
        "wbs": "- 초기분석 → 상세설계 → 구축/시험 → 이행/교육 → 검수",
        "risks": _to_md_list(match.get("리스크및보완")),
        "team_table": _render_team_table(profile.get("staff", [])),
        "kpis": _to_md_list(strategy.get("핵심KPI")),
        "differentiators": _to_md_list(strategy.get("차별화포인트")),
        "summary_statement": "우리 조직의 역량과 일정/예산 충족 조건에서 수행 가능성이 높습니다.",
    }

    p4_ctx = (
        f"{system}\n\n{step4}\n\n"
        f"[요약 변수]\n{_dumps(helper_vars)}\n\n"
        f"[CompanyProfile]\n{_dumps(profile)}\n\n"
        f"[CallForProposal]\n{_dumps(notice)}\n\n"
        f"[단계1]\n{_dumps(requirements)}\n\n"
        f"[단계2]\n{_dumps(match)}\n\n"
        f"[단계3]\n{_dumps(strategy)}"
    )
    draft_md = _call_llm(p4_ctx).strip()

    # ── 5) 체크리스트 리뷰(Markdown)
    p5 = f"{system}\n\n{step5}\n\n[Draft]\n{draft_md}"
    review_md = _call_llm(p5).strip()

    return {
        "draft_md": draft_md,
        "review_md": review_md,
        "intermediates": {
            "requirements": requirements,
            "match": match,
            "strategy": strategy,
        },
    }
