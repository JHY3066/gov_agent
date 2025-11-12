# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any
import re
from student.common.schemas import CompanyProfile, Budgets, Staff, PastProject

def _find_list(pattern: str, text: str) -> List[str]:
    m = re.search(pattern, text, re.I | re.S)
    if not m: return []
    body = m.group(1)
    items = re.split(r"[\n,;/]", body)
    return [re.sub(r"\s+", " ", x).strip("-• ").strip() for x in items if x.strip()]

def _find_one(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I | re.S)
    return m.group(1).strip() if m else ""

def _infer_budget(text: str) -> Budgets:
    # "총 예산 3억원", "CAPEX 1.2억, OPEX 0.8억" 등 단순 규칙
    def _num(s): 
        s = s.replace(",", "")
        m = re.search(r"([0-9]+(\.[0-9]+)?)", s)
        return float(m.group(1)) if m else None
    capex = _num(_find_one(r"CAPEX[^0-9]*([0-9\.,]+)", text))
    opex  = _num(_find_one(r"OPEX[^0-9]*([0-9\.,]+)", text))
    total = _num(_find_one(r"(?:총\s*예산|예산\s*한도)[^0-9]*([0-9\.,]+)", text))
    return Budgets(capex=capex, opex=opex, limit=total)

def _extract_staff(text: str) -> List[Staff]:
    staff = []
    # "성명/역할/투입률/보유역량" 표 형태 또는 줄 형태 감지
    for line in text.splitlines():
        # 예) "홍길동, PM, 80%, AI/데이터, 정보처리기사"
        cells = [c.strip() for c in re.split(r"[,\t|]", line) if c.strip()]
        if len(cells) >= 3 and re.search(r"%|\d\.\d", cells[2]):
            name, role, avail = cells[0], cells[1], cells[2]
            skills = []
            certs = []
            if len(cells) >= 4:
                skills = [s.strip() for s in re.split(r"[;/]", cells[3]) if s.strip()]
            if len(cells) >= 5:
                certs  = [s.strip() for s in re.split(r"[;/]", cells[4]) if s.strip()]
            staff.append(Staff(name=name, role=role, availability=avail, skills=skills, certs=certs))
    return staff

def _extract_past_projects(text: str) -> List[PastProject]:
    projects = []
    # 예) "프로젝트명(2023, 발주기관: OO시, 예산: 2.1억) - 스마트시티 데이터 허브 구축"
    pat = re.compile(r"([^\n\(]+)\((\d{4}).*?발주기관\s*:\s*([^,\)]+).{0,20}?예산\s*:\s*([0-9\.,]+)\s*억?\).*?-?\s*([^\n]+)")
    for m in pat.finditer(text):
        name = m.group(1).strip()
        year = m.group(2).strip()
        agency = m.group(3).strip()
        budget = float(m.group(4).replace(",", ""))
        summary = m.group(5).strip()
        projects.append(PastProject(name=name, year=year, agency=agency, budget=budget*1e8, summary=summary))
    return projects

def build_company_profile(parsed_docs: List[Dict[str, Any]], company_name: str = "") -> CompanyProfile:
    all_texts = "\n".join(d.get("text","") for d in parsed_docs if d.get("text"))
    # 장비/IP/보유기술/자격증 섹션 탐지(간단 키워드 기반)
    skills = _find_list(r"(?:보유기술|핵심역량)[:：]\s*(.+?)(?:\n\n|$)", all_texts)
    certs  = _find_list(r"(?:인증|자격증)[:：]\s*(.+?)(?:\n\n|$)", all_texts)
    eq_ip  = _find_list(r"(?:장비|특허|IP)[:：]\s*(.+?)(?:\n\n|$)", all_texts)
    budgets = _infer_budget(all_texts)
    staff = _extract_staff(all_texts)
    past  = _extract_past_projects(all_texts)
    avail_note = _find_one(r"(?:일정\s*가용성|투입\s*가능\s*기간)[:：]\s*(.+)", all_texts)

    return CompanyProfile(
        companyName=company_name or "",
        skills=skills,
        certifications=certs,
        equipments_or_ip=eq_ip,
        budgets=budgets,
        staff=staff,
        availabilityNote=avail_note,
        pastProjects=past
    )
