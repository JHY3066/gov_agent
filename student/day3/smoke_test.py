# -*- coding: utf-8 -*-
"""
Day3 스모크 테스트 (Day1 스모크 스타일)
- 루트 .env 로드 → 유연 임포트 → 라이브 웹 수집 → 정규화/랭킹 결과 최소 검증
실행:
  export TAVILY_API_KEY="실제키"
  python smoke_day3.py
"""

# 0) 루트 탐색 + sys.path 보정 + .env 로드
import os, sys, json
from pathlib import Path

def _find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists() or (p / ".git").exists() or (p / "apps").exists():
            return p
    return start

ROOT = _find_root(Path(__file__).resolve())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# .env 로드 (python-dotenv 있으면 사용, 없으면 수동 로드)
ENV_PATH = ROOT / ".env"
def _manual_load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

try:
    from dotenv import load_dotenv, find_dotenv
    # 루트 .env가 최우선
    if ENV_PATH.exists():
        load_dotenv(str(ENV_PATH), override=True)
    else:
        load_dotenv(find_dotenv(usecwd=True), override=True)
except Exception:
    _manual_load_env(ENV_PATH)

# 1) 키 확인
if not os.getenv("TAVILY_API_KEY"):
    print("[SKIP] TAVILY_API_KEY가 없습니다. .env를 확인하거나 환경변수로 설정하세요.")
    sys.exit(0)

# 2) 유연 임포트 (student.* 우선, 실패 시 로컬 모듈 폴백)
import importlib

def _try_import(mod, fallback=None):
    try:
        return importlib.import_module(mod)
    except Exception:
        if fallback:
            return importlib.import_module(fallback)
        raise

try:
    agent_mod = _try_import("student.day3.impl.agent", "agent")
    schemas_mod = _try_import("student.common.schemas")
    Day3Agent = getattr(agent_mod, "Day3Agent")
    Day3Plan = getattr(schemas_mod, "Day3Plan")
except Exception:
    # 최소 폴백 (동일 폴더에 agent.py가 있고, Day3Plan이 없을 때)
    agent_mod = _try_import("agent")
    Day3Agent = getattr(agent_mod, "Day3Agent")
    class Day3Plan:
        def __init__(self, **kw): self.__dict__.update(kw)

# 3) 실행 파라미터
QUERY = "AI 바우처"            # 샘플 쿼리 (원하면 바꾸세요)
PLAN = Day3Plan(
    nipa_topk=2,               # NIPA 상위 2개
    bizinfo_topk=2,            # Bizinfo 상위 2개
    web_topk=1,                # 웹 보조 1개
    use_web_fallback=True,     # 정부 포털이 비어도 웹로 보조
)

# 4) 실행
agent = Day3Agent()
try:
    payload = agent.handle(QUERY, PLAN)
except NotImplementedError as e:
    print(f"[XFAIL] Day3가 아직 미구현: {e}")
    sys.exit(0)
except Exception as e:
    print(f"[FAIL] Day3Agent.handle 에러: {e}")
    sys.exit(1)

# 5) 최소 검증/출력 (Day1 스모크와 동일한 톤)
if not isinstance(payload, dict):
    print("[FAIL] payload가 dict가 아닙니다.")
    sys.exit(1)

items = payload.get("items") or []
if not isinstance(items, list):
    print("[FAIL] payload['items']가 리스트가 아닙니다.")
    sys.exit(1)

if len(items) == 0:
    print("[WARN] 공고 결과가 비어 있습니다. (쿼리/시점에 따라 정상일 수 있음)")
else:
    print(f"[OK] 공고 {len(items)}건 수집. 상위 3개:")
    for i, it in enumerate(items[:3], 1):
        title = (it.get("title") or "").strip() or "(제목없음)"
        url = it.get("url") or ""
        deadline = it.get("deadline") or it.get("due_date") or ""
        print(f"  {i}. {title} | {deadline} | {url}")
    print("\n[샘플 JSON] 첫 항목:")
    print(json.dumps(items[0], ensure_ascii=False, indent=2)[:800])

print("\n[DONE] Day3 스모크 종료")
sys.exit(0)
