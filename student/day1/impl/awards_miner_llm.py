# -*- coding: utf-8 -*-
"""
awards_miner_llm.py
- LLM으로 '낙찰업체/우선협상대상자/계약상대자' 등 수상자(winner) 정보를 추출
- LLM이 실패하거나 빈 결과일 때, 정규식 + 스코어링 폴백으로 보조 추출
- 입력: pages: [{"url":..., "title":..., "text":...}, ...], query: str
- 출력 스키마:
{
  "query": str,
  "winners": [{"name": str, "count": int}],       # legacy view (top5)
  "signals": {
     "topWinners": [{"name":..., "wins":..., "avgAmount":...}],
     "topReasons": [{"reason":..., "freq":...}],
     "agencies":   [{"name":..., "freq":...}],
  },
  "evidences": [{"url":..., "title":..., "snippet":...}],
  "score": {"tech": null, "price": null, "total": null}
}
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple, Callable
from collections import Counter, defaultdict
import json
import os
import re
import time

try:
    from google.adk.models.lite_llm import LiteLlm
except Exception:  # 런타임 방어
    LiteLlm = None

__all__ = ["build_awards_snapshot_llm"]

# ─────────────────────────────────────────────────────────────────────────────
# 환경/디버그
# ─────────────────────────────────────────────────────────────────────────────
DEBUG = os.getenv("DAY1_DEBUG", "0") == "1"

def _dprint(*args):
    if DEBUG:
        print("[AWARDS-LLM]", *args)

# ─────────────────────────────────────────────────────────────────────────────
# 전처리/후처리 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _clean_html_ws(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\u200b", "").replace("\u200c", "").replace("\uFEFF", "")
    s = s.replace("&nbsp;", " ").replace("\u00A0", " ")
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s

def _truncate(s: str, n: int = 260) -> str:
    s = " ".join((_clean_html_ws(s) or "").split())
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."

def _json_loose_load(s: str) -> Dict[str, Any]:
    """
    LLM이 코드펜스/접두/접미/주석을 섞어도 JSON 객체만 최대한 뽑아 파싱.
    - trailing comma, 따옴표 문제를 일부 보정.
    """
    if not isinstance(s, str):
        return {}
    text = s.strip()

    # 코드펜스 제거
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()

    # JSON 객체만 추출
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    text = m.group(0)

    # 흔한 오류 보정: trailing comma
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    try:
        return json.loads(text)
    except Exception:
        return {}

# ─────────────────────────────────────────────────────────────────────────────
# 회사명 정규화/필터
# ─────────────────────────────────────────────────────────────────────────────

# “이유/가이드/문장조각” 류 제거를 위한 금지토큰
BAN_TOKENS = [
    # 설명/메타 라벨
    "결정기준", "결정방식", "유의사항", "제안요청서", "RFP", "제안서",
    "내용이", "상세", "계획서", "시험운영", "평가기준", "가점", "감점",
    "배점", "평가표", "제출서류", "입찰공고", "제안요청", "공고", "발주",
    "과업", "범위", "목적",
    # 자주 잡히던 잡음 패턴 방지
    "가 제안한", "에대해결과", "에서 제외함", "통보", "필요시", "해야 하며",
]

# 회사 힌트 토큰
COMPANY_HINTS = [
    "주식회사", "㈜", "(주)", "(유)", "유한", "재단", "협동조합", "컨소시엄",
    "엔지니어링", "시스템", "정보", "테크", "솔루션", "컨설팅",
    "개발", "산업", "전자", "통신", "소프트", "데이터",
    "대학교 산학협력단", "산학협력단", "협회", "연구원", "연구소", "코리아",
    "INC", "LTD", "Co.", "Corp", "Company", "Limited",
]

KOR_COMPANY_PAT = r"(?:주식회사\s*)?[㈜(주)(유)]?\s*[가-힣A-Za-z0-9&.,\-·() ]{2,60}"
COMPANY_CLEAN_PAT = re.compile(r"\s*(?:주식회사|㈜|\(주\)|\(유\))\s*", re.UNICODE)

def _has_company_hint(name: str) -> bool:
    return any(h in name for h in COMPANY_HINTS)

def _norm_company(name: str) -> Optional[str]:
    if not name:
        return None
    n = _clean_html_ws(name)
    n = re.sub(r"\s+", " ", n).strip()
    n = COMPANY_CLEAN_PAT.sub("", n).strip()
    n = n.strip(" ,.;:·-()[]|")
    if not n or len(n) < 2:
        return None

    # 금지 토큰 포함 시 제외
    if any(k in n for k in BAN_TOKENS):
        return None

    # 한글/영문이 하나도 없으면 제외
    if not re.search(r"[가-힣A-Za-z]", n):
        return None

    # 공백 없는 긴 토큰(문장 조각 가능성) 제외 — 단, 회사 힌트가 있으면 허용
    if " " not in n and len(n) >= 16 and not _has_company_hint(n):
        return None

    # 특수문자 비율이 과도하면 제외
    letters = sum(1 for ch in n if ch.isalpha() or ch.isdigit())
    if letters / max(1, len(n)) < 0.6:
        return None

    # 조사만/한 글자짜리 등 제외
    if re.fullmatch(r"[가-힣]{1,2}", n):
        return None

    return n

def _is_number_like(x: str) -> bool:
    if not isinstance(x, str):
        return False
    if re.search(r"\d", x):
        return True
    return any(u in x for u in ["원", "만원", "억원", "천만원", "백만원", "KRW", "₩"])

# ─────────────────────────────────────────────────────────────────────────────
# LLM 호출부: 다양한 SDK 호환 + 재시도
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_INSTR = (
    "역할: 당신은 한국어 공공입찰 결과 문서를 정리하는 어시스턴트입니다. "
    "항상 사실만 기반으로, 지정된 JSON 스키마로만 응답하세요. "
    "문서에 명시되지 않은 정보를 생성하지 마세요."
)

USER_TPL = """아래 본문은 입찰 결과/낙찰 공고와 관련된 텍스트입니다.
이 텍스트에서 '낙찰업체(또는 우선협상대상자/계약상대자)', '발주기관(가능시)', '낙찰금액(가능시)', 그리고 '낙찰 사유/근거(문구형태)'를 찾아 JSON으로만 출력하세요.

반드시 아래 스키마로만 출력:
{{
  "winners": [{{"name": "회사명", "amount": "숫자(원 단위 또는 기재된 단위 그대로)"}}],
  "agency": "발주기관 이름 또는 빈 문자열",
  "reasons": ["키워드 또는 짧은 근거 문구"...]
}}

지켜야 할 규칙:
- 문서에 없는 정보는 생성하지 말고 빈 값으로 남겨두세요.
- 'winners'는 실제 회사명만 넣습니다(설명/문장 조각 금지).
- 표/선정 결과/공고의 '낙찰자·우선협상대상자·계약상대자'를 우선 반영합니다.
- 금액은 원문 단위를 보존합니다(숫자 포함 시).

[제목]
{title}

[URL]
{url}

[본문 (일부 청크)]
{body}
"""

def _get_llm() -> Optional[LiteLlm]:
    model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    if LiteLlm is None:
        return None
    try:
        # LiteLlm은 대부분 __call__ 지원. (invoke 미지원 환경 존재)
        return LiteLlm(model=model)
    except Exception:
        return None

def _extract_text_from_resp(resp: Any) -> str:
    """여러 SDK 응답 포맷을 최대한 호환적으로 텍스트로 변환."""
    # 1) 문자열
    if isinstance(resp, str):
        return resp

    # 2) pydantic-like content/parts
    try:
        content = getattr(resp, "content", None)
        if isinstance(content, str):
            return content
        parts = getattr(content, "parts", None)
        if isinstance(parts, (list, tuple)) and parts:
            first = parts[0]
            txt = getattr(first, "text", None)
            if isinstance(txt, str) and txt.strip():
                return txt
            return str(first)
    except Exception:
        pass

    # 3) text 속성
    try:
        txt = getattr(resp, "text", None)
        if isinstance(txt, str):
            return txt
    except Exception:
        pass

    # 4) OpenAI-like
    try:
        choices = getattr(resp, "choices", None)
        if isinstance(choices, list) and choices:
            choice = choices[0]
            msg = getattr(choice, "message", None)
            if msg is not None:
                mc = getattr(msg, "content", None)
                if isinstance(mc, str):
                    return mc
            t = getattr(choice, "text", None)
            if isinstance(t, str):
                return t
    except Exception:
        pass

    # 5) dict
    if isinstance(resp, dict):
        if "content" in resp and isinstance(resp["content"], str):
            return resp["content"]
        if "text" in resp and isinstance(resp["text"], str):
            return resp["text"]
        ch = resp.get("choices")
        if isinstance(ch, list) and ch:
            c0 = ch[0]
            if isinstance(c0, dict):
                if "message" in c0 and isinstance(c0["message"], dict):
                    mc = c0["message"].get("content")
                    if isinstance(mc, str):
                        return mc
                if "text" in c0 and isinstance(c0["text"], str):
                    return c0["text"]

    # 6) 마지막 수단
    try:
        return str(resp)
    except Exception:
        return ""

def _llm_send_with_retry(llm: Any, prompt: str, retries: int = 2, sleep_sec: float = 0.6) -> str:
    """
    invoke / __call__ / chat / generate / complete 순서로 시도 후 텍스트 추출.
    재시도 간단 지원(일부 429/일시적 오류 방어 목적).
    """
    last_err = None
    for attempt in range(retries + 1):
        try:
            # 1) invoke
            if hasattr(llm, "invoke"):
                try:
                    resp = llm.invoke(prompt)  # 일부 SDK는 invoke(message)
                    txt = _extract_text_from_resp(resp)
                    if txt.strip():
                        return txt
                except Exception as e:
                    last_err = e

            # 2) __call__
            if callable(llm):
                try:
                    resp = llm(prompt)
                    txt = _extract_text_from_resp(resp)
                    if txt.strip():
                        return txt
                except Exception as e:
                    last_err = e

            # 3) chat
            if hasattr(llm, "chat"):
                try:
                    resp = llm.chat(prompt)
                    txt = _extract_text_from_resp(resp)
                    if txt.strip():
                        return txt
                except Exception as e:
                    last_err = e

            # 4) generate / complete with kwargs
            for meth in ("generate", "complete"):
                if hasattr(llm, meth):
                    try:
                        fn: Callable = getattr(llm, meth)
                        resp = fn(prompt=prompt)
                        txt = _extract_text_from_resp(resp)
                        if txt.strip():
                            return txt
                    except Exception as e:
                        last_err = e

        except Exception as e:
            last_err = e

        if attempt < retries:
            time.sleep(sleep_sec)

    if DEBUG and last_err:
        _dprint("LLM send failed:", type(last_err).__name__, last_err)
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# 폴백(정규식) + 스코어링 추출기
# ─────────────────────────────────────────────────────────────────────────────

WINNER_KEYS = ["낙찰자", "낙찰 업체", "낙찰업체", "우선협상대상자", "계약상대자", "선정 업체", "선정업체", "우선협상 대상자"]
AGENCY_KEYS = ["발주기관", "수요기관", "구매기관", "발주 부서", "계약기관", "계약부서", "발주처", "수요처"]
REASON_KEYS = ["사유", "근거", "평가", "정성", "정량", "우수", "기술", "가격", "낙찰", "선정"]

COMPANY_REGEX_A = re.compile(
    rf"(?:{'|'.join(WINNER_KEYS)})\s*[:：\-–]?\s*({KOR_COMPANY_PAT})",
    re.IGNORECASE
)
COMPANY_REGEX_B = re.compile(
    rf"(?:업체명|사업자|제안사|업체)\s*[:：\-–]?\s*({KOR_COMPANY_PAT})",
    re.IGNORECASE
)
COMPANY_NEAR_WINNER = re.compile(
    rf"({'|'.join(WINNER_KEYS)})[\s\S]{{0,40}}({KOR_COMPANY_PAT})|({KOR_COMPANY_PAT})[\s\S]{{0,40}}({'|'.join(WINNER_KEYS)})",
    re.IGNORECASE
)

AMOUNT_REGEX = re.compile(r"(?:낙찰금액|계약금액|추정가격|투찰금액)\s*[:：\-–]?\s*([0-9][0-9,.\s]*\s*(?:원|억원|천만원|백만원|KRW|₩)?)")
AGENCY_REGEX = re.compile(rf"(?:{'|'.join(AGENCY_KEYS)})\s*[:：\-–]?\s*([가-힣A-Za-z0-9&.,\-·() ]{{2,60}})", re.IGNORECASE)

def _company_score(raw_name: str, ctx: str, key_span: Tuple[int, int]) -> int:
    """
    후보 회사명에 대한 간단 점수:
    +2: 힌트 토큰 포함
    +1: key_span(낙찰자 키워드)와 40자 이내 근접
    +1: 공백 포함 또는 (주/㈜)/(유) 접두
    -2: 공백 없고 길이>=16 (연결문장 가능성)
    """
    score = 0
    n = raw_name or ""
    n_norm = _norm_company(n) or ""
    if not n_norm:
        return -999  # 이미 탈락

    if _has_company_hint(n) or _has_company_hint(n_norm):
        score += 2
    if " " in n_norm or n.startswith("(주)") or n.startswith("㈜") or n_norm.startswith("(주)") or n_norm.startswith("㈜") or n.startswith("(유)") or n_norm.startswith("(유)"):
        score += 1
    if " " not in n_norm and len(n_norm) >= 16 and not _has_company_hint(n_norm):
        score -= 2

    # 근접도
    start, end = key_span
    start = max(0, start - 40)
    end = min(len(ctx), end + 40)
    window = ctx[start:end]
    if n in window or n_norm in window:
        score += 1

    return score

def _fallback_extract(text: str) -> Tuple[List[Dict[str, Any]], List[str], Optional[str]]:
    """본문에서 낙찰업체/금액/기관/사유 키워드를 정규식 + 스코어링으로 보조 추출."""
    text = _clean_html_ws(text)
    if not text:
        return [], [], None
    winners_raw: List[Dict[str, Any]] = []
    reasons: List[str] = []
    agency: Optional[str] = None

    # 회사/금액 추출(+스코어)
    for rx in (COMPANY_REGEX_A, COMPANY_REGEX_B, COMPANY_NEAR_WINNER):
        for m in rx.finditer(text):
            cand = None
            for g in m.groups():
                if g:
                    cand = g
                    break
            if not cand:
                continue
            score = _company_score(cand, text, m.span())
            if score < 2:  # 임계치: 2 미만은 노이즈로 본다
                continue
            nm = _norm_company(cand)
            if nm:
                winners_raw.append({"name": nm, "amount": None, "_score": score, "_pos": m.span()})

    # 금액 매칭(가까운 후보로 보수적 매핑)
    for m in AMOUNT_REGEX.finditer(text):
        amt = (m.group(1) or "").strip()
        if winners_raw and _is_number_like(amt):
            pos = m.span()[0]
            winners_sorted = sorted(winners_raw, key=lambda w: abs(pos - w["_pos"][0]))
            for w in winners_sorted[:3]:
                if w.get("amount") in (None, ""):
                    w["amount"] = amt
                    break

    # 기관
    am = AGENCY_REGEX.search(text)
    if am:
        ag = _norm_company(am.group(1))
        if ag:
            agency = ag

    # 사유 문장 후보
    for sent in re.split(r"[\n\.]", text):
        s = sent.strip()
        if not s:
            continue
        if any(k in s for k in REASON_KEYS):
            s = _truncate(s, 100)
            if s and s not in reasons:
                reasons.append(s)

    # 후보 정리(스코어 순) + 중복 제거
    winners_raw.sort(key=lambda w: (-w.get("_score", 0), w.get("name", "")))
    uniq = {}
    dedup_winners: List[Dict[str, Any]] = []
    for w in winners_raw:
        nm = w.get("name")
        if nm and nm not in uniq:
            uniq[nm] = True
            dedup_winners.append({"name": nm, "amount": w.get("amount")})

    return dedup_winners[:10], reasons[:10], agency

# ─────────────────────────────────────────────────────────────────────────────
# LLM 호출 + 폴백 융합 추출
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_text(body: str, max_len: int = 8000) -> List[str]:
    """길어진 본문을 청크로 분할(문단 단위)."""
    body = _clean_html_ws(body or "")
    if len(body) <= max_len:
        return [body]
    paras = re.split(r"\n{2,}", body)
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= max_len:
            cur += (("\n\n" if cur else "") + p)
        else:
            if cur:
                chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)
    return chunks

def _call_llm(llm, title: str, url: str, body: str) -> Dict[str, Any]:
    """본문을 여러 청크로 나눠 LLM을 여러 번 호출하고 병합."""
    chunks = _chunk_text(body, max_len=9000)
    winners_all: List[Dict[str, Any]] = []
    reasons_all: List[str] = []
    agency_votes = Counter()

    for idx, ch in enumerate(chunks):
        prompt = f"{SYSTEM_INSTR}\n\n" + USER_TPL.format(title=title or "", url=url or "", body=ch or "")
        out = _llm_send_with_retry(llm, prompt, retries=2, sleep_sec=0.5)
        data = _json_loose_load(out)
        if DEBUG:
            _dprint(f"chunk {idx+1}/{len(chunks)} raw:", _truncate(out, 180))

        winners = data.get("winners") or []
        reasons = data.get("reasons") or []
        agency = data.get("agency") or ""

        # 정제
        for w in winners:
            if isinstance(w, dict):
                nm = _norm_company(w.get("name", ""))
                amt = w.get("amount")
                if nm:
                    winners_all.append({"name": nm, "amount": amt})
        for r in reasons:
            if isinstance(r, str):
                rs = r.strip()
                if rs:
                    reasons_all.append(_truncate(rs, 100))
        if agency:
            ag = _norm_company(agency)
            if ag:
                agency_votes[ag] += 1

    # ★ LLM이 이유/기관만 주고 승자는 비워 둔 경우에도 폴백 수행
    if not winners_all:
        fb_wins, fb_reasons, fb_agency = _fallback_extract(body)
        winners_all.extend(fb_wins)
        if not reasons_all and fb_reasons:
            reasons_all.extend(fb_reasons)
        if not agency_votes and fb_agency:
            agency_votes[fb_agency] += 1
        _dprint("fallback after LLM (winners):", len(fb_wins))

    agency = agency_votes.most_common(1)[0][0] if agency_votes else ""

    # dedup winners
    uniq = {}
    winners_clean = []
    for w in winners_all:
        nm = w.get("name")
        if nm and nm not in uniq:
            uniq[nm] = True
            winners_clean.append(w)

    return {"winners": winners_clean, "reasons": reasons_all, "agency": agency}

def build_awards_snapshot_llm(pages: List[Dict[str, str]], query: str) -> Dict[str, Any]:
    """
    LLM + 정규식+스코어 폴백을 사용한 낙찰/개찰 스냅샷 생성.
    """
    llm = _get_llm()
    if llm is None:
        return {
            "query": query,
            "winners": [],
            "signals": {"topWinners": [], "topReasons": [], "agencies": []},
            "evidences": [],
            "score": {"tech": None, "price": None, "total": None},
            "note": "LLM unavailable",
        }

    # 1) 페이지별 호출
    all_winners: List[Dict[str, Any]] = []
    all_reasons: List[str] = []
    agency_counts = Counter()
    evidences: List[Dict[str, str]] = []

    for p in pages or []:
        url = (p.get("url") or "").strip()
        title = (p.get("title") or "").strip()
        text = _clean_html_ws(p.get("text") or "")
        if not text:
            continue

        data = _call_llm(llm, title, url, text)
        winners = data.get("winners") or []
        reasons = data.get("reasons") or []
        agency = data.get("agency") or ""

        if winners:
            all_winners.extend(winners)
        if reasons:
            all_reasons.extend(reasons)
        if agency:
            agency_counts[agency] += 1

        evidences.append({
            "url": url,
            "title": title,
            "snippet": _truncate(text, 240),
        })

    # 2) 집계
    win_counter = Counter()
    amount_bag = defaultdict(list)
    for w in all_winners:
        nm = w.get("name")
        amt = w.get("amount")
        if nm:
            win_counter[nm] += 1
            if isinstance(amt, (int, float)):
                amount_bag[nm].append(float(amt))
            elif isinstance(amt, str):
                # "1,234만원" 등에서 숫자만 추출(rough)
                m = re.sub(r"[^\d.]", "", amt)
                try:
                    if m:
                        amount_bag[nm].append(float(m))
                except Exception:
                    pass

    # ★ 페이지 전부 돌렸는데도 여전히 0 → 모든 본문을 합쳐 최종 폴백 1회(스코어 적용)
    if not win_counter:
        all_text_concat = "\n\n".join([_clean_html_ws(p.get("text") or "") for p in pages or []])
        fb_wins, fb_reasons, fb_agency = _fallback_extract(all_text_concat)
        for w in fb_wins:
            nm = w.get("name")
            if nm:
                win_counter[nm] += 1
        if not all_reasons and fb_reasons:
            all_reasons.extend(fb_reasons)
        if fb_agency:
            agency_counts[fb_agency] += 1
        _dprint("final global fallback winners:", len(fb_wins))

    top_winners = []
    for nm, wins in win_counter.most_common(8):
        amts = amount_bag.get(nm) or []
        avg_amt = (sum(amts) / len(amts)) if amts else None
        top_winners.append({"name": nm, "wins": wins, "avgAmount": avg_amt})

    reason_counts = Counter([r.strip() for r in all_reasons if r and r.strip()])
    top_reasons = [{"reason": k, "freq": v} for k, v in reason_counts.most_common(8)]
    top_agencies = [{"name": k, "freq": v} for k, v in agency_counts.most_common(6)]

    legacy_winners = [{"name": nm, "count": c} for nm, c in win_counter.most_common(5)]

    _dprint("final winners:", len(legacy_winners), "evidences:", len(evidences))

    return {
        "query": query,
        "winners": legacy_winners,
        "signals": {
            "topWinners": top_winners,
            "topReasons": top_reasons,
            "agencies": top_agencies,
        },
        "evidences": evidences[:20],
        "score": {"tech": None, "price": None, "total": None},
    }
