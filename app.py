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
    padding-top: 2.4rem;
    padding-bottom: 2rem;
}
.main-title {
    font-size: 2.3rem;
    font-weight: 800;
    color: #0f172a;
    margin-top: 0.2rem;
    margin-bottom: 0.35rem;
    letter-spacing: -0.03em;
    line-height: 1.25;
}
.sub-title {
    color: #475569;
    font-size: 1.02rem;
    margin-bottom: 1.2rem;
    line-height: 1.7;
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
st.markdown(
    '<div class="sub-title">대한민국의 시도, 시군구, 읍면동 단위로 행정구역을 단계적으로 탐색하면서 지역별 맛집 정보를 한눈에 확인할 수 있도록 만든 서비스입니다. 음식 유형, 평점, 키워드 검색을 통해 원하는 식당을 빠르게 찾고, 네이버 지도·구글 지도·예약 플랫폼 검색 링크까지 함께 확인할 수 있습니다.</div>',
    unsafe_allow_html=True
)

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

# =========================================================
# 누락되었던 함수: load_geojson
# =========================================================
@st.cache_data(show_spinner=False)
def load_geojson(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
