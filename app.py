import os
import json
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

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

# =========================================================
# 모던 스타일
# =========================================================
st.markdown("""
<style>
html, body, [class*="css"] {
    font-family: "Pretendard", "Noto Sans KR", sans-serif;
}
.stApp {
    background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
}
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
}
.main-title {
    font-size: 2.1rem;
    font-weight: 800;
    color: #0f172a;
    margin-bottom: 0.2rem;
    letter-spacing: -0.03em;
}
.sub-title {
    color: #475569;
    font-size: 0.98rem;
    margin-bottom: 1rem;
}
.glass-card {
    background: rgba(255,255,255,0.88);
    border: 1px solid rgba(226,232,240,0.95);
    border-radius: 22px;
    padding: 18px 18px 14px 18px;
    box-shadow: 0 8px 30px rgba(15,23,42,0.06);
    margin-bottom: 12px;
}
[data-testid="stMetric"] {
    background: rgba(255,255,255,0.92);
    border: 1px solid #e2e8f0;
    padding: 12px 14px;
    border-radius: 18px;
    box-shadow: 0 6px 20px rgba(15,23,42,0.04);
}
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
    border-right: 1px solid #e2e8f0;
}
.stDataFrame, .stTable {
    border-radius: 16px;
    overflow: hidden;
}
div[data-testid="stExpander"] {
    border-radius: 16px !important;
    border: 1px solid #e2e8f0 !important;
    background: rgba(255,255,255,0.88);
}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🍽 대한민국 맛집 지도</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">행정구역 드릴다운 + 로컬 내장형 스타터 맛집 데이터 + 모던 UI</div>', unsafe_allow_html=True)

# =========================================================
# 경로 / URL
# =========================================================
DATA_DIR = "data"
GEO_DIR = os.path.join(DATA_DIR, "geo")
REST_DIR = os.path.join(DATA_DIR, "restaurants")

SIDO_GEO_PATH = os.path.join(GEO_DIR, "sido.geojson")
SIGUNGU_GEO_PATH = os.path.join(GEO_DIR, "sigungu.geojson")
EMD_GEO_PATH = os.path.join(GEO_DIR, "emd.geojson")

RESTAURANT_PARQUET_PATH = os.path.join(REST_DIR, "starter_restaurants_v2.parquet")
RESTAURANT_CSV_PATH = os.path.join(REST_DIR, "starter_restaurants_v2.csv")

SIDO_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-provinces-geo.json"
SIGUNGU_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-municipalities-geo.json"
EMD_URL = "https://raw.githubusercontent.com/vuski/admdongkor/master/ver20220101/HangJeongDong_ver20220101.geojson"

KOREA_CENTER = [36.35, 127.95]
DEFAULT_ZOOM = 7

MAX_MARKERS_SIDO = 140
MAX_MARKERS_SIGUNGU = 260
MAX_MARKERS_EMD = 420

FOOD_TYPES = [
    "전체", "한식", "중식", "일식", "양식", "분식", "카페", "카페/디저트",
    "치킨", "피자", "고기", "구이", "국밥", "탕", "찌개", "면요리",
    "해산물", "술집", "이자카야", "비건", "기타"
]

# =========================================================
# 행정구역 시드
# =========================================================
REGION_SEEDS = {
    "서울특별시": {
        "center": (37.5665, 126.9780),
        "sigungu": {
            "강남구": ["역삼동", "논현동", "청담동", "삼성동", "대치동", "신사동"],
            "중구": ["명동", "을지로", "주교동", "신당동", "장충동", "충무로"],
            "마포구": ["합정동", "서교동", "연남동", "상수동", "공덕동", "망원동"],
            "송파구": ["잠실동", "석촌동", "문정동", "방이동", "가락동", "송리단길"],
            "성동구": ["성수동", "행당동", "금호동", "왕십리", "옥수동", "송정동"],
            "용산구": ["이태원동", "한남동", "보광동", "효창동", "용문동", "남영동"],
            "종로구": ["익선동", "삼청동", "서촌", "종로1가", "평창동", "부암동"],
            "서초구": ["서초동", "반포동", "방배동", "잠원동", "양재동", "내곡동"],
        },
    },
    "부산광역시": {
        "center": (35.1796, 129.0756),
        "sigungu": {
            "해운대구": ["우동", "중동", "좌동", "송정동", "재송동", "달맞이길"],
            "수영구": ["광안동", "민락동", "남천동", "망미동", "수영동", "광안리"],
            "부산진구": ["전포동", "부전동", "범천동", "가야동", "당감동", "서면"],
            "중구": ["남포동", "광복동", "보수동", "영주동", "대청동", "자갈치"],
            "동래구": ["명륜동", "사직동", "온천동", "안락동", "복천동", "수안동"],
        },
    },
    "대구광역시": {
        "center": (35.8714, 128.6014),
        "sigungu": {
            "중구": ["동성로", "삼덕동", "대봉동", "남산동", "동인동", "교동"],
            "수성구": ["범어동", "수성동", "두산동", "만촌동", "황금동", "지산동"],
            "달서구": ["상인동", "월성동", "죽전동", "감삼동", "성당동", "이곡동"],
            "북구": ["칠곡", "침산동", "태전동", "동천동", "학정동", "산격동"],
        },
    },
    "인천광역시": {
        "center": (37.4563, 126.7052),
        "sigungu": {
            "연수구": ["송도동", "연수동", "동춘동", "옥련동", "청학동", "선학동"],
            "남동구": ["구월동", "간석동", "논현동", "서창동", "만수동", "장수동"],
            "부평구": ["부평동", "삼산동", "갈산동", "청천동", "산곡동", "십정동"],
            "미추홀구": ["주안동", "용현동", "숭의동", "도화동", "관교동", "학익동"],
        },
    },
    "광주광역시": {
        "center": (35.1595, 126.8526),
        "sigungu": {
            "서구": ["치평동", "상무동", "금호동", "쌍촌동", "풍암동", "화정동"],
            "동구": ["충장로", "학동", "산수동", "지산동", "계림동", "서석동"],
            "북구": ["용봉동", "운암동", "문흥동", "오치동", "매곡동", "두암동"],
            "광산구": ["수완동", "첨단", "월곡동", "우산동", "신창동", "장덕동"],
        },
    },
    "대전광역시": {
        "center": (36.3504, 127.3845),
        "sigungu": {
            "유성구": ["봉명동", "궁동", "장대동", "도룡동", "전민동", "어은동"],
            "서구": ["둔산동", "탄방동", "월평동", "도안동", "갈마동", "관저동"],
            "중구": ["은행동", "대흥동", "선화동", "유천동", "오류동", "문화동"],
        },
    },
    "울산광역시": {
        "center": (35.5384, 129.3114),
        "sigungu": {
            "남구": ["삼산동", "달동", "신정동", "옥동", "무거동", "야음동"],
            "중구": ["성남동", "우정동", "반구동", "학성동", "복산동", "태화동"],
            "북구": ["매곡동", "천곡동", "호계동", "송정동", "염포동", "진장동"],
        },
    },
    "세종특별자치시": {
        "center": (36.4800, 127.2890),
        "sigungu": {
            "세종특별자치시": ["나성동", "어진동", "도담동", "새롬동", "보람동", "소담동", "종촌동"],
        },
    },
    "경기도": {
        "center": (37.4138, 127.5183),
        "sigungu": {
            "수원시": ["영통동", "인계동", "매탄동", "광교", "권선동", "행궁동"],
            "성남시": ["정자동", "서현동", "야탑동", "판교", "분당", "모란"],
            "고양시": ["일산", "백석동", "정발산", "화정동", "주엽동", "삼송동"],
            "용인시": ["수지", "죽전", "기흥", "동백", "보정동", "상현동"],
            "부천시": ["상동", "중동", "신중동", "송내", "역곡동", "옥길동"],
            "안양시": ["범계", "평촌", "인덕원", "안양1동", "호계동", "관양동"],
            "화성시": ["동탄", "병점", "봉담", "향남", "남양", "송산"],
            "남양주시": ["다산", "별내", "호평동", "평내동", "덕소", "진접"],
        },
    },
    "강원특별자치도": {
        "center": (37.8228, 128.1555),
        "sigungu": {
            "춘천시": ["퇴계동", "석사동", "후평동", "효자동", "온의동", "소양로"],
            "강릉시": ["안목", "교동", "포남동", "유천동", "입암동", "경포"],
            "원주시": ["무실동", "단계동", "반곡동", "명륜동", "단구동", "혁신도시"],
            "속초시": ["조양동", "교동", "영랑동", "청초호", "대포항", "장사항"],
        },
    },
    "충청북도": {
        "center": (36.6357, 127.4917),
        "sigungu": {
            "청주시": ["복대동", "율량동", "가경동", "오창", "산남동", "성안길"],
            "충주시": ["연수동", "칠금동", "문화동", "호암동", "성서동", "교현동"],
            "제천시": ["하소동", "청전동", "장락동", "중앙로", "영천동", "고암동"],
        },
    },
    "충청남도": {
        "center": (36.6588, 126.6728),
        "sigungu": {
            "천안시": ["불당동", "두정동", "신부동", "청당동", "쌍용동", "백석동"],
            "아산시": ["탕정", "배방", "온천동", "모종동", "권곡동", "신정호"],
            "공주시": ["신관동", "중동", "산성동", "금성동", "월송동", "옥룡동"],
        },
    },
    "전북특별자치도": {
        "center": (35.7175, 127.1530),
        "sigungu": {
            "전주시": ["객사", "효자동", "혁신도시", "송천동", "중화산동", "한옥마을"],
            "군산시": ["수송동", "나운동", "조촌동", "영동", "미장동", "선유도"],
            "익산시": ["영등동", "모현동", "부송동", "어양동", "신동", "창인동"],
        },
    },
    "전라남도": {
        "center": (34.8161, 126.4630),
        "sigungu": {
            "여수시": ["학동", "웅천", "여서동", "소호동", "교동", "돌산"],
            "목포시": ["상동", "하당", "평화광장", "옥암동", "용해동", "북항"],
            "순천시": ["연향동", "조례동", "왕지동", "신대지구", "장천동", "해룡면"],
            "나주시": ["빛가람동", "성북동", "남평읍", "영강동", "송월동", "이창동"],
        },
    },
    "경상북도": {
        "center": (36.4919, 128.8889),
        "sigungu": {
            "포항시": ["영일대", "이동", "죽도동", "효자동", "장성동", "구룡포"],
            "경주시": ["황리단길", "성건동", "동천동", "용강동", "보문단지", "불국동"],
            "구미시": ["형곡동", "옥계동", "송정동", "인동", "진평동", "원평동"],
            "안동시": ["옥동", "정하동", "송현동", "태화동", "남문동", "용상동"],
        },
    },
    "경상남도": {
        "center": (35.4606, 128.2132),
        "sigungu": {
            "창원시": ["상남동", "용호동", "가로수길", "합성동", "중앙동", "상남시장"],
            "김해시": ["장유", "내동", "율하", "삼계동", "구산동", "봉황동"],
            "진주시": ["평거동", "충무공동", "상대동", "초전동", "하대동", "중앙시장"],
            "양산시": ["물금", "증산", "중부동", "덕계동", "서창", "평산동"],
        },
    },
    "제주특별자치도": {
        "center": (33.4996, 126.5312),
        "sigungu": {
            "제주시": ["연동", "노형동", "애월", "함덕", "이도동", "한림", "구좌"],
            "서귀포시": ["중문", "서귀동", "성산", "표선", "대정", "안덕", "남원"],
        },
    },
}

CATEGORY_TEMPLATES = {
    "한식": ["한상차림", "백반집", "정식당", "한식당", "밥상"],
    "중식": ["중화요리", "반점", "중국관", "마라관", "중식당"],
    "일식": ["스시", "이자카야", "라멘", "우동", "덮밥집"],
    "양식": ["비스트로", "파스타", "브런치", "스테이크", "그릴"],
    "분식": ["떡볶이", "김밥", "분식집", "라볶이", "포차분식"],
    "카페": ["로스터스", "커피랩", "브루잉", "카페", "커피하우스"],
    "카페/디저트": ["디저트랩", "베이커리", "파티세리", "케이크샵", "스위츠"],
    "치킨": ["치킨", "통닭", "닭강정", "후라이드", "옛날통닭"],
    "피자": ["피자", "화덕피자", "피제리아", "슬라이스", "피자하우스"],
    "고기": ["고깃집", "갈비", "삼겹살", "숯불구이", "정육식당"],
    "구이": ["구이집", "화로", "직화구이", "참숯", "바베큐"],
    "국밥": ["국밥", "돼지국밥", "순대국", "해장국", "곰탕"],
    "탕": ["탕집", "감자탕", "설렁탕", "갈비탕", "추어탕"],
    "찌개": ["찌개집", "김치찌개", "된장찌개", "부대찌개", "두루치기"],
    "면요리": ["칼국수", "냉면", "국수", "라멘", "우동"],
    "해산물": ["횟집", "해물탕", "조개구이", "초밥", "해산물식당"],
    "술집": ["포차", "주점", "맥주집", "펍", "와인바"],
    "이자카야": ["이자카야", "사카바", "오뎅바", "야키토리", "사시미"],
    "비건": ["비건키친", "샐러드", "플랜트", "그린테이블", "채식당"],
    "기타": ["맛집", "레스토랑", "다이닝", "푸드하우스", "키친"],
}

MAIN_MENU_MAP = {
    "한식": "제육볶음, 된장찌개, 백반",
    "중식": "짜장면, 짬뽕, 탕수육",
    "일식": "초밥, 사시미, 라멘",
    "양식": "파스타, 스테이크, 리조또",
    "분식": "떡볶이, 순대, 김밥",
    "카페": "아메리카노, 라떼, 핸드드립",
    "카페/디저트": "케이크, 크로플, 마카롱",
    "치킨": "후라이드, 양념치킨",
    "피자": "화덕피자, 페퍼로니피자",
    "고기": "삼겹살, 목살, 갈비",
    "구이": "생선구이, 고기구이",
    "국밥": "돼지국밥, 순대국밥",
    "탕": "갈비탕, 감자탕",
    "찌개": "김치찌개, 부대찌개",
    "면요리": "냉면, 칼국수, 우동",
    "해산물": "회, 해물탕, 조개찜",
    "술집": "안주, 하이볼, 맥주",
    "이자카야": "꼬치, 사시미, 나베",
    "비건": "샐러드, 비건볼, 파스타",
    "기타": "대표 메뉴 정보 확인 필요",
}

STREET_SUFFIXES = ["1길", "2길", "3길", "5길", "7길", "9길", "중앙로", "로데오길", "먹자골목", "번화로"]

# =========================================================
# 유틸
# =========================================================
def ensure_directories():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(GEO_DIR, exist_ok=True)
    os.makedirs(REST_DIR, exist_ok=True)


def download_file(url: str, path: str, timeout: int = 180):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    with open(path, "wb") as f:
        f.write(response.content)


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
            download_file(url, path)


def region_offset(base_lat: float, base_lon: float, idx: int) -> Tuple[float, float]:
    lat = base_lat + ((idx % 9) - 4) * 0.0028
    lon = base_lon + (((idx // 9) % 9) - 4) * 0.0033
    return lat, lon


def generate_restaurant_name(emd: str, category: str, idx: int) -> str:
    suffixes = CATEGORY_TEMPLATES.get(category, CATEGORY_TEMPLATES["기타"])
    return f"{emd} {suffixes[idx % len(suffixes)]}"


def generate_summary(category: str, emd: str, sigungu: str) -> str:
    return f"{sigungu} {emd}에서 {category} 메뉴를 찾는 분들이 많이 찾아볼 만한 곳"


def generate_korean_address(sido: str, sigungu: str, emd: str, idx: int) -> str:
    suffix = STREET_SUFFIXES[idx % len(STREET_SUFFIXES)]
    lot_main = 10 + (idx * 3) % 87
    lot_sub = 1 + (idx * 7) % 18
    if suffix in ["중앙로", "번화로"]:
        return f"{sido} {sigungu} {emd} {suffix} {lot_main}"
    if suffix == "먹자골목":
        return f"{sido} {sigungu} {emd} {suffix} {lot_main}-{lot_sub}"
    return f"{sido} {sigungu} {emd} {suffix} {lot_main}-{lot_sub}"


def make_naver_map_search_url(query: str) -> str:
    return f"https://map.naver.com/v5/search/{quote(query)}"


def make_google_map_search_url(query: str) -> str:
    return f"https://www.google.com/maps/search/{quote(query)}"


def make_catchtable_search_url(query: str) -> str:
    return f"https://www.catchtable.net/search?query={quote(query)}"


def make_tabling_search_url(query: str) -> str:
    return f"https://www.tabling.co.kr/search?query={quote(query)}"


def build_starter_dataframe() -> pd.DataFrame:
    rows = []
    categories_cycle = [
        "한식", "중식", "일식", "양식", "분식", "카페", "카페/디저트",
        "치킨", "피자", "고기", "구이", "국밥", "탕", "찌개", "면요리",
        "해산물", "술집", "이자카야", "비건"
    ]

    for sido, region_info in REGION_SEEDS.items():
        base_lat, base_lon = region_info["center"]

        for s_idx, (sigungu, emd_list) in enumerate(region_info["sigungu"].items()):
            sigungu_lat = base_lat + (s_idx - 3) * 0.022
            sigungu_lon = base_lon + (s_idx - 3) * 0.026

            for e_idx, emd in enumerate(emd_list):
                emd_lat = sigungu_lat + (e_idx - 3) * 0.006
                emd_lon = sigungu_lon + (e_idx - 3) * 0.007

                for i in range(10):
                    category = categories_cycle[(i + e_idx + s_idx) % len(categories_cycle)]
                    name = generate_restaurant_name(emd, category, i)
                    lat, lon = region_offset(emd_lat, emd_lon, i)
                    address = generate_korean_address(sido, sigungu, emd, i)
                    query = f"{name} {address}"
                    rating = round(3.6 + ((i + e_idx + s_idx) % 14) * 0.1, 1)
                    if rating > 4.9:
                        rating = 4.9
                    review_count = 30 + ((s_idx * 37 + e_idx * 19 + i * 17) % 620)

                    rows.append({
                        "name": name,
                        "sido": sido,
                        "sigungu": sigungu,
                        "emd": emd,
                        "address": address,
                        "road_address": address,
                        "lat": lat,
                        "lon": lon,
                        "food_category": category,
                        "rating": rating,
                        "review_count": review_count,
                        "main_menu": MAIN_MENU_MAP.get(category, "대표 메뉴 정보 확인 필요"),
                        "summary": generate_summary(category, emd, sigungu),
                        "parking": "가능성 있음" if i % 3 == 0 else "정보 확인 필요",
                        "waiting": "피크 시간 대기 가능" if i % 4 == 0 else "정보 확인 필요",
                        "opening_hours": "11:00 ~ 21:30",
                        "phone": "정보 확인 필요",
                        "source": "Local Starter Data v2",
                        "naver_map_url": make_naver_map_search_url(query),
                        "google_map_url": make_google_map_search_url(query),
                        "catchtable_url": make_catchtable_search_url(query),
                        "tabling_url": make_tabling_search_url(query),
                    })

    return pd.DataFrame(rows)


def prepare_restaurants_if_needed():
    ensure_directories()
    if os.path.exists(RESTAURANT_PARQUET_PATH) or os.path.exists(RESTAURANT_CSV_PATH):
        return

    with st.spinner("확장된 로컬 스타터 맛집 데이터를 생성하는 중입니다..."):
        df = build_starter_dataframe()
        df.to_csv(RESTAURANT_CSV_PATH, index=False, encoding="utf-8-sig")
        df.to_parquet(RESTAURANT_PARQUET_PATH, index=False)


@st.cache_data(show_spinner=False)
def load_restaurants() -> pd.DataFrame:
    if os.path.exists(RESTAURANT_PARQUET_PATH):
        df = pd.read_parquet(RESTAURANT_PARQUET_PATH)
    elif os.path.exists(RESTAURANT_CSV_PATH):
        df = pd.read_csv(RESTAURANT_CSV_PATH, encoding="utf-8")
    else:
        raise FileNotFoundError("스타터 음식점 데이터 파일 생성에 실패했습니다.")

    text_cols = [
        "name", "sido", "sigungu", "emd", "address", "road_address", "food_category",
        "main_menu", "summary", "parking", "waiting", "opening_hours", "phone",
        "source", "naver_map_url", "google_map_url", "catchtable_url", "tabling_url"
    ]
    for col in text_cols:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str).fillna("")

    for col in ["lat", "lon", "rating"]:
        if col not in df.columns:
            df[col] = None
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "review_count" not in df.columns:
        df["review_count"] = 0
    df["review_count"] = pd.to_numeric(df["review_count"], errors="coerce").fillna(0).astype(int)

    df = df.dropna(subset=["lat", "lon"]).copy()
    df["sort_score"] = df["rating"].fillna(0) * 1000 + df["review_count"]
    return df

# =========================================================
# GeoJSON/행정구역 유틸
# =========================================================
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

# =========================================================
# 초기 준비
# =========================================================
try:
    ensure_geojson_files()
    prepare_restaurants_if_needed()
except Exception as e:
    st.error(f"초기 데이터 준비 중 오류가 발생했습니다:\n\n{e}")
    st.stop()

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
    "도 / 특별시 / 광역시",
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
    "시 / 군 / 구",
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
    "읍 / 면 / 동",
    emd_options,
    index=0 if not st.session_state.selected_emd or st.session_state.selected_emd not in emd_options else emd_options.index(st.session_state.selected_emd),
)

food_type = st.sidebar.selectbox("음식 유형", FOOD_TYPES, index=0)
search_keyword = st.sidebar.text_input("검색어", placeholder="예: 냉면, 브런치, 곰탕, 디저트")
min_rating = st.sidebar.slider("최소 평점", 0.0, 5.0, 3.7, 0.1)
max_results = st.sidebar.slider("최대 표시 개수", 20, 300, 120, 10)

st.session_state.selected_sido = "" if selected_sido == "전체" else selected_sido
st.session_state.selected_sigungu = "" if selected_sigungu == "전체" else selected_sigungu
st.session_state.selected_emd = "" if selected_emd == "전체" else selected_emd

# =========================================================
# 현재 레벨 / 지도 범위
# =========================================================
def current_level() -> str:
    if st.session_state.selected_emd:
        return "emd"
    if st.session_state.selected_sigungu:
        return "sigungu"
    if st.session_state.selected_sido:
        return "sido_detail"
    return "sido"


def get_display_features() -> Tuple[List[Dict[str, Any]], str]:
    level = current_level()

    if level == "sido":
        return sido_features, "도/시도"

    if level == "sido_detail":
        filtered = [f for f in sigungu_features if contains_name(f["properties"], st.session_state.selected_sido)]
        return filtered if filtered else sido_features, "시/군/구"

    if level == "sigungu":
        filtered = [f for f in emd_features if contains_name(f["properties"], st.session_state.selected_sigungu)]
        return filtered if filtered else sigungu_features, "읍/면/동"

    if level == "emd":
        filtered = [f for f in emd_features if f["properties"].get("_display_name") == st.session_state.selected_emd]
        return filtered if filtered else emd_features, "읍/면/동"

    return sido_features, "도/시도"


display_features, display_label = get_display_features()
level = current_level()

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
# 필터링
# =========================================================
@st.cache_data(show_spinner=False)
def filter_restaurants_cached(
    df: pd.DataFrame,
    sido: str,
    sigungu: str,
    emd: str,
    food_type: str,
    search_keyword: str,
    min_rating: float,
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
            filtered["road_address"].astype(str) + " " +
            filtered["main_menu"].astype(str)
        )
        filtered = filtered[combined.str.contains(k, case=False, na=False)]

    filtered = filtered[filtered["rating"].fillna(0) >= min_rating]
    return filtered.copy()


filtered_df = filter_restaurants_cached(
    restaurant_df,
    st.session_state.selected_sido,
    st.session_state.selected_sigungu,
    st.session_state.selected_emd,
    food_type,
    search_keyword,
    min_rating,
).sort_values(["sort_score", "name"], ascending=[False, True])

if level == "sido":
    marker_limit = min(max_results, MAX_MARKERS_SIDO)
elif level == "sido_detail":
    marker_limit = min(max_results, MAX_MARKERS_SIGUNGU)
else:
    marker_limit = min(max_results, MAX_MARKERS_EMD)

map_df = filtered_df.head(marker_limit).copy()

# =========================================================
# 상단 요약
# =========================================================
st.markdown('<div class="glass-card">', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
c1.metric("검색 결과", f"{len(filtered_df):,}")
c2.metric("지도 마커", f"{len(map_df):,}")
c3.metric("도/시도", st.session_state.selected_sido or "전체")
c4.metric("시/군/구", st.session_state.selected_sigungu or "전체")
st.markdown('</div>', unsafe_allow_html=True)

# =========================================================
# 본문
# =========================================================
left_col, right_col = st.columns([1.9, 1.0])

with left_col:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)

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
            "fillColor": "#6366f1",
            "color": "#3730a3",
            "weight": 1.2,
            "fillOpacity": 0.16,
        },
        highlight_function=lambda _f: {
            "fillColor": "#4f46e5",
            "color": "#1e1b4b",
            "weight": 2.0,
            "fillOpacity": 0.30,
        },
        tooltip=GeoJsonTooltip(
            fields=["_display_name"],
            aliases=[f"{display_label}:"],
            sticky=True,
            labels=True,
            style="background-color: white; color: #111827; font-size: 13px; padding: 8px; border-radius: 8px;",
        ),
        popup=GeoJsonPopup(
            fields=["_display_name", "_display_code"],
            aliases=[f"{display_label}명", "행정코드"],
            labels=True,
            style="background-color: white; color: #111827; font-size: 13px; padding: 10px;",
        ),
    ).add_to(m)

    if not map_df.empty:
        for _, row in map_df.iterrows():
            popup_html = f"""
            <div style="width: 360px; font-family: Arial, sans-serif; line-height: 1.55;">
                <h4 style="margin: 0 0 8px 0;">{row['name']}</h4>
                <div><b>행정구역</b>: {row['sido']} {row['sigungu']} {row['emd']}</div>
                <div><b>주소</b>: {row['road_address']}</div>
                <div><b>음식 유형</b>: {row['food_category']}</div>
                <div><b>평점</b>: {row['rating']}</div>
                <div><b>리뷰 수</b>: {row['review_count']}</div>
                <div><b>대표 메뉴</b>: {row['main_menu']}</div>
                <div><b>요약</b>: {row['summary']}</div>
                <div><b>주차</b>: {row['parking']}</div>
                <div><b>웨이팅</b>: {row['waiting']}</div>
                <div><b>영업시간</b>: {row['opening_hours']}</div>
                <hr style="margin: 10px 0;">
                <div><a href="{row['naver_map_url']}" target="_blank">네이버 지도 검색</a></div>
                <div><a href="{row['google_map_url']}" target="_blank">구글 지도 검색</a></div>
                <div><a href="{row['catchtable_url']}" target="_blank">캐치테이블 검색</a></div>
                <div><a href="{row['tabling_url']}" target="_blank">테이블링 검색</a></div>
            </div>
            """

            folium.Marker(
                location=[row["lat"], row["lon"]],
                tooltip=f"{row['name']} | {row['food_category']} | {row['rating']}",
                popup=folium.Popup(popup_html, max_width=410),
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
    st.markdown('</div>', unsafe_allow_html=True)

    clicked_name = try_get_clicked_name(map_data)

    if clicked_name:
        if clicked_name in sido_options:
            st.session_state.selected_sido = clicked_name
            st.session_state.selected_sigungu = ""
            st.session_state.selected_emd = ""
            st.rerun()
        elif clicked_name in sigungu_options:
            st.session_state.selected_sigungu = clicked_name
            st.session_state.selected_emd = ""
            st.rerun()
        elif clicked_name in emd_options:
            st.session_state.selected_emd = clicked_name
            st.rerun()

with right_col:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("📍 현재 탐색 단계")
    st.write(f"**도/시도**: {st.session_state.selected_sido or '전체'}")
    st.write(f"**시/군/구**: {st.session_state.selected_sigungu or '전체'}")
    st.write(f"**읍/면/동**: {st.session_state.selected_emd or '전체'}")
    st.write(f"**음식 유형**: {food_type}")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("🍴 식당 목록")

    if filtered_df.empty:
        st.info("현재 조건에 맞는 식당이 없습니다.")
    else:
        show_cols = ["name", "food_category", "rating", "review_count", "sido", "sigungu", "emd"]
        st.dataframe(filtered_df[show_cols].head(150), use_container_width=True, height=280)

        for i, (_, row) in enumerate(filtered_df.head(12).iterrows(), start=1):
            with st.expander(f"{i}. {row['name']}"):
                st.markdown(f"**행정구역**: {row['sido']} {row['sigungu']} {row['emd']}")
                st.markdown(f"**주소**: {row['road_address']}")
                st.markdown(f"**음식 유형**: {row['food_category']}")
                st.markdown(f"**평점**: {row['rating']}")
                st.markdown(f"**리뷰 수**: {row['review_count']}")
                st.markdown(f"**대표 메뉴**: {row['main_menu']}")
                st.markdown(f"**설명**: {row['summary']}")
                st.markdown(f"**주차**: {row['parking']}")
                st.markdown(f"**웨이팅**: {row['waiting']}")
                st.markdown(f"[네이버 지도 검색]({row['naver_map_url']})")
                st.markdown(f"[구글 지도 검색]({row['google_map_url']})")
                st.markdown(f"[캐치테이블 검색]({row['catchtable_url']})")
                st.markdown(f"[테이블링 검색]({row['tabling_url']})")
    st.markdown('</div>', unsafe_allow_html=True)
