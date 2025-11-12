# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, HttpUrl

# -------------------------
# Day1: Web Search / Finance Plan
# -------------------------
@dataclass
class Day1Plan:
    # 전부 기본값이 있으니 순서 자유. (비기본 필드 없음)
    do_web: bool = True
    do_stocks: bool = False
    web_keywords: List[str] = field(default_factory=list)
    tickers: List[str] = field(default_factory=list)
    output_style: str = "report"  # "report" | "summary"

# (선택) 웹 결과 아이템이 dataclass라면, "기본값 없는 필드 먼저" 규칙 엄수
@dataclass
class WebResultItem:
    url: str                       # <- 기본값 없음 (필수) 먼저!
    title: str = ""
    source: str = ""
    snippet: str = ""
    date: str = ""

# -------------------------
# Day2: RAG Plan
# -------------------------
@dataclass
class Day2Plan:
    # 전부 기본값이 있으니 OK
    index_dir: str = "indices/day2"
    top_k: int = 5
    min_score: float = 0.32
    min_mean_topk: float = 0.30
    force_rag_only: bool = False
    return_draft_when_enough: bool = True
    max_context: int = 1200
    embedding_model: str = "text-embedding-3-small"

# (선택) RAG Context 아이템도 dataclass를 쓸 경우 예시
@dataclass
class RagContextItem:
    doc_id: str                    # <- 기본값 없음
    score: float                   # <- 기본값 없음
    chunk: str = ""
    meta: dict = field(default_factory=dict)

@dataclass
class Staff:
    name: str
    role: str
    availability: str | float = "100%"     # "80%" 또는 0.8 등 허용
    skills: List[str] = field(default_factory=list)
    certs: List[str] = field(default_factory=list)

@dataclass
class PastProject:
    name: str
    year: str | int
    agency: str = ""
    budget: Optional[float] = None  # KRW
    summary: str = ""
    tags: List[str] = field(default_factory=list)

@dataclass
class Budgets:
    capex: Optional[float] = None
    opex: Optional[float] = None
    limit: Optional[float] = None   # 총 예산 한도(선택)

@dataclass
class CompanyProfile:
    companyName: str = ""
    skills: List[str] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    equipments_or_ip: List[str] = field(default_factory=list)  # 장비/특허/IP
    budgets: Budgets = field(default_factory=Budgets)
    staff: List[Staff] = field(default_factory=list)
    availabilityNote: str = ""      # 일정 가용성 메모
    pastProjects: List[PastProject] = field(default_factory=list)

# DAY2 결과 페이로드(웹/주가 등과 동일한 패턴 유지)
@dataclass
class Day2Payload:
    type: str      # "internal_profile"
    sources: List[Dict[str, Any]]
    profile: CompanyProfile
    notes: List[str]
    errors: List[str]

# -------------------------
# Day3: Gov Notices Plan
# -------------------------
@dataclass
class Day3Plan:
    # 전부 기본값이 있으니 OK
    nipa_topk: int = 3
    bizinfo_topk: int = 2
    web_topk: int = 2
    use_web_fallback: bool = True

# (선택) Day3 결과 아이템을 dataclass로 쓰고 싶다면
@dataclass
class GovNoticeItem:
    url: str                       # <- 기본값 없음
    title: str = ""
    source: str = ""               # "nipa" | "bizinfo" | "web"
    agency: str = ""
    announce_date: str = ""
    close_date: str = ""
    budget: str = ""
    snippet: str = ""
    attachments: List[str] = field(default_factory=list)
    content_type: str = "notice"
    score: float = 0.0

class GovNoticeItemModel(BaseModel):
    url: HttpUrl
    title: str = ""
    source: Literal["nipa","bizinfo","web",""] = ""
    agency: str = ""
    announce_date: Optional[str] = ""
    close_date: Optional[str] = ""
    budget: str = ""
    snippet: str = ""
    attachments: List[HttpUrl] = []
    content_type: Literal["notice","guide","faq","other"] = "notice"
    score: float = 0.0

class GovNoticesModel(BaseModel):
    type: Literal["gov_notices"] = "gov_notices"
    query: str
    items: List[GovNoticeItemModel] = []
    
    
GovNoticeItem = GovNoticeItemModel
GovNotices = GovNoticesModel