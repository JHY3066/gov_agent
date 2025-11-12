# -*- coding: utf-8 -*-
from __future__ import annotations
from student.common.schemas import CompanyProfile, Staff, PastProject, Budgets

def make_dummy_company_profile() -> CompanyProfile:
    return CompanyProfile(
        companyName="AIVLE Demo Co.",
        skills=["데이터파이프라인", "LLM-RAG", "GIS", "클라우드배포"],
        certifications=["GS인증 1등급", "ISO27001"],
        equipments_or_ip=["GPU 서버 2식", "데이터 수집 프레임워크 특허 제10-1234567"],
        budgets=Budgets(capex=150_000_000, opex=80_000_000, limit=300_000_000),
        staff=[
            Staff(name="홍길동", role="PM", availability="80%", skills=["프로젝트관리","조달"], certs=["PMP"]),
            Staff(name="김데브", role="ML Eng", availability="100%", skills=["LLM","벡터DB"], certs=["정보처리기사"]),
            Staff(name="이데브", role="FE", availability="60%", skills=["React","GIS"], certs=[]),
        ],
        availabilityNote="11~12월 집중 투입 가능",
        pastProjects=[
            PastProject(name="스마트시티 데이터허브 고도화", year="2024", agency="OO시청", budget=210_000_000, summary="데이터 허브 및 대시보드 고도화"),
            PastProject(name="관광빅데이터 분석 시스템", year="2023", agency="한국관광공사", budget=180_000_000, summary="수요 예측 및 KPI 설계"),
        ]
    )
