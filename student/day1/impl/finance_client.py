# -*- coding: utf-8 -*-
"""
yfinance 가격 조회
- 목표: 티커 리스트에 대해 현재가/통화를 가져와 표준 형태로 반환
"""

from typing import List, Dict, Any
import re

# (강의 안내) yfinance는 외부 네트워크 환경에서 동작. 인터넷 불가 환경에선 모킹이 필요할 수 있음.


def _normalize_symbol(s: str) -> str:
    """
    6자리 숫자면 한국거래소(.KS) 보정.
    예:
      '005930' → '005930.KS'
      'AAPL'   → 'AAPL' (그대로)
    """
    # ----------------------------------------------------------------------------
    # TODO[DAY1-F-01] 구현 지침
    #  - if re.fullmatch(r"\d{6}", s): return f"{s}.KS"
    #  - else: return s
    # ----------------------------------------------------------------------------
    if re.fullmatch(r"\d{6}", s):          # 정확히 6자리 숫자(한국 종목 코드)인 경우에.
      return f"{s}.KS"                      # yfinance 호환을 위해 거래소 접미사 ".KS"를 붙인다! (Ex. 005930 -> 005930.KS)
    else:
      return s                              # 이미 접미사가 있거나(005930.KS), 영문 티커(AAPL 등)면 변경 없이 그냥 그대로 반환하기


def get_quotes(symbols: List[str], timeout: int = 20) -> List[Dict[str, Any]]:
    """
    yfinance로 심볼별 시세를 조회해 리스트로 반환합니다.
    반환 예:
      [{"symbol":"AAPL","price":123.45,"currency":"USD"},
       {"symbol":"005930.KS","price":...,"currency":"KRW"}]
    실패시 해당 심볼은 {"symbol":sym, "error":"..."} 형태로 표기.
    """
    # ----------------------------------------------------------------------------
    # TODO[DAY1-F-02] 구현 지침
    #  1) from yfinance import Ticker 임포트(파일 상단 대신 함수 내부 임포트도 OK)
    #  2) 결과 리스트 out=[]
    #  3) 입력 심볼들을 _normalize_symbol로 보정
    #  4) 각 심볼에 대해:
    #       - t = Ticker(sym)
    #       - 가격: getattr(t.fast_info, "last_price", None) 또는 t.fast_info.get("last_price")
    #       - 통화: getattr(t.fast_info, "currency", None)
    #       - 둘 다 숫자/문자 정상 추출 시 out.append({...})
    #       - 예외/누락 시 out.append({"symbol": sym, "error": "설명"})
    #  5) return out
    # ----------------------------------------------------------------------------
    try:
        from yfinance import Ticker  # 1) 내부 임포트 허용
    except ImportError:
        print("Error: 'yfinance' library not found. Please install it using 'pip install yfinance'")
        return [{"symbol": sym, "error": "yfinance library not installed"} for sym in symbols]

    import math

    # 2) 결과 리스트
    out: List[Dict[str, Any]] = []

    # 3) 심볼 정규화
    normalized_symbols = [_normalize_symbol(sym) for sym in symbols]

    # 4) 각 심볼 처리
    for sym in normalized_symbols:
        try:
            t = Ticker(sym)

            # fast_info는 dict-유사 객체일 수 있어 양쪽 접근 모두 지원
            fi = getattr(t, "fast_info", {}) or {}
            
            # last_price가 None일 경우를 대비해 regularMarketPrice, previousClose 순으로 fallback
            last_price = None
            if hasattr(fi, "get"):
                last_price = fi.get("last_price") or fi.get("regularMarketPrice") or fi.get("previousClose")
            else:
                last_price = getattr(fi, "last_price", None) or \
                             getattr(fi, "regularMarketPrice", None) or \
                             getattr(fi, "previousClose", None)

            currency   = fi.get("currency")   if hasattr(fi, "get") else getattr(fi, "currency", None)

            # 가격 검증: 숫자 변환 가능 + 유한값
            try:
                price_value = float(last_price) if last_price is not None else None
            except (TypeError, ValueError):
                price_value = None

            currency_ok = isinstance(currency, str) and len(currency.strip()) > 0
            price_ok = (price_value is not None) and math.isfinite(price_value)

            if price_ok and currency_ok:
                out.append({
                    "symbol": sym,
                    "price": float(price_value),
                    "currency": currency.strip(),
                })
            else:
                reasons = []
                if not price_ok:
                    reasons.append(f"invalid price (raw: {last_price})")
                if not currency_ok:
                    reasons.append(f"invalid currency (raw: {currency})")
                
                # yfinance가 티커를 찾지 못했을 때의 일반적인 응답 확인
                if not price_ok and not currency_ok and (fi.get('regularMarketPrice') is None and fi.get('previousClose') is None):
                     out.append({
                        "symbol": sym,
                        "error": "Ticker not found or no data available",
                    })
                else:
                    out.append({
                        "symbol": sym,
                        "error": ", ".join(reasons) if reasons else "unknown error",
                    })

        except Exception as e:
            # yfinance 네트워크/응답 오류 등 일반 예외 처리
            out.append({
                "symbol": sym,
                "error": f"{type(e).__name__}: {e}",
            })

    # 5) 결과 반환
    return out