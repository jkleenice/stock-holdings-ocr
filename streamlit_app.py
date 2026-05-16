from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="Holdings OCR", layout="wide", page_icon="📊")

# iOS "Add to Home Screen" PWA hints. Streamlit injects these into the body but
# iOS Safari still respects apple-* meta tags wherever they appear.
st.markdown(
    """
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <meta name="apple-mobile-web-app-title" content="Holdings">
    <meta name="theme-color" content="#4C78A8">
    """,
    unsafe_allow_html=True,
)


def _require_password() -> None:
    """Gate the app behind APP_PASSWORD if it is set in secrets. No-op if missing."""
    try:
        configured = st.secrets.get("APP_PASSWORD")
    except Exception:
        configured = None
    if not configured:
        return
    if st.session_state.get("_authed"):
        return

    st.title("🔒 비밀번호")
    pw = st.text_input("암호를 입력하세요", type="password", label_visibility="collapsed")
    if pw:
        if pw == configured:
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    st.stop()


_require_password()


# 사이드바에서 기능 선택
FEATURES = {
    "📊 Holdings OCR": "holdings",
    "😱 공포지수 (Crypto)": "fear_greed",
    "📈 VIX 비교": "vix",
}

with st.sidebar:
    st.subheader("기능 선택")
    selected_label = st.radio(
        "기능",
        options=list(FEATURES.keys()),
        label_visibility="collapsed",
    )
    st.divider()


feature_id = FEATURES[selected_label]

# 지연 import — 선택한 뷰만 로드 (plotly 등 무거운 의존성 lazy load)
if feature_id == "holdings":
    from views import holdings

    holdings.render()
elif feature_id == "fear_greed":
    from views import fear_greed

    fear_greed.render()
elif feature_id == "vix":
    from views import vix

    vix.render()
