import os
import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
import pandas as pd
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

st.title("🍜 대한민국 맛집 지도")
st.caption(
    "대한민국 행정구역을 단계별로 탐색하고, 평점 3.7 이상 맛집을 지도에서 확인할 수 있습니다."
)

# =========================================================
# 환경변수 / 외부 설정
# =========================================================
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()

# 행정구역 GeoJSON
# - 시도 / 시군구는 public raw URL 기본 제공
# - 읍면동은 파일이 매우 커서 로컬 파일 우선 사용 권장
#   예: data/korea_emd.geojson
SIDO_URL = os.getenv(
    "KOREA_SIDO_GEOJSON_URL",
    "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-provinces-geo.json",
)

SIGUNGU_URL = os.getenv(
    "KOREA_SIGUNGU_GEOJSON_URL",
    "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-municipalities-geo.json",
)

EMD_LOCAL_PATH = os.getenv("KOREA_EMD_GEOJSON_PATH", "data/korea_emd.geojson")

# =========================================================
# 공통 상수
# =========================================================
KOREA_CENTER = [36.35, 127.95]
DEFAULT_ZOOM = 7

MIN_RATING_DEFAULT = 3.7

# 사용자가 보기 좋게 표시할 음식 카테고리
FOOD_TYPES = [
    "전체",
    "한식",
    "중식",
    "일식",
    "양식",
    "분식",
    "카페/디저트",
    "치킨",
    "피자",
    "고기/구이",
    "국밥/탕/찌개",
    "면요리",
    "해산물",
    "술집/이자카야",
    "비건/샐러드",
    "패스트푸드",
]

FOOD_KEYWORDS = {
    "한식": ["한식", "백반", "국밥", "찌개", "김치찌개", "비빔밥", "불고기", "삼겹살", "갈비", "냉면", "한정식"],
    "중식": ["중식", "짜장면", "짬뽕", "탕수육", "마라", "중국집"],
    "일식": ["일식", "초밥", "스시", "라멘", "우동", "돈카츠", "가츠", "오마카세", "사시미"],
    "양식": ["양식", "파스타", "스테이크", "리조또", "브런치", "이탈리안", "프렌치"],
    "분식": ["분식", "떡볶이", "순대", "튀김", "김밥", "라볶이"],
    "카페/디저트": ["카페", "커피", "디저트", "베이커리", "케이크", "브런치", "빙수"],
    "치킨": ["치킨", "닭강정", "후라이드", "양념치킨"],
    "피자": ["피자"],
    "고기/구이": ["고기", "구이", "삼겹살", "갈비", "곱창", "막창", "오겹살", "숯불"],
    "국밥/탕/찌개": ["국밥", "탕", "찌개", "설렁탕", "감자탕", "순대국", "해장국"],
    "면요리": ["면", "국수", "냉면", "칼국수", "라멘", "우동", "파스타", "쌀국수"],
    "해산물": ["해산물", "횟집", "회", "조개", "게장", "해물탕", "초밥"],
    "술집/이자카야": ["술집", "이자카야", "포차", "호프", "와인바", "펍", "맥주"],
    "비건/샐러드": ["비건", "샐러드", "채식"],
    "패스트푸드": ["버거", "햄버거", "샌드위치", "패스트푸드", "핫도그"],
}

# 특별시/광역시/특별자치시/도 이름 표준화
REGION_ALIASES = {
    "서울": "서울특별시",
    "부산": "부산광역시",
    "대구": "대구광역시",
    "인천": "인천광역시",
    "광주": "광주광역시",
    "대전": "대전광역시",
    "울산": "울산광역시",
    "세종": "세종특별자치시",
    "경기": "경기도",
    "강원": "강원특별자치도",
    "충북": "충청북도",
    "충남": "충청남도",
    "전북": "전북특별자치도",
    "전남": "전라남도",
    "경북": "경상북도",
    "경남": "경상남도",
    "제주": "제주특별자치도",
}

# =========================================================
# 유틸 함수
# =========================================================
@st.cache_data(show_spinner=False, ttl=60 * 60)
def fetch_json(url: str) -> Dict[str, Any]:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


@st.cache_data(show_spinner=False, ttl=60 * 60)
def load_local_geojson(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def safe_get(props: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        if key in props and props[key] not in (None, ""):
            return str(props[key]).strip()
    return ""


def normalize_region_name(name: str) -> str:
    name = normalize_text(name)
    if name in REGION_ALIASES:
        return REGION_ALIASES[name]
    return name


def infer_food_type(name: str, text: str) -> str:
    combined = f"{name} {text}".lower()
    for category, keywords in FOOD_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in combined:
                return category
    return "기타"


def infer_waiting(text: str) -> str:
    if not text:
        return "정보 부족"
    t = text.lower()
    keywords_yes = ["웨이팅", "wait", "줄 서", "대기", "오픈런", "예약 필수", "혼잡"]
    keywords_no = ["널널", "한산", "바로 입장", "대기 없음", "웨이팅 없음"]
    if any(k in t for k in keywords_yes):
        return "가능성 높음"
    if any(k in t for k in keywords_no):
        return "적은 편"
    return "정보 부족"


def infer_parking(text: str) -> str:
    if not text:
        return "정보 부족"
    t = text.lower()
    yes_keywords = ["주차", "parking", "전용 주차", "주차장", "발렛"]
    no_keywords = ["주차 불가", "주차 어려움", "주차 없음", "주차장 없음"]
    if any(k in t for k in no_keywords):
        return "없거나 어려움"
    if any(k in t for k in yes_keywords):
        return "가능성 있음"
    return "정보 부족"


def summarize_taste(reviews: List[Dict[str, Any]], editorial_summary: str = "") -> str:
    snippets = []
    if editorial_summary:
        snippets.append(editorial_summary)

    for review in reviews[:3]:
        txt = normalize_text(review.get("text", {}).get("text", "")) or normalize_text(review.get("text", ""))
        if txt:
            snippets.append(txt[:120])

    if not snippets:
        return "리뷰 요약 정보가 부족합니다."
    joined = " / ".join(snippets)
    return joined[:350]


def make_naver_map_search_url(query: str) -> str:
    # 직접 장소 링크를 안정적으로 얻기 어려워 검색 링크로 대체
    return f"https://map.naver.com/v5/search/{requests.utils.quote(query)}"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_feature_name(props: Dict[str, Any]) -> str:
    candidates = [
        "name", "NAME_1", "NAME_2", "NAME_3",
        "CTP_KOR_NM", "SIG_KOR_NM", "EMD_KOR_NM",
        "adm_nm", "sggnm", "sidonm", "emd_nm"
    ]
    for c in candidates:
        if c in props and props[c]:
            return str(props[c]).strip()
    return "이름없음"


def get_admin_code(props: Dict[str, Any]) -> str:
    candidates = ["adm_cd", "adm_cd8", "code", "SIG_CD", "EMD_CD", "CTPRVN_CD"]
    for c in candidates:
        if c in props and props[c]:
            return str(props[c]).strip()
    return ""


def feature_matches_parent(feature_props: Dict[str, Any], parent_name: str) -> bool:
    if not parent_name:
        return True
    full = json.dumps(feature_props, ensure_ascii=False)
    return parent_name in full


def get_feature_centroid(feature: Dict[str, Any]) -> Tuple[float, float]:
    """
    아주 단순한 중심값 계산.
    정확한 지오메트리 중심이 아니라도 지도 이동용으로 충분.
    반환값: (lat, lon)
    """
    geom = feature.get("geometry", {})
    gtype = geom.get("type")
    coords = geom.get("coordinates", [])

    points = []

    def collect(arr):
        if isinstance(arr, list):
            if len(arr) == 2 and all(isinstance(v, (int, float)) for v in arr):
                points.append(arr)
            else:
                for item in arr:
                    collect(item)

    collect(coords)

    if not points:
        return KOREA_CENTER[0], KOREA_CENTER[1]

    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lon


def try_extract_clicked_region(map_data: Dict[str, Any]) -> Optional[str]:
    if not map_data:
        return None

    # st_folium이 반환하는 값은 환경에 따라 다를 수 있어 최대한 폭넓게 처리
    last_active = map_data.get("last_active_drawing")
    if isinstance(last_active, dict):
        props = last_active.get("properties", {})
        if props:
            return get_feature_name(props)

    last_object = map_data.get("last_object_clicked")
    if isinstance(last_object, dict):
        props = last_object.get("properties", {})
        if props:
            return get_feature_name(props)

    tooltip = map_data.get("last_object_clicked_tooltip")
    if tooltip:
        return str(tooltip).strip()

    popup = map_data.get("last_object_clicked_popup")
    if popup:
        return str(popup).strip()

    return None


# =========================================================
# Google Places API
# =========================================================
def google_headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": ",".join([
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.rating",
            "places.userRatingCount",
            "places.primaryTypeDisplayName",
            "places.shortFormattedAddress",
            "places.googleMapsUri",
            "places.regularOpeningHours",
            "places.editorialSummary",
            "places.priceLevel",
            "places.websiteUri"
        ]),
    }


@st.cache_data(show_spinner=False, ttl=60 * 30)
def search_places_text(query: str, page_size: int = 15) -> List[Dict[str, Any]]:
    if not GOOGLE_MAPS_API_KEY:
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    payload = {
        "textQuery": query,
        "pageSize": page_size,
        "languageCode": "ko",
        "regionCode": "KR",
    }

    res = requests.post(url, headers=google_headers(), json=payload, timeout=30)
    if res.status_code != 200:
        return []
    data = res.json()
    return data.get("places", [])


def place_details_headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": ",".join([
            "id",
            "displayName",
            "formattedAddress",
            "location",
            "rating",
            "userRatingCount",
            "primaryTypeDisplayName",
            "regularOpeningHours",
            "googleMapsUri",
            "websiteUri",
            "editorialSummary",
            "reviews",
            "priceLevel",
            "parkingOptions",
            "delivery",
            "takeout",
            "dineIn",
            "servesBreakfast",
            "servesLunch",
            "servesDinner",
            "servesDessert"
        ]),
    }


@st.cache_data(show_spinner=False, ttl=60 * 30)
def get_place_detail(place_id: str) -> Dict[str, Any]:
    if not GOOGLE_MAPS_API_KEY:
        return {}
    url = f"https://places.googleapis.com/v1/places/{place_id}"
    res = requests.get(url, headers=place_details_headers(), timeout=30)
    if res.status_code != 200:
        return {}
    return res.json()


def is_restaurant_place(place: Dict[str, Any]) -> bool:
    text = json.dumps(place, ensure_ascii=False).lower()
    keywords = ["restaurant", "food", "meal", "카페", "restaurant", "eatery", "bakery", "coffee", "bar"]
    return any(k in text for k in keywords)


def build_restaurant_row(place: Dict[str, Any], my_lat: Optional[float], my_lon: Optional[float]) -> Dict[str, Any]:
    place_id = place.get("id", "")
    detail = get_place_detail(place_id) if place_id else {}

    display_name = (
        normalize_text(place.get("displayName", {}).get("text"))
        or normalize_text(detail.get("displayName", {}).get("text"))
        or "이름 없음"
    )
    address = normalize_text(place.get("formattedAddress")) or normalize_text(detail.get("formattedAddress"))
    location = place.get("location") or detail.get("location") or {}
    lat = location.get("latitude")
    lon = location.get("longitude")

    rating = place.get("rating", detail.get("rating"))
    user_rating_count = place.get("userRatingCount", detail.get("userRatingCount"))
    primary_type = (
        normalize_text(place.get("primaryTypeDisplayName", {}).get("text"))
        or normalize_text(detail.get("primaryTypeDisplayName", {}).get("text"))
    )
    google_maps_uri = normalize_text(place.get("googleMapsUri")) or normalize_text(detail.get("googleMapsUri"))
    website_uri = normalize_text(place.get("websiteUri")) or normalize_text(detail.get("websiteUri"))
    editorial_summary = normalize_text(detail.get("editorialSummary", {}).get("text"))

    reviews = detail.get("reviews", []) if isinstance(detail.get("reviews", []), list) else []
    taste_summary = summarize_taste(reviews, editorial_summary=editorial_summary)

    text_blob = json.dumps(detail, ensure_ascii=False)
    parking = infer_parking(text_blob)
    waiting = infer_waiting(text_blob)
    food_type = infer_food_type(display_name, f"{primary_type} {text_blob}")

    distance_km = None
    if my_lat is not None and my_lon is not None and lat is not None and lon is not None:
        distance_km = round(haversine_km(my_lat, my_lon, lat, lon), 2)

    naver_query = f"{display_name} {address}"
    naver_url = make_naver_map_search_url(naver_query)

    # 간단 운영정보
    hours_text = "정보 부족"
    roh = detail.get("regularOpeningHours", {})
    if isinstance(roh, dict):
        weekday_desc = roh.get("weekdayDescriptions", [])
        if weekday_desc:
            hours_text = " / ".join(weekday_desc[:3])
            if len(weekday_desc) > 3:
                hours_text += " ..."

    return {
        "name": display_name,
        "address": address,
        "lat": lat,
        "lon": lon,
        "rating": rating,
        "user_rating_count": user_rating_count,
        "food_type": food_type if food_type != "기타" else (primary_type or "기타"),
        "taste_summary": taste_summary,
        "parking": parking,
        "waiting": waiting,
        "hours": hours_text,
        "google_maps_url": google_maps_uri,
        "website_url": website_uri,
        "naver_map_url": naver_url,
        "distance_km": distance_km,
    }


def search_restaurants(
    region_text: str,
    food_type: str,
    min_rating: float,
    my_lat: Optional[float],
    my_lon: Optional[float],
    query_extra: str = "",
) -> pd.DataFrame:
    if not GOOGLE_MAPS_API_KEY:
        return pd.DataFrame()

    keywords = []
    if food_type and food_type != "전체":
        keywords.append(food_type)
    else:
        keywords.append("맛집")

    if query_extra.strip():
        keywords.append(query_extra.strip())

    query = f"{region_text} {' '.join(keywords)}"

    places = search_places_text(query=query, page_size=20)
    rows = []

    for p in places:
        if not is_restaurant_place(p):
            continue
        rating = p.get("rating")
        if rating is None or float(rating) < min_rating:
            continue

        row = build_restaurant_row(p, my_lat=my_lat, my_lon=my_lon)
        if row["lat"] is None or row["lon"] is None:
            continue
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["name", "address"]).copy()

    # 음식유형 필터 정제
    if food_type != "전체":
        df = df[
            df["food_type"].astype(str).str.contains(food_type, case=False, na=False)
            | df["taste_summary"].astype(str).str.contains(food_type, case=False, na=False)
            | df["name"].astype(str).str.contains(food_type, case=False, na=False)
        ].copy()

    # 정렬: 거리 우선(있으면), 없으면 평점/리뷰수
    if "distance_km" in df.columns and df["distance_km"].notna().any():
        df = df.sort_values(by=["distance_km", "rating", "user_rating_count"], ascending=[True, False, False])
    else:
        df = df.sort_values(by=["rating", "user_rating_count"], ascending=[False, False])

    return df.reset_index(drop=True)


# =========================================================
# GeoJSON 로드
# =========================================================
@st.cache_data(show_spinner=True, ttl=60 * 60)
def load_sido_geojson() -> Dict[str, Any]:
    return fetch_json(SIDO_URL)


@st.cache_data(show_spinner=True, ttl=60 * 60)
def load_sigungu_geojson() -> Dict[str, Any]:
    return fetch_json(SIGUNGU_URL)


@st.cache_data(show_spinner=False, ttl=60 * 60)
def load_emd_geojson() -> Optional[Dict[str, Any]]:
    return load_local_geojson(EMD_LOCAL_PATH)


def prepare_named_features(geojson_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    features = geojson_obj.get("features", [])
    prepared = []
    for f in features:
        props = f.get("properties", {})
        props = dict(props)
        props["_display_name"] = get_feature_name(props)
        props["_admin_code"] = get_admin_code(props)
        f["properties"] = props
        prepared.append(f)
    return prepared


sido_geojson = load_sido_geojson()
sigungu_geojson = load_sigungu_geojson()
emd_geojson = load_emd_geojson()

sido_features = prepare_named_features(sido_geojson)
sigungu_features = prepare_named_features(sigungu_geojson)
emd_features = prepare_named_features(emd_geojson) if emd_geojson else []

sido_names = sorted({f["properties"].get("_display_name", "") for f in sido_features if f["properties"].get("_display_name")})
sigungu_names = sorted({f["properties"].get("_display_name", "") for f in sigungu_features if f["properties"].get("_display_name")})

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

with st.sidebar.expander("행정구역 선택", expanded=True):
    selected_sido = st.selectbox(
        "시도",
        ["전체"] + sido_names,
        index=(["전체"] + sido_names).index(st.session_state.selected_sido) if st.session_state.selected_sido in (["전체"] + sido_names) else 0
    )

    # 시군구 후보를 시도명 기반으로 대략 필터링
    if selected_sido == "전체":
        sigungu_candidates = sigungu_names
    else:
        sigungu_candidates = sorted([
            f["properties"]["_display_name"]
            for f in sigungu_features
            if selected_sido in json.dumps(f["properties"], ensure_ascii=False)
        ])
        if not sigungu_candidates:
            sigungu_candidates = sigungu_names

    selected_sigungu = st.selectbox(
        "시군구",
        ["전체"] + sigungu_candidates,
        index=(["전체"] + sigungu_candidates).index(st.session_state.selected_sigungu) if st.session_state.selected_sigungu in (["전체"] + sigungu_candidates) else 0
    )

    # 읍면동 후보
    emd_candidates = []
    if emd_features:
        if selected_sigungu != "전체":
            emd_candidates = sorted([
                f["properties"]["_display_name"]
                for f in emd_features
                if selected_sigungu in json.dumps(f["properties"], ensure_ascii=False)
            ])
        elif selected_sido != "전체":
            emd_candidates = sorted([
                f["properties"]["_display_name"]
                for f in emd_features
                if selected_sido in json.dumps(f["properties"], ensure_ascii=False)
            ])
        else:
            emd_candidates = sorted([
                f["properties"]["_display_name"] for f in emd_features
            ])[:1000]

    selected_emd = st.selectbox(
        "읍면동",
        ["전체"] + emd_candidates if emd_candidates else ["전체"],
        index=(["전체"] + emd_candidates).index(st.session_state.selected_emd) if emd_candidates and st.session_state.selected_emd in (["전체"] + emd_candidates) else 0
    )

with st.sidebar.expander("맛집 조건", expanded=True):
    food_type = st.selectbox("음식 유형", FOOD_TYPES, index=0)
    min_rating = st.slider("최소 평점", 3.0, 5.0, MIN_RATING_DEFAULT, 0.1)
    search_keyword = st.text_input("추가 검색어", placeholder="예: 주차, 가족식사, 야식, 혼밥, 오마카세")
    only_parking = st.checkbox("주차 가능한 곳 우선 보기", value=False)
    only_low_waiting = st.checkbox("웨이팅 적은 곳 우선 보기", value=False)

with st.sidebar.expander("내 위치 / 거리 기반 추천", expanded=True):
    use_my_location = st.checkbox("내 위치 기준으로 정렬", value=False)
    my_lat = st.number_input("내 위치 위도", value=37.5665, format="%.6f")
    my_lon = st.number_input("내 위치 경도", value=126.9780, format="%.6f")

with st.sidebar.expander("데이터/API 안내", expanded=False):
    st.markdown(
        """
- Google Places API 키가 있으면 맛집 정보를 자동 조회합니다.
- 환경변수: `GOOGLE_MAPS_API_KEY`
- 읍면동 경계는 `data/korea_emd.geojson` 파일이 있으면 자동 활성화됩니다.
- 네이버 리뷰는 공식 공개 API 제약 때문에 상세 자동 수집이 어렵습니다.
  대신 팝업에 네이버 지도 검색 링크를 제공합니다.
        """
    )

# 세션 반영
st.session_state.selected_sido = "" if selected_sido == "전체" else selected_sido
st.session_state.selected_sigungu = "" if selected_sigungu == "전체" else selected_sigungu
st.session_state.selected_emd = "" if selected_emd == "전체" else selected_emd

effective_my_lat = my_lat if use_my_location else None
effective_my_lon = my_lon if use_my_location else None

# =========================================================
# 지도 표시 레벨 결정
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
# GeoJSON 필터
# =========================================================
def filter_features_by_level() -> Tuple[List[Dict[str, Any]], str]:
    if level == "sido":
        return sido_features, "시도"

    if level == "sido_detail":
        filtered = [
            f for f in sigungu_features
            if feature_matches_parent(f["properties"], st.session_state.selected_sido)
        ]
        if filtered:
            return filtered, "시군구"
        return sido_features, "시도"

    if level == "sigungu":
        if emd_features:
            filtered = [
                f for f in emd_features
                if feature_matches_parent(f["properties"], st.session_state.selected_sigungu)
            ]
            if filtered:
                return filtered, "읍면동"
        # 읍면동이 없으면 현재 시군구만 강조
        filtered = [
            f for f in sigungu_features
            if f["properties"].get("_display_name") == st.session_state.selected_sigungu
        ]
        return filtered, "시군구"

    if level == "emd":
        filtered = [
            f for f in emd_features
            if f["properties"].get("_display_name") == st.session_state.selected_emd
        ]
        if filtered:
            return filtered, "읍면동"

    return sido_features, "시도"

display_features, display_label = filter_features_by_level()

# 지도 중심 자동 이동
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
# 맛집 검색 대상 텍스트 결정
# =========================================================
region_parts = []
if st.session_state.selected_sido:
    region_parts.append(st.session_state.selected_sido)
if st.session_state.selected_sigungu:
    region_parts.append(st.session_state.selected_sigungu)
if st.session_state.selected_emd:
    region_parts.append(st.session_state.selected_emd)

region_query_text = " ".join(region_parts).strip() or "대한민국"

restaurants_df = pd.DataFrame()
if GOOGLE_MAPS_API_KEY:
    with st.spinner("맛집 정보를 조회하는 중입니다..."):
        restaurants_df = search_restaurants(
            region_text=region_query_text,
            food_type=food_type,
            min_rating=min_rating,
            my_lat=effective_my_lat,
            my_lon=effective_my_lon,
            query_extra=search_keyword,
        )

        if not restaurants_df.empty:
            if only_parking:
                restaurants_df = restaurants_df[
                    restaurants_df["parking"].astype(str).str.contains("가능", na=False)
                ].copy()

            if only_low_waiting:
                restaurants_df = restaurants_df[
                    restaurants_df["waiting"].astype(str).isin(["적은 편", "정보 부족"])
                ].copy()

# =========================================================
# 지도 렌더링
# =========================================================
left_col, right_col = st.columns([1.8, 1.0])

with left_col:
    m = folium.Map(
        location=st.session_state.map_center,
        zoom_start=st.session_state.map_zoom,
        tiles="CartoDB positron",
        control_scale=True,
    )

    # 현재 표시 레벨 경계
    display_geojson = {
        "type": "FeatureCollection",
        "features": display_features
    }

    def style_fn(_feature):
        return {
            "fillColor": "#4F8BF9",
            "color": "#1E3A8A",
            "weight": 1.5,
            "fillOpacity": 0.18,
        }

    def highlight_fn(_feature):
        return {
            "fillColor": "#2563EB",
            "color": "#0F172A",
            "weight": 2.5,
            "fillOpacity": 0.35,
        }

    GeoJson(
        display_geojson,
        name=f"{display_label} 경계",
        style_function=style_fn,
        highlight_function=highlight_fn,
        tooltip=GeoJsonTooltip(
            fields=["_display_name"],
            aliases=[f"{display_label}:"],
            sticky=True,
            labels=True,
            localize=True,
            style=(
                "background-color: white; color: #111827; font-family: Arial; "
                "font-size: 13px; padding: 8px; border-radius: 6px;"
            ),
        ),
        popup=GeoJsonPopup(
            fields=["_display_name", "_admin_code"],
            aliases=[f"{display_label}명", "행정코드"],
            localize=True,
            labels=True,
            style="background-color: white; color: #111827; font-size: 13px; padding: 10px;",
        ),
    ).add_to(m)

    # 맛집 마커
    if not restaurants_df.empty:
        for _, row in restaurants_df.iterrows():
            popup_html = f"""
            <div style="width: 330px; font-family: Arial, sans-serif; line-height: 1.5;">
                <h4 style="margin: 0 0 8px 0;">{row['name']}</h4>
                <div><b>주소</b>: {row['address']}</div>
                <div><b>음식 유형</b>: {row['food_type']}</div>
                <div><b>평점</b>: {row['rating']} / 리뷰수: {row['user_rating_count']}</div>
                <div><b>맛 요약</b>: {row['taste_summary']}</div>
                <div><b>주차</b>: {row['parking']}</div>
                <div><b>웨이팅</b>: {row['waiting']}</div>
                <div><b>영업 정보</b>: {row['hours']}</div>
                {"<div><b>내 위치 기준 거리</b>: " + str(row['distance_km']) + " km</div>" if pd.notna(row.get('distance_km')) else ""}
                <hr style="margin: 10px 0;">
                <div><a href="{row['google_maps_url']}" target="_blank">구글 지도에서 보기</a></div>
                <div><a href="{row['naver_map_url']}" target="_blank">네이버 지도에서 검색하기</a></div>
                {f'<div><a href="{row["website_url"]}" target="_blank">공식 웹사이트</a></div>' if row.get("website_url") else ""}
            </div>
            """

            tooltip_text = f"{row['name']} | 평점 {row['rating']}"
            folium.Marker(
                location=[row["lat"], row["lon"]],
                tooltip=tooltip_text,
                popup=folium.Popup(popup_html, max_width=360),
                icon=folium.Icon(icon="cutlery", prefix="fa"),
            ).add_to(m)

    folium.LayerControl().add_to(m)

    map_data = st_folium(
        m,
        width=None,
        height=760,
        returned_objects=["last_active_drawing", "last_object_clicked", "last_object_clicked_tooltip", "last_object_clicked_popup"],
        use_container_width=True,
    )

    clicked_region_name = try_extract_clicked_region(map_data)

    # 클릭 기반 드릴다운
    if clicked_region_name:
        # 1) 시도 클릭
        if clicked_region_name in sido_names:
            st.session_state.selected_sido = clicked_region_name
            st.session_state.selected_sigungu = ""
            st.session_state.selected_emd = ""
            st.rerun()

        # 2) 시군구 클릭
        elif clicked_region_name in sigungu_names:
            st.session_state.selected_sigungu = clicked_region_name
            st.session_state.selected_emd = ""
            st.rerun()

        # 3) 읍면동 클릭
        elif emd_features and clicked_region_name in [f["properties"]["_display_name"] for f in emd_features]:
            st.session_state.selected_emd = clicked_region_name
            st.rerun()

with right_col:
    st.subheader("📌 현재 탐색 범위")
    st.write(f"- 시도: {st.session_state.selected_sido or '전체'}")
    st.write(f"- 시군구: {st.session_state.selected_sigungu or '전체'}")
    st.write(f"- 읍면동: {st.session_state.selected_emd or '전체'}")
    st.write(f"- 음식 유형: {food_type}")
    st.write(f"- 최소 평점: {min_rating}")

    if not GOOGLE_MAPS_API_KEY:
        st.warning(
            "Google Places API 키가 없어 맛집 자동 조회가 비활성화되었습니다.\n\n"
            "환경변수 `GOOGLE_MAPS_API_KEY`를 설정한 뒤 다시 실행하세요."
        )

    if not emd_geojson:
        st.info(
            "읍면동 경계 파일(`data/korea_emd.geojson`)이 아직 없습니다.\n\n"
            "현재는 시도/시군구 중심으로 동작하며, 파일을 추가하면 읍면동까지 자동 확장됩니다."
        )

    st.subheader("🍽 추천 맛집")
    if restaurants_df.empty:
        st.write("조건에 맞는 맛집 결과가 없거나 API 키가 설정되지 않았습니다.")
    else:
        show_df = restaurants_df.copy()

        display_cols = [
            "name", "food_type", "rating", "user_rating_count",
            "parking", "waiting", "distance_km", "address"
        ]
        display_cols = [c for c in display_cols if c in show_df.columns]

        st.dataframe(
            show_df[display_cols],
            use_container_width=True,
            height=420
        )

        top_n = min(8, len(show_df))
        for i in range(top_n):
            row = show_df.iloc[i]
            with st.expander(f"{i+1}. {row['name']} | 평점 {row['rating']}"):
                st.markdown(f"**주소**: {row['address']}")
                st.markdown(f"**음식 유형**: {row['food_type']}")
                st.markdown(f"**맛 요약**: {row['taste_summary']}")
                st.markdown(f"**주차**: {row['parking']}")
                st.markdown(f"**웨이팅**: {row['waiting']}")
                st.markdown(f"**영업 정보**: {row['hours']}")
                if pd.notna(row.get("distance_km")):
                    st.markdown(f"**내 위치 기준 거리**: {row['distance_km']} km")
                st.markdown(f"[구글 지도에서 보기]({row['google_maps_url']})")
                st.markdown(f"[네이버 지도에서 검색하기]({row['naver_map_url']})")
                if row.get("website_url"):
                    st.markdown(f"[공식 웹사이트]({row['website_url']})")

    st.subheader("💡 이 앱에 들어간 추가 정보")
    st.markdown(
        """
- **평점 기준 필터**: 기본 3.7 이상
- **음식 유형 필터**: 한식, 중식, 일식, 카페 등
- **주차 가능성 추정**
- **웨이팅 가능성 추정**
- **내 위치 기준 거리 정렬**
- **구글 지도 / 네이버 지도 바로가기**
- **정보 부족 시 검색 링크 제공**
        """
    )

st.markdown("---")
st.caption(
    "팁: 시도 → 시군구 → 읍면동 순서로 클릭하며 좁혀가세요. "
    "읍면동까지 정확히 쓰려면 `data/korea_emd.geojson` 파일을 추가하는 것이 가장 좋습니다."
)
