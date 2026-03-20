import os
import json
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
import folium
from folium.features import GeoJson, GeoJsonTooltip, GeoJsonPopup
from streamlit_folium import st_folium

# =========================================================
# 기본 설정
# =========================================================
st.set_page_config(
    page_title="대한민국 맛집 지도",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🍽 대한민국 맛집 지도")
st.caption("실제 행정구역 경계 + 실제 일반음식점 공공데이터 기반 지도")

# =========================================================
# 경로 / URL
# =========================================================
DATA_DIR = "data"
GEO_DIR = os.path.join(DATA_DIR, "geo")
REST_DIR = os.path.join(DATA_DIR, "restaurants")

SIDO_GEO_PATH = os.path.join(GEO_DIR, "sido.geojson")
SIGUNGU_GEO_PATH = os.path.join(GEO_DIR, "sigungu.geojson")
EMD_GEO_PATH = os.path.join(GEO_DIR, "emd.geojson")

RESTAURANT_PARQUET_PATH = os.path.join(REST_DIR, "restaurants_merged.parquet")
RESTAURANT_CSV_PATH = os.path.join(REST_DIR, "restaurants_merged.csv")

SIDO_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-provinces-geo.json"
SIGUNGU_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-municipalities-geo.json"
EMD_URL = "https://raw.githubusercontent.com/vuski/admdongkor/master/ver20220101/HangJeongDong_ver20220101.geojson"

KOREA_CENTER = [36.35, 127.95]
DEFAULT_ZOOM = 7

MAX_MARKERS_SIDO = 80
MAX_MARKERS_SIGUNGU = 180
MAX_MARKERS_EMD = 300

FOOD_TYPES = [
    "전체",
    "한식",
    "중식",
    "일식",
    "양식",
    "분식",
    "카페",
    "카페/디저트",
    "치킨",
    "피자",
    "고기",
    "구이",
    "국밥",
    "탕",
    "찌개",
    "면요리",
    "해산물",
    "술집",
    "이자카야",
    "패스트푸드",
    "기타",
]

# =========================================================
# 유틸
# =========================================================
def normalize_str(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def get_first_existing(props: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        if key in props and props[key] not in (None, ""):
            return str(props[key]).strip()
    return ""


def get_feature_name(props: Dict[str, Any]) -> str:
    return get_first_existing(props, [
        "name", "NAME_1", "NAME_2", "NAME_3",
        "CTP_KOR_NM", "SIG_KOR_NM", "EMD_KOR_NM",
        "adm_nm", "sidonm", "sggnm", "emd_nm"
    ]) or "이름없음"


def get_feature_code(props: Dict[str, Any]) -> str:
    return get_first_existing(props, [
        "adm_cd", "adm_cd2", "adm_cd5", "adm_cd8",
        "CTPRVN_CD", "SIG_CD", "EMD_CD", "code"
    ])


def collect_points(coords, result):
    if isinstance(coords, list):
        if len(coords) == 2 and all(isinstance(v, (int, float)) for v in coords):
            result.append(coords)
        else:
            for item in coords:
                collect_points(item, result)


def get_feature_centroid(feature: Dict[str, Any]) -> Tuple[float, float]:
    geometry = feature.get("geometry", {})
    coords = geometry.get("coordinates", [])
    points = []
    collect_points(coords, points)

    if not points:
        return KOREA_CENTER[0], KOREA_CENTER[1]

    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lon


def contains_name(props: Dict[str, Any], keyword: str) -> bool:
    if not keyword:
        return True
    text = json.dumps(props, ensure_ascii=False)
    return keyword in text


def try_get_clicked_name(map_data: Dict[str, Any]) -> Optional[str]:
    if not map_data:
        return None

    last_active = map_data.get("last_active_drawing")
    if isinstance(last_active, dict):
        props = last_active.get("properties", {})
        if props:
            return get_feature_name(props)

    last_clicked = map_data.get("last_object_clicked")
    if isinstance(last_clicked, dict):
        props = last_clicked.get("properties", {})
        if props:
            return get_feature_name(props)

    tooltip = map_data.get("last_object_clicked_tooltip")
    if tooltip:
        return str(tooltip).strip()

    popup = map_data.get("last_object_clicked_popup")
    if popup:
        return str(popup).strip()

    return None


def download_file(url: str, path: str, timeout: int = 180):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    with open(path, "wb") as f:
        f.write(response.content)


def ensure_directories():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(GEO_DIR, exist_ok=True)
    os.makedirs(REST_DIR, exist_ok=True)


@st.cache_data(show_spinner=False)
def ensure_geojson_files():
    ensure_directories()

    targets = [
        (SIDO_GEO_PATH, SIDO_URL, "시도"),
        (SIGUNGU_GEO_PATH, SIGUNGU_URL, "시군구"),
        (EMD_GEO_PATH, EMD_URL, "읍면동"),
    ]

    for path, url, label in targets:
        if not os.path.exists(path):
            with st.spinner(f"{label} GeoJSON 파일을 다운로드하는 중입니다..."):
                download_file(url, path)


# =========================================================
# 데이터 로딩
# =========================================================
@st.cache_data(show_spinner=False)
def load_geojson(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def load_restaurants() -> pd.DataFrame:
    if os.path.exists(RESTAURANT_PARQUET_PATH):
        df = pd.read_parquet(RESTAURANT_PARQUET_PATH)
    elif os.path.exists(RESTAURANT_CSV_PATH):
        df = pd.read_csv(RESTAURANT_CSV_PATH, encoding="utf-8")
    else:
        raise FileNotFoundError(
            "음식점 데이터 파일이 없습니다.\n\n"
            f"- 필요 파일: `{RESTAURANT_PARQUET_PATH}` 또는 `{RESTAURANT_CSV_PATH}`\n"
            "먼저 `prepare_data.py`를 실행해서 음식점 데이터를 생성해주세요."
        )

    expected_columns = {
        "name": "",
        "sido": "",
        "sigungu": "",
        "emd": "",
        "address": "",
        "road_address": "",
        "lat": None,
        "lon": None,
        "food_category": "기타",
        "rating": None,
        "review_count": 0,
        "main_menu": "",
        "summary": "",
        "parking": "",
        "waiting": "",
        "opening_hours": "",
        "phone": "",
        "source": "",
        "naver_map_url": "",
    }

    for col, default_value in expected_columns.items():
        if col not in df.columns:
            df[col] = default_value

    for col in [
        "name", "sido", "sigungu", "emd", "address", "road_address", "food_category",
        "main_menu", "summary", "parking", "waiting", "opening_hours", "phone",
        "source", "naver_map_url"
    ]:
        df[col] = df[col].astype(str).fillna("")

    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df["review_count"] = pd.to_numeric(df["review_count"], errors="coerce").fillna(0).astype(int)

    df = df.dropna(subset=["lat", "lon"]).copy()
    df = df[
        df["lat"].between(30, 40, inclusive="both")
        & df["lon"].between(120, 135, inclusive="both")
    ].copy()

    df["priority_score"] = df["review_count"].fillna(0)
    return df


# =========================================================
# GeoJSON 자동 준비
# =========================================================
try:
    ensure_geojson_files()
except Exception as e:
    st.error(f"GeoJSON 파일 준비 중 오류가 발생했습니다:\n\n{e}")
    st.stop()

# =========================================================
# 로딩
# =========================================================
try:
    sido_geo = load_geojson(SIDO_GEO_PATH)
    sigungu_geo = load_geojson(SIGUNGU_GEO_PATH)
    emd_geo = load_geojson(EMD_GEO_PATH)
except Exception as e:
    st.error(f"GeoJSON 파일 로딩 중 오류가 발생했습니다:\n\n{e}")
    st.stop()

try:
    restaurant_df = load_restaurants()
except Exception as e:
    st.error(str(e))
    st.stop()

sido_features = sido_geo.get("features", [])
sigungu_features = sigungu_geo.get("features", [])
emd_features = emd_geo.get("features", [])

for features in [sido_features, sigungu_features, emd_features]:
    for f in features:
        props = f.get("properties", {})
        props["_display_name"] = get_feature_name(props)
        props["_display_code"] = get_feature_code(props)
        f["properties"] = props

sido_names = sorted({f["properties"]["_display_name"] for f in sido_features if f["properties"].get("_display_name")})
sigungu_names = sorted({f["properties"]["_display_name"] for f in sigungu_features if f["properties"].get("_display_name")})
emd_names = sorted({f["properties"]["_display_name"] for f in emd_features if f["properties"].get("_display_name")})

# =========================================================
# 세션 상태
# =========================================================
if "selected_sido" not in st.session_state:
    st.session_state.selected_sido = ""
if "selected_sigungu" not in st.session_state:
    st.session_state.selected_sigungu = ""
if "selected_emd" not in st.session_state:
    st.session_state.selected_emd = ""
if "map_center" not in st.session_state:
    st.session_state.map_center = KOREA_CENTER
if "map_zoom" not in st.session_state:
    st.session_state.map_zoom = DEFAULT_ZOOM

# =========================================================
# 사이드바
# =========================================================
st.sidebar.header("🔎 검색 / 필터")

sido_options = ["전체"] + sorted(restaurant_df["sido"].dropna().astype(str).unique().tolist())
selected_sido = st.sidebar.selectbox(
    "시도",
    sido_options,
    index=0 if not st.session_state.selected_sido or st.session_state.selected_sido not in sido_options else sido_options.index(st.session_state.selected_sido),
)

if selected_sido == "전체":
    sigungu_candidates = sorted(restaurant_df["sigungu"].dropna().astype(str).unique().tolist())
else:
    sigungu_candidates = sorted(
        restaurant_df.loc[restaurant_df["sido"] == selected_sido, "sigungu"]
        .dropna().astype(str).unique().tolist()
    )

sigungu_options = ["전체"] + sigungu_candidates
selected_sigungu = st.sidebar.selectbox(
    "시군구",
    sigungu_options,
    index=0 if not st.session_state.selected_sigungu or st.session_state.selected_sigungu not in sigungu_options else sigungu_options.index(st.session_state.selected_sigungu),
)

if selected_sigungu == "전체":
    if selected_sido == "전체":
        emd_candidates = sorted(restaurant_df["emd"].dropna().astype(str).unique().tolist())
    else:
        emd_candidates = sorted(
            restaurant_df.loc[restaurant_df["sido"] == selected_sido, "emd"]
            .dropna().astype(str).unique().tolist()
        )
else:
    cond = restaurant_df["sigungu"] == selected_sigungu
    if selected_sido != "전체":
        cond &= restaurant_df["sido"] == selected_sido
    emd_candidates = sorted(
        restaurant_df.loc[cond, "emd"].dropna().astype(str).unique().tolist()
    )

emd_options = ["전체"] + emd_candidates
selected_emd = st.sidebar.selectbox(
    "읍면동",
    emd_options,
    index=0 if not st.session_state.selected_emd or st.session_state.selected_emd not in emd_options else emd_options.index(st.session_state.selected_emd),
)

food_type = st.sidebar.selectbox("음식 유형", FOOD_TYPES, index=0)
search_keyword = st.sidebar.text_input("검색어", placeholder="예: 냉면, 국밥, 가족식사")
min_review_count = st.sidebar.slider("최소 리뷰수", 0, 500, 0, 10)
sort_option = st.sidebar.radio("정렬 기준", ["추천순", "이름순"], index=0)
max_results = st.sidebar.slider("최대 표시 개수", 30, 300, 120, 10)

st.sidebar.info("현재 기본 데이터는 공공데이터 일반음식점 파일 기준입니다.")

st.session_state.selected_sido = "" if selected_sido == "전체" else selected_sido
st.session_state.selected_sigungu = "" if selected_sigungu == "전체" else selected_sigungu
st.session_state.selected_emd = "" if selected_emd == "전체" else selected_emd

# =========================================================
# 레벨
# =========================================================
def current_level() -> str:
    if st.session_state.selected_emd:
        return "emd"
    if st.session_state.selected_sigungu:
        return "sigungu"
    if st.session_state.selected_sido:
        return "sido_detail"
    return "sido"

level = current_level()

# =========================================================
# 표시 feature
# =========================================================
def get_display_features() -> Tuple[List[Dict[str, Any]], str]:
    if level == "sido":
        return sido_features, "시도"

    if level == "sido_detail":
        filtered = [f for f in sigungu_features if contains_name(f["properties"], st.session_state.selected_sido)]
        return filtered if filtered else sido_features, "시군구"

    if level == "sigungu":
        filtered = [f for f in emd_features if contains_name(f["properties"], st.session_state.selected_sigungu)]
        return filtered if filtered else sigungu_features, "읍면동"

    if level == "emd":
        filtered = [f for f in emd_features if f["properties"].get("_display_name") == st.session_state.selected_emd]
        return filtered if filtered else emd_features, "읍면동"

    return sido_features, "시도"

display_features, display_label = get_display_features()

if display_features:
    lat, lon = get_feature_centroid(display_features[0])
    if level == "sido":
        st.session_state.map_center = KOREA_CENTER
        st.session_state.map_zoom = 7
    elif level == "sido_detail":
        st.session_state.map_center = [lat, lon]
        st.session_state.map_zoom = 9
    elif level == "sigungu":
        st.session_state.map_center = [lat, lon]
        st.session_state.map_zoom = 11
    elif level == "emd":
        st.session_state.map_center = [lat, lon]
        st.session_state.map_zoom = 13

# =========================================================
# 업소 필터
# =========================================================
@st.cache_data(show_spinner=False)
def filter_restaurants_cached(
    df: pd.DataFrame,
    sido: str,
    sigungu: str,
    emd: str,
    food_type: str,
    search_keyword: str,
    min_review_count: int,
) -> pd.DataFrame:
    filtered = df.copy()

    if sido:
        filtered = filtered[filtered["sido"] == sido]
    if sigungu:
        filtered = filtered[filtered["sigungu"] == sigungu]
    if emd:
        filtered = filtered[filtered["emd"] == emd]

    if food_type != "전체":
        filtered = filtered[
            filtered["food_category"].astype(str).str.contains(food_type, case=False, na=False)
        ]

    if search_keyword.strip():
        k = search_keyword.strip()
        combined = (
            filtered["name"].astype(str) + " " +
            filtered["food_category"].astype(str) + " " +
            filtered["summary"].astype(str) + " " +
            filtered["address"].astype(str) + " " +
            filtered["road_address"].astype(str)
        )
        filtered = filtered[combined.str.contains(k, case=False, na=False)]

    filtered = filtered[filtered["review_count"].fillna(0) >= min_review_count]
    return filtered.copy()

filtered_df = filter_restaurants_cached(
    restaurant_df,
    st.session_state.selected_sido,
    st.session_state.selected_sigungu,
    st.session_state.selected_emd,
    food_type,
    search_keyword,
    min_review_count,
)

if sort_option == "추천순":
    filtered_df = filtered_df.sort_values(["priority_score", "name"], ascending=[False, True])
else:
    filtered_df = filtered_df.sort_values(["name"], ascending=[True])

if level == "sido":
    marker_limit = min(max_results, MAX_MARKERS_SIDO)
elif level == "sido_detail":
    marker_limit = min(max_results, MAX_MARKERS_SIGUNGU)
else:
    marker_limit = min(max_results, MAX_MARKERS_EMD)

filtered_df = filtered_df.head(marker_limit).copy()

# =========================================================
# 상단 요약
# =========================================================
c1, c2, c3, c4 = st.columns(4)
c1.metric("현재 표시 업소", f"{len(filtered_df):,}")
c2.metric("전체 업소", f"{len(restaurant_df):,}")
c3.metric("시도", st.session_state.selected_sido or "전체")
c4.metric("시군구", st.session_state.selected_sigungu or "전체")

# =========================================================
# 본문
# =========================================================
left_col, right_col = st.columns([1.85, 1.0])

with left_col:
    m = folium.Map(
        location=st.session_state.map_center,
        zoom_start=st.session_state.map_zoom,
        tiles="CartoDB positron",
        control_scale=True,
    )

    geojson_to_show = {"type": "FeatureCollection", "features": display_features}

    def style_fn(_feature):
        return {
            "fillColor": "#4F8BF9",
            "color": "#1E3A8A",
            "weight": 1.2,
            "fillOpacity": 0.18,
        }

    def highlight_fn(_feature):
        return {
            "fillColor": "#2563EB",
            "color": "#0F172A",
            "weight": 2.0,
            "fillOpacity": 0.32,
        }

    GeoJson(
        geojson_to_show,
        name=f"{display_label} 경계",
        style_function=style_fn,
        highlight_function=highlight_fn,
        tooltip=GeoJsonTooltip(
            fields=["_display_name"],
            aliases=[f"{display_label}:"],
            sticky=True,
            labels=True,
            style=(
                "background-color: white; color: #111827; font-family: Arial; "
                "font-size: 13px; padding: 8px; border-radius: 6px;"
            ),
        ),
        popup=GeoJsonPopup(
            fields=["_display_name", "_display_code"],
            aliases=[f"{display_label}명", "행정코드"],
            labels=True,
            style="background-color: white; color: #111827; font-size: 13px; padding: 10px;",
        ),
    ).add_to(m)

    for _, row in filtered_df.iterrows():
        road_address = row["road_address"] if normalize_str(row["road_address"]) else row["address"]
        rating_text = "정보 없음" if pd.isna(row["rating"]) else f"{row['rating']:.1f}"

        popup_html = f"""
        <div style="width: 340px; font-family: Arial, sans-serif; line-height: 1.55;">
            <h4 style="margin: 0 0 8px 0;">{row['name']}</h4>
            <div><b>행정구역</b>: {row['sido']} {row['sigungu']} {row['emd']}</div>
            <div><b>주소</b>: {road_address}</div>
            <div><b>음식 유형</b>: {row['food_category'] if normalize_str(row['food_category']) else '정보 없음'}</div>
            <div><b>평점</b>: {rating_text}</div>
            <div><b>리뷰 수</b>: {row['review_count']}</div>
            <div><b>대표 메뉴</b>: {row['main_menu'] if normalize_str(row['main_menu']) else '정보 없음'}</div>
            <div><b>요약</b>: {row['summary'] if normalize_str(row['summary']) else '정보 없음'}</div>
            <div><b>주차</b>: {row['parking'] if normalize_str(row['parking']) else '정보 없음'}</div>
            <div><b>웨이팅</b>: {row['waiting'] if normalize_str(row['waiting']) else '정보 없음'}</div>
            <div><b>운영시간</b>: {row['opening_hours'] if normalize_str(row['opening_hours']) else '정보 없음'}</div>
            <div><b>전화번호</b>: {row['phone'] if normalize_str(row['phone']) else '정보 없음'}</div>
            <div><b>출처</b>: {row['source'] if normalize_str(row['source']) else '공공데이터'}</div>
            <hr style="margin: 10px 0;">
            <div><a href="{row['naver_map_url']}" target="_blank">네이버 지도에서 보기</a></div>
        </div>
        """

        tooltip_text = f"{row['name']} | {row['food_category']}"

        folium.Marker(
            location=[row["lat"], row["lon"]],
            tooltip=tooltip_text,
            popup=folium.Popup(popup_html, max_width=380),
            icon=folium.Icon(icon="cutlery", prefix="fa"),
        ).add_to(m)

    folium.LayerControl().add_to(m)

    map_data = st_folium(
        m,
        height=760,
        use_container_width=True,
        returned_objects=[
            "last_active_drawing",
            "last_object_clicked",
            "last_object_clicked_tooltip",
            "last_object_clicked_popup",
        ],
    )

    clicked_name = try_get_clicked_name(map_data)

    if clicked_name:
        if clicked_name in sido_names:
            st.session_state.selected_sido = clicked_name
            st.session_state.selected_sigungu = ""
            st.session_state.selected_emd = ""
            st.rerun()
        elif clicked_name in sigungu_names:
            st.session_state.selected_sigungu = clicked_name
            st.session_state.selected_emd = ""
            st.rerun()
        elif clicked_name in emd_names:
            st.session_state.selected_emd = clicked_name
            st.rerun()

with right_col:
    st.subheader("📍 현재 선택")
    st.write(f"**시도**: {st.session_state.selected_sido or '전체'}")
    st.write(f"**시군구**: {st.session_state.selected_sigungu or '전체'}")
    st.write(f"**읍면동**: {st.session_state.selected_emd or '전체'}")
    st.write(f"**음식 유형**: {food_type}")

    st.markdown("---")
    st.subheader("🍴 업소 목록")

    if filtered_df.empty:
        st.info("현재 조건에 맞는 업소가 없습니다.")
    else:
        show_cols = ["name", "food_category", "review_count", "sido", "sigungu", "emd"]
        st.dataframe(filtered_df[show_cols], use_container_width=True, height=260)

        for i, (_, row) in enumerate(filtered_df.head(12).iterrows(), start=1):
            with st.expander(f"{i}. {row['name']}"):
                st.markdown(f"**행정구역**: {row['sido']} {row['sigungu']} {row['emd']}")
                st.markdown(f"**주소**: {row['road_address'] if normalize_str(row['road_address']) else row['address']}")
                st.markdown(f"**음식 유형**: {row['food_category'] if normalize_str(row['food_category']) else '정보 없음'}")
                st.markdown(f"**대표 메뉴**: {row['main_menu'] if normalize_str(row['main_menu']) else '정보 없음'}")
                st.markdown(f"**설명**: {row['summary'] if normalize_str(row['summary']) else '정보 없음'}")
                st.markdown(f"**주차**: {row['parking'] if normalize_str(row['parking']) else '정보 없음'}")
                st.markdown(f"**웨이팅**: {row['waiting'] if normalize_str(row['waiting']) else '정보 없음'}")
                st.markdown(f"**운영시간**: {row['opening_hours'] if normalize_str(row['opening_hours']) else '정보 없음'}")
                st.markdown(f"**전화번호**: {row['phone'] if normalize_str(row['phone']) else '정보 없음'}")
                st.markdown(f"[네이버 지도에서 보기]({row['naver_map_url']})")

    st.markdown("---")
    st.info("GeoJSON 파일은 이제 앱이 자동으로 다운로드합니다. 음식점 파일은 prepare_data.py로 생성해야 합니다.")
