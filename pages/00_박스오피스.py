"""
어제의 박스오피스 분석 대시보드
- KOBIS(영화진흥위원회) 오픈API 사용
- 오늘 데이터는 아직 집계 전이므로 '어제(한국시간 기준)' 데이터를 보여준다.
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 파이썬 내장 시간대 라이브러리 (별도 설치 불필요)
import plotly.express as px

# ------------------------------------------------------------------
# 1. 기본 페이지 설정
# ------------------------------------------------------------------
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")
st.title("🎬 어제의 박스오피스 대시보드")

# ------------------------------------------------------------------
# 2. 인증키 불러오기 (절대 코드에 직접 쓰지 않음!)
#    Streamlit Cloud의 Settings > Secrets 에
#    KOBIS_KEY = "발급받은키" 형태로 등록해두어야 합니다.
# ------------------------------------------------------------------
try:
    KOBIS_KEY = st.secrets["KOBIS_KEY"]
except KeyError:
    st.error(
        "🔑 KOBIS_KEY가 설정되어 있지 않아요.\n\n"
        "Streamlit Cloud라면 'Manage app' → 'Settings' → 'Secrets'에서\n"
        'KOBIS_KEY = "발급받은_API_키" 를 추가해주세요.'
    )
    st.stop()  # 키가 없으면 여기서 앱 실행을 멈춘다.

# ------------------------------------------------------------------
# 3. '어제' 날짜를 한국 시간(Asia/Seoul) 기준으로 계산
#    - 서버 시계가 외국 기준일 수 있으므로 반드시 시간대를 명시한다.
# ------------------------------------------------------------------
kst_now = datetime.now(ZoneInfo("Asia/Seoul"))
yesterday_kst = kst_now - timedelta(days=1)
target_dt = yesterday_kst.strftime("%Y%m%d")  # yyyymmdd 형식 (예: 20260721)

# 화면에 보여줄 사람이 읽기 좋은 날짜 형식
target_dt_display = yesterday_kst.strftime("%Y년 %m월 %d일")

st.caption(f"📅 조회 기준일(한국시간): {target_dt_display}  ·  당일 데이터는 아직 집계 전이라 어제 데이터를 보여줍니다.")

# ------------------------------------------------------------------
# 4. KOBIS API 호출
# ------------------------------------------------------------------
API_URL = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

params = {
    "key": KOBIS_KEY,
    "targetDt": target_dt,
}

try:
    response = requests.get(API_URL, params=params, timeout=10)
    response.raise_for_status()  # 200번대가 아니면 예외 발생
    data = response.json()
except requests.exceptions.RequestException as e:
    st.error(
        "🚫 박스오피스 데이터를 불러오는 중 문제가 발생했어요.\n\n"
        "인터넷 연결이나 KOBIS 서버 상태를 확인한 뒤 새로고침 해주세요.\n\n"
        f"(자세한 오류: {e})"
    )
    st.stop()
except ValueError:
    st.error("🚫 서버 응답을 해석할 수 없어요. 잠시 후 다시 시도해주세요.")
    st.stop()

# ------------------------------------------------------------------
# 5. 에러 응답(faultInfo) 확인
#    KOBIS는 키가 잘못되었거나 요청이 잘못되면 boxOfficeResult 대신
#    faultInfo 라는 필드로 에러 내용을 돌려준다.
# ------------------------------------------------------------------
if "faultInfo" in data:
    message = data["faultInfo"].get("message", "알 수 없는 오류")
    st.error(
        "🚫 KOBIS API에서 오류를 응답했어요.\n\n"
        f"오류 내용: {message}\n\n"
        "인증키(KOBIS_KEY)가 올바른지, 혹은 하루 요청 한도를 넘기지 않았는지 확인해주세요."
    )
    st.stop()

# 정상 응답이라면 boxOfficeResult 안에 리스트가 들어있다.
box_office_result = data.get("boxOfficeResult", {})
movie_list = box_office_result.get("dailyBoxOfficeList", [])

if not movie_list:
    st.warning("😥 해당 날짜의 박스오피스 데이터가 없어요.")
    st.stop()

# ------------------------------------------------------------------
# 6. DataFrame으로 변환 + 문자열 숫자를 실제 숫자로 변환
#    (정렬/그래프에 쓰려면 반드시 숫자 타입이어야 한다)
# ------------------------------------------------------------------
df = pd.DataFrame(movie_list)

numeric_cols = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt", "rankInten"]
for col in numeric_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

# 순위 기준으로 정렬 (혹시 순서가 섞여 있을 경우 대비)
df = df.sort_values("rank").reset_index(drop=True)

# ------------------------------------------------------------------
# 7. 전날 대비 순위 변동 화살표 만들기
#    rankInten 이 양수면 순위 상승(빨간 위 화살표),
#    음수면 순위 하락(파란 아래 화살표), 0이면 변동 없음
# ------------------------------------------------------------------
def make_rank_change_text(inten: float) -> str:
    if pd.isna(inten):
        return "-"
    if inten > 0:
        return f"🔺{int(inten)}"   # 순위 상승
    elif inten < 0:
        return f"🔻{int(abs(inten))}"  # 순위 하락
    else:
        return "➖"  # 변동 없음

df["순위변동"] = df["rankInten"].apply(make_rank_change_text)

# ------------------------------------------------------------------
# 8. 누적관객 100만 돌파 영화에 트로피 이모지 붙이기
# ------------------------------------------------------------------
def make_movie_name(row) -> str:
    name = row["movieNm"]
    if row["audiAcc"] >= 1_000_000:
        return f"{name} 🏆"
    return name

df["영화명"] = df.apply(make_movie_name, axis=1)

# ------------------------------------------------------------------
# 9. 1위 영화 지표 카드
# ------------------------------------------------------------------
top_movie = df.iloc[0]

st.subheader("🥇 어제의 1위 영화")

col1, col2, col3 = st.columns(3)
col1.metric(
    label=top_movie["영화명"],
    value=f"{int(top_movie['audiCnt']):,}명",
    delta=f"전날 대비 순위 {int(top_movie['rankInten'])}" if not pd.isna(top_movie["rankInten"]) else None,
)
col2.metric(label="누적 관객수", value=f"{int(top_movie['audiAcc']):,}명")
col3.metric(label="스크린 수", value=f"{int(top_movie['scrnCnt']):,}개")

st.divider()

# ------------------------------------------------------------------
# 10. 관객수 상위 5편 막대그래프
# ------------------------------------------------------------------
st.subheader("📊 관객수 상위 5편")

top5 = df.nlargest(5, "audiCnt")

fig = px.bar(
    top5,
    x="movieNm",
    y="audiCnt",
    text="audiCnt",
    labels={"movieNm": "영화명", "audiCnt": "일일 관객수"},
    color="audiCnt",
    color_continuous_scale="Reds",
)
fig.update_traces(texttemplate="%{text:,}명", textposition="outside")
fig.update_layout(showlegend=False, coloraxis_showscale=False)

st.plotly_chart(fig, use_container_width=True)

st.divider()

# ------------------------------------------------------------------
# 11. 전체 박스오피스 표
# ------------------------------------------------------------------
st.subheader("📋 전체 박스오피스 순위")

display_df = df[
    ["rank", "순위변동", "영화명", "openDt", "audiCnt", "audiAcc", "scrnCnt"]
].rename(
    columns={
        "rank": "순위",
        "openDt": "개봉일",
        "audiCnt": "관객수",
        "audiAcc": "누적관객",
        "scrnCnt": "스크린수",
    }
)

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "관객수": st.column_config.NumberColumn(format="%d명"),
        "누적관객": st.column_config.NumberColumn(format="%d명"),
        "스크린수": st.column_config.NumberColumn(format="%d개"),
    },
)

st.caption("데이터 출처: 영화진흥위원회(KOBIS) 일별 박스오피스 오픈API")
