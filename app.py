import os
import re
import io
import json
import ssl
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin

import pandas as pd
import requests
import streamlit as st
import folium
from folium.features import GeoJson, GeoJsonTooltip, GeoJsonPopup
from streamlit_folium import st_folium
from pyproj import Transformer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================================================
# 기본 설정
# =========================================================
st.set_page_config(
    page_title="대한민국 맛집 지도",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🍽 대한민국 맛집 지도")
st.caption("실제 행정구역 경계 + 공공데이터 기반 실제 음식점 지도")

# =========================================================
# 경로 / URL
# =========================================================
DATA_DIR = "data"
GEO_DIR = os.path.join(DATA_DIR, "geo")
REST_DIR = os.path.join(DATA_DIR, "restaurants")

SIDO_GEO_PATH = os.path.join(GEO_DIR, "sido.geojson")
SIGUNGU_GEO_PATH = os.path.join(GEO_DIR, "sigungu.geojson")
EMD_GEO_PATH = os.path.join(GEO_DIR, "emd.geojson")

RESTAURANT_RAW_PATH = os.path.join(REST_DIR, "restaurant_raw_download")
RESTAURANT_PARQUET_PATH = os.path.join(REST_DIR, "restaurants_merged.parquet")
RESTAURANT_CSV_PATH = os.path.join(REST_DIR, "restaurants_merged.csv")

SIDO_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-provinces-geo.json"
SIGUNGU_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-municipalities-geo.json"
EMD_URL = "https://raw.githubusercontent.com/vuski/admdongkor/master/ver20220101/HangJeongDong_ver20220101.geojson"

# 현재 공공데이터포털이 안내하는 일반음식점 제공 URL
GENERAL_RESTAURANTS_INFO_URL = "https://file.localdata.go.kr/file/general_restaurants/info"
# 예전 경로(폴백)
GENERAL_RESTAURANTS_LEGACY_XLSX_URL = "https://www.localdata.go.kr/datafile/each/07_24_04_P.xlsx"
# 폴백용 모범음식점
EXCELLENT_RESTAURANTS_INFO_URL = "https://file.localdata.go.kr/file/excellent_restaurant_info/info"

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
def ensure_directories():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(GEO_DIR, exist_ok=True)
    os.makedirs(REST_DIR, exist_ok=True)


def normalize_str(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def make_naver_map_search_url(query: str) -> str:
    return f"https://map.naver.com/v5/search/{quote(query)}"


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


def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = list(df.columns)
    for cand in candidates:
        if cand in cols:
            return cand
    lower_map = {str(c).strip().lower(): c for c in cols}
    for cand in candidates:
        key = str(cand).strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def parse_address_parts(address: str):
    address = normalize_str(address)
    if not address:
        return "", "", ""

    parts = address.split()
    sido = parts[0] if len(parts) >= 1 else ""
    sigungu = parts[1] if len(parts) >= 2 else ""
    emd = parts[2] if len(parts) >= 3 else ""

    if sido == "세종특별자치시" and len(parts) >= 2:
        sigungu = "세종특별자치시"
        emd = parts[1] if len(parts) >= 2 else ""

    return sido, sigungu, emd


def transform_xy_to_wgs84(x_series: pd.Series, y_series: pd.Series):
    x = pd.to_numeric(x_series, errors="coerce")
    y = pd.to_numeric(y_series, errors="coerce")

    # data.go.kr 현재 안내는 EPSG:5174
    t5174 = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    lon_5174, lat_5174 = t5174.transform(x.values, y.values)
    lat_5174 = pd.Series(lat_5174)
    lon_5174 = pd.Series(lon_5174)

    valid_5174 = (
        lat_5174.between(30, 40, inclusive="both")
        & lon_5174.between(120, 135, inclusive="both")
    )

    # 과거 문헌/미러 대응용 폴백
    t2097 = Transformer.from_crs("EPSG:2097", "EPSG:4326", always_xy=True)
    lon_2097, lat_2097 = t2097.transform(x.values, y.values)
    lat_2097 = pd.Series(lat_2097)
    lon_2097 = pd.Series(lon_2097)

    valid_2097 = (
        lat_2097.between(30, 40, inclusive="both")
        & lon_2097.between(120, 135, inclusive="both")
    )

    if valid_5174.mean() >= valid_2097.mean():
        return lat_5174, lon_5174
    return lat_2097, lon_2097


def build_summary(row):
    pieces = []
    food_type = normalize_str(row.get("food_category", ""))
    if food_type:
        pieces.append(f"{food_type} 업종")

    status = normalize_str(row.get("business_status", ""))
    detail_status = normalize_str(row.get("detail_status", ""))
    if detail_status:
        pieces.append(f"상태: {detail_status}")
    elif status:
        pieces.append(f"상태: {status}")

    return " / ".join(pieces)


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    })
    return session


def robust_get(url: str, timeout: int = 300) -> requests.Response:
    session = make_session()
    last_error = None

    # 1차: 기본 검증
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r
    except Exception as e:
        last_error = e

    # 2차: SSL 검증 해제
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True, verify=False)
        r.raise_for_status()
        return r
    except Exception as e:
        last_error = e

    raise last_error


def extract_download_link_from_html(html: str, base_url: str) -> Optional[str]:
    # csv/xlsx/zip 직접 링크 추출
    patterns = [
        r'href=["\']([^"\']+\.csv(?:\?[^"\']*)?)["\']',
        r'href=["\']([^"\']+\.xlsx(?:\?[^"\']*)?)["\']',
        r'href=["\']([^"\']+\.zip(?:\?[^"\']*)?)["\']',
        r'["\'](https?://[^"\']+/(?:download|down)[^"\']*)["\']',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, flags=re.IGNORECASE)
        if m:
            return urljoin(base_url, m.group(1))
    return None


def download_binary(url: str) -> bytes:
    r = robust_get(url)
    ctype = (r.headers.get("content-type") or "").lower()

    # HTML이면 다운로드 링크를 한 번 더 추출
    if "text/html" in ctype or r.text.lstrip().lower().startswith("<!doctype html") or "<html" in r.text[:1000].lower():
        link = extract_download_link_from_html(r.text, url)
        if link:
            r2 = robust_get(link)
            r2.raise_for_status()
            return r2.content

    return r.content


def sniff_file_kind(binary: bytes) -> str:
    if binary[:2] == b"PK":
        return "xlsx"
    head = binary[:4000].decode("utf-8", errors="ignore").lower()
    if "," in head or "사업장명" in head or "업소명" in head:
        return "csv"
    if "<html" in head:
        return "html"
    return "unknown"


# =========================================================
# 자동 준비
# =========================================================
@st.cache_data(show_spinner=False)
def ensure_geojson_files():
    ensure_directories()
    targets = [
        (SIDO_GEO_PATH, SIDO_URL),
        (SIGUNGU_GEO_PATH, SIGUNGU_URL),
        (EMD_GEO_PATH, EMD_URL),
    ]
    for path, url in targets:
        if not os.path.exists(path):
            content = download_binary(url)
            with open(path, "wb") as f:
                f.write(content)


def load_raw_restaurant_source() -> Tuple[pd.DataFrame, str]:
    """
    반환: (원본 dataframe, source_name)
    일반음식점 전체 다운로드를 우선 시도.
    실패하면 모범음식점으로 폴백.
    """
    source_candidates = [
        ("일반음식점", GENERAL_RESTAURANTS_INFO_URL),
        ("일반음식점_레거시", GENERAL_RESTAURANTS_LEGACY_XLSX_URL),
        ("모범음식점", EXCELLENT_RESTAURANTS_INFO_URL),
    ]

    errors = []

    for label, url in source_candidates:
        try:
            raw = download_binary(url)
            kind = sniff_file_kind(raw)

            if kind == "csv":
                # utf-8-sig / cp949 가능성 모두 대응
                try:
                    df = pd.read_csv(io.BytesIO(raw), encoding="utf-8")
                except Exception:
                    try:
                        df = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
                    except Exception:
                        df = pd.read_csv(io.BytesIO(raw), encoding="cp949")
                return df, label

            if kind == "xlsx":
                df = pd.read_excel(io.BytesIO(raw), engine="openpyxl")
                return df, label

            errors.append(f"{label}: 파일 형식을 판별하지 못함")
        except Exception as e:
            errors.append(f"{label}: {e}")

    raise RuntimeError("음식점 원본 다운로드에 실패했습니다.\n" + "\n".join(errors))


def prepare_restaurants_if_needed():
    ensure_directories()

    if os.path.exists(RESTAURANT_PARQUET_PATH) or os.path.exists(RESTAURANT_CSV_PATH):
        return

    with st.spinner("음식점 원본 데이터를 내려받고 정리하는 중입니다..."):
        df, source_label = load_raw_restaurant_source()

        col_name = find_col(df, ["사업장명", "업소명", "업소명칭", "업소명(상호)"])
        col_addr = find_col(df, ["소재지전체주소", "지번주소", "주소"])
        col_road = find_col(df, ["도로명전체주소", "소재지도로명전체주소", "소재지도로명주소", "도로명주소"])
        col_x = find_col(df, ["좌표정보(X)", "좌표정보x(epsg5174)", "좌표정보x", "좌표정보(X좌표)", "X"])
        col_y = find_col(df, ["좌표정보(Y)", "좌표정보y(epsg5174)", "좌표정보y", "좌표정보(Y좌표)", "Y"])
        col_type = find_col(df, ["업태구분명", "위생업태명", "음식의유형", "주된음식종류"])
        col_phone = find_col(df, ["소재지전화", "전화번호"])
        col_status = find_col(df, ["영업상태명"])
        col_detail_status = find_col(df, ["상세영업상태명"])
        col_status_code = find_col(df, ["영업상태구분코드", "상세영업상태코드"])

        # 모범음식점 폴백은 위경도가 바로 있는 경우도 있음
        if col_x is None:
            col_x = find_col(df, ["경도"])
        if col_y is None:
            col_y = find_col(df, ["위도"])

        required = [col_name, col_addr or col_road, col_x, col_y]
        if any(c is None for c in required):
            raise ValueError(
                "원본 파일의 핵심 컬럼을 찾지 못했습니다.\n"
                f"name={col_name}, addr={col_addr}, road={col_road}, x={col_x}, y={col_y}"
            )

        work = df.copy()

        # 일반음식점이면 영업중만 필터
        if source_label.startswith("일반음식점"):
            if col_detail_status:
                work = work[work[col_detail_status].astype(str).str.contains("정상|영업", na=False)].copy()
            elif col_status:
                work = work[work[col_status].astype(str).str.contains("정상|영업", na=False)].copy()
            elif col_status_code:
                work = work[pd.to_numeric(work[col_status_code], errors="coerce").fillna(-1).isin([1])].copy()

        # 좌표 처리
        x_num = pd.to_numeric(work[col_x], errors="coerce")
        y_num = pd.to_numeric(work[col_y], errors="coerce")

        # 이미 위경도 형태면 그대로 사용
        if x_num.between(120, 135, inclusive="both").mean() > 0.7 and y_num.between(30, 40, inclusive="both").mean() > 0.7:
            lon = x_num
            lat = y_num
        else:
            lat, lon = transform_xy_to_wgs84(work[col_x], work[col_y])

        addr_series = work[col_road] if col_road else work[col_addr]
        addr_series = addr_series.where(addr_series.astype(str).str.strip() != "", work[col_addr] if col_addr else "")

        out = pd.DataFrame({
            "name": work[col_name].astype(str).fillna("").str.strip(),
            "address": work[col_addr].astype(str).fillna("").str.strip() if col_addr else "",
            "road_address": work[col_road].astype(str).fillna("").str.strip() if col_road else "",
            "lat": lat,
            "lon": lon,
            "food_category": work[col_type].astype(str).fillna("").str.strip() if col_type else "",
            "phone": work[col_phone].astype(str).fillna("").str.strip() if col_phone else "",
            "business_status": work[col_status].astype(str).fillna("").str.strip() if col_status else "",
            "detail_status": work[col_detail_status].astype(str).fillna("").str.strip() if col_detail_status else "",
        })

        out = out[
            out["lat"].between(30, 40, inclusive="both")
            & out["lon"].between(120, 135, inclusive="both")
        ].copy()

        base_addr = out["road_address"].where(out["road_address"].str.strip() != "", out["address"])
        parsed = base_addr.apply(parse_address_parts)
        out["sido"] = parsed.apply(lambda x: x[0])
        out["sigungu"] = parsed.apply(lambda x: x[1])
        out["emd"] = parsed.apply(lambda x: x[2])

        out["rating"] = pd.NA
        out["review_count"] = 0
        out["main_menu"] = ""
        out["summary"] = out.apply(build_summary, axis=1)
        out["parking"] = ""
        out["waiting"] = ""
        out["opening_hours"] = ""
        out["source"] = "지방행정인허가데이터개방 일반음식점" if source_label.startswith("일반음식점") else "전국모범음식점표준데이터"
        out["naver_map_url"] = out.apply(
            lambda r: make_naver_map_search_url(f"{r['name']} {r['road_address'] or r['address']}"),
            axis=1
        )

        out = out.drop_duplicates(subset=["name", "road_address", "address", "lat", "lon"]).copy()

        for c in [
            "name", "sido", "sigungu", "emd", "address", "road_address", "food_category",
            "main_menu", "summary", "parking", "waiting", "opening_hours", "phone",
            "source", "naver_map_url"
        ]:
            out[c] = out[c].astype(str).fillna("").str.strip()

        out["review_count"] = 0

        out.to_csv(RESTAURANT_CSV_PATH, index=False, encoding="utf-8-sig")
        out.to_parquet(RESTAURANT_PARQUET_PATH, index=False)


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
        raise FileNotFoundError("음식점 데이터 파일 생성에 실패했습니다.")

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

    return df


# =========================================================
# 초기 준비
# =========================================================
try:
    ensure_geojson_files()
    prepare_restaurants_if_needed()
except Exception as e:
    st.error(f"초기 데이터 준비 중 오류가 발생했습니다:\n\n{e}")
    st.stop()

# =========================================================
# 데이터 로딩
# =========================================================
try:
    sido_geo = load_geojson(SIDO_GEO_PATH)
    sigungu_geo = load_geojson(SIGUNGU_GEO_PATH)
    emd_geo = load_geojson(EMD_GEO_PATH)
    restaurant_df = load_restaurants()
except Exception as e:
    st.error(f"데이터 로딩 중 오류가 발생했습니다:\n\n{e}")
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
max_results = st.sidebar.slider("최대 표시 개수", 30, 300, 120, 10)

st.sidebar.info("일반음식점 전체 다운로드가 실패하면 모범음식점 데이터로 자동 대체됩니다.")

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

    return filtered.copy()

filtered_df = filter_restaurants_cached(
    restaurant_df,
    st.session_state.selected_sido,
    st.session_state.selected_sigungu,
    st.session_state.selected_emd,
    food_type,
    search_keyword,
).sort_values(["name"], ascending=[True])

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

    GeoJson(
        geojson_to_show,
        name=f"{display_label} 경계",
        style_function=lambda _f: {
            "fillColor": "#4F8BF9",
            "color": "#1E3A8A",
            "weight": 1.2,
            "fillOpacity": 0.18,
        },
        highlight_function=lambda _f: {
            "fillColor": "#2563EB",
            "color": "#0F172A",
            "weight": 2.0,
            "fillOpacity": 0.32,
        },
        tooltip=GeoJsonTooltip(
            fields=["_display_name"],
            aliases=[f"{display_label}:"],
            sticky=True,
            labels=True,
            style="background-color: white; color: #111827; font-size: 13px; padding: 8px; border-radius: 6px;",
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

        popup_html = f"""
        <div style="width: 340px; font-family: Arial, sans-serif; line-height: 1.55;">
            <h4 style="margin: 0 0 8px 0;">{row['name']}</h4>
            <div><b>행정구역</b>: {row['sido']} {row['sigungu']} {row['emd']}</div>
            <div><b>주소</b>: {road_address}</div>
            <div><b>음식 유형</b>: {row['food_category'] if normalize_str(row['food_category']) else '정보 없음'}</div>
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

        folium.Marker(
            location=[row["lat"], row["lon"]],
            tooltip=f"{row['name']} | {row['food_category']}",
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
        show_cols = ["name", "food_category", "sido", "sigungu", "emd", "source"]
        st.dataframe(filtered_df[show_cols], use_container_width=True, height=260)

        for i, (_, row) in enumerate(filtered_df.head(12).iterrows(), start=1):
            with st.expander(f"{i}. {row['name']}"):
                st.markdown(f"**행정구역**: {row['sido']} {row['sigungu']} {row['emd']}")
                st.markdown(f"**주소**: {row['road_address'] if normalize_str(row['road_address']) else row['address']}")
                st.markdown(f"**음식 유형**: {row['food_category'] if normalize_str(row['food_category']) else '정보 없음'}")
                st.markdown(f"**설명**: {row['summary'] if normalize_str(row['summary']) else '정보 없음'}")
                st.markdown(f"**전화번호**: {row['phone'] if normalize_str(row['phone']) else '정보 없음'}")
                st.markdown(f"**출처**: {row['source']}")
                st.markdown(f"[네이버 지도에서 보기]({row['naver_map_url']})")
