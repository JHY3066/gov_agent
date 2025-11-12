# mini_project/student/day1/smoke_test.py
# -*- coding: utf-8 -*-
"""
Day1 smoke test (agent.py는 그대로, 테스트만 유연하게)
실행(루트가 mini_project/ 인 상태에서):
  mini_project> python -m student.day1.smoke_test
"""

import uuid
from typing import Any

# google-adk 콜백 컨텍스트 (버전마다 생성자 요구가 달라서 호환 처리)
from google.adk.agents.callback_context import CallbackContext
try:
    # 있으면 공식 클래스를 사용
    from google.adk.agents.callback_context import InvocationContext, SessionContext
except Exception:
    InvocationContext = None
    SessionContext = None

# agent.py의 콜백/타입
from google.genai import types
from google.adk.models.llm_request import LlmRequest

# 우리가 테스트할 대상: agent.py의 before_model_callback
from student.day1.agent import before_model_callback


def _make_ctx() -> CallbackContext:
    """
    agent.py의 before_model_callback은 CallbackContext를 받지만
    내부에서 ctx를 쓰지는 않는다. 다만 라이브러리 측에서
    invocation_context.session.state 등에 접근할 수 있어
    속성 트리를 만족시키는 객체를 만들어 준다.
    """
    trace = str(uuid.uuid4())

    if InvocationContext is not None and SessionContext is not None:
        # 최신/일부 버전: 공식 컨텍스트 클래스로 구성
        sess = SessionContext(session_id="smoke_test_session", state={})
        ic = InvocationContext(
            user_id="smoke_test_user",
            session=sess,
            trace_id=trace,
        )
        return CallbackContext(invocation_context=ic)

    # 클래스를 제공하지 않는 버전: 더미 객체로 동일한 속성 트리 보장
    class _SessionCtx:
        def __init__(self, session_id: str):
            self.session_id = session_id
            self.state = {}

    class _InvocationCtx:
        def __init__(self, user_id: str, session: _SessionCtx, trace_id: str):
            self.user_id = user_id
            self.session = session
            self.trace_id = trace_id

    sess = _SessionCtx("smoke_test_session")
    ic = _InvocationCtx(user_id="smoke_test_user", session=sess, trace_id=trace)
    return CallbackContext(invocation_context=ic)


def _print_response(resp: Any) -> None:
    """
    agent.py의 before_model_callback은 LlmResponse를 반환한다.
    content.parts[0].text에 마크다운 결과가 들어오므로 안전하게 꺼내서 출력.
    """
    try:
        text = None
        if hasattr(resp, "output_text") and resp.output_text:
            text = resp.output_text
        elif getattr(resp, "content", None) and getattr(resp.content, "parts", None):
            parts = resp.content.parts
            if parts and getattr(parts[0], "text", None):
                text = parts[0].text
        print("\n✅ 결과:\n", text or "[빈 응답]", sep="")
    except Exception as e:
        print(f"⚠️ 응답 파싱 실패: {e}\n원시 응답: {resp!r}")


def main() -> None:
    print("🚀 Day1 Smoke Test 시작")

    # 1) 사용자가 보낸 메시지를 LlmRequest 형태로 구성
    query = "삼성전자 005930 최근 동향과 기업개요 요약"
    user_msg = types.Content(parts=[types.Part(text=query)], role="user")
    req = LlmRequest(contents=[user_msg])

    # 2) 콜백 컨텍스트 구성
    ctx = _make_ctx()

    # 3) agent.py의 before_model_callback 직접 호출 (모델 호출을 우회)
    #    - agent.py 내부에서 _handle(query) → Day1Agent.handle(...) → 렌더/세이브 → LlmResponse 생성
    try:
        resp = before_model_callback(ctx, req)
    except Exception as e:
        print(f"❌ 에이전트 실행 오류: {e}")
        raise

    # 4) 결과 출력
    _print_response(resp)
    print("\n--- 완료 ---")


if __name__ == "__main__":
    main()
