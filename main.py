"""
Korean Data API - 배포용 최소 버전
핸드폰 + Railway/Render 배포에 최적화
"""

import os
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings

# ---------- 설정 ----------
class Settings(BaseSettings):
    data_go_kr_service_key: Optional[str] = None
    port: int = 8000

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# ---------- 캐시 (메모리) ----------
_cache: dict[str, tuple[Any, datetime]] = {}

def cache_get(key: str, minutes: int = 20) -> Any | None:
    item = _cache.get(key)
    if not item:
        return None
    value, expires = item
    if datetime.now() > expires:
        _cache.pop(key, None)
        return None
    return value

def cache_set(key: str, value: Any, minutes: int = 20):
    _cache[key] = (value, datetime.now() + timedelta(minutes=minutes))

# ---------- 데이터 수집 ----------
async def fetch_air_quality(sido: str = "서울") -> dict:
    """시도별 실시간 미세먼지"""
    key = f"air:{sido}"
    cached = cache_get(key)
    if cached:
        return cached

    service_key = settings.data_go_kr_service_key or os.getenv("DATA_GO_KR_SERVICE_KEY")
    if not service_key:
        return {
            "error": "DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다",
            "hint": "환경변수에 공공데이터 서비스키를 넣어주세요",
        }

    url = "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty"
    params = {
        "serviceKey": service_key,
        "returnType": "json",
        "numOfRows": "50",
        "pageNo": "1",
        "sidoName": sido,
        "ver": "1.0",
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()

        items = data["response"]["body"]["items"]
        result = {
            "sido": sido,
            "count": len(items),
            "updated": datetime.now().isoformat(),
            "stations": [
                {
                    "station": i.get("stationName"),
                    "pm10": i.get("pm10Value"),
                    "pm25": i.get("pm25Value"),
                    "khai": i.get("khaiValue"),
                    "grade": i.get("khaiGrade"),
                    "time": i.get("dataTime"),
                }
                for i in items[:15]
            ],
        }
        cache_set(key, result)
        return result
    except Exception as e:
        return {"error": str(e), "sido": sido}

# ---------- FastAPI ----------
app = FastAPI(
    title="Korean Data API",
    description="한국 공공데이터 (미세먼지 등) 간단 API",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "service": "Korean Data API",
        "status": "ok",
        "docs": "/docs",
        "endpoints": {
            "air_quality": "/air-quality?sido=서울",
            "health": "/health",
        },
    }

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.get("/air-quality")
async def air_quality(sido: str = Query("서울", description="시도명 (서울, 부산, 경기 등)")):
    """시도별 실시간 미세먼지 조회"""
    return await fetch_air_quality(sido)

# Railway / Render용 엔트리포인트
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", settings.port))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
