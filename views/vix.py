from __future__ import annotations

import streamlit as st


def render() -> None:
    st.title("📈 VIX 비교")
    st.info(
        "🚧 준비 중인 기능입니다. "
        "VIX(미국 변동성지수)와 다른 지수의 추이를 비교 시각화할 예정입니다."
    )
    st.markdown(
        """
        ### 계획된 기능
        - VIX 30/60/90일 추이
        - S&P 500과의 역상관 시각화
        - Crypto Fear & Greed Index와 동시 비교
        - 임계값(예: VIX > 30) 알림
        """
    )
