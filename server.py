import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

app = FastAPI(title="Football Live")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "https://api.football-data.org/v4"
TZ = ZoneInfo("Asia/Tehran")
TOKEN = (
    os.getenv("FOOTBALL_DATA_TOKEN", "").strip()
    or os.getenv("API_TOKEN", "").strip()
    or os.getenv("FOOTBALL_API_KEY", "").strip()
)

COMPETITIONS = [
    {"code": "PL", "name": "لیگ برتر انگلیس"},
    {"code": "ELC", "name": "چمپیونشیپ انگلیس"},
    {"code": "PD", "name": "لالیگا اسپانیا"},
    {"code": "BL1", "name": "بوندس‌لیگا آلمان"},
    {"code": "SA", "name": "سری آ ایتالیا"},
    {"code": "FL1", "name": "لیگ فرانسه"},
    {"code": "DED", "name": "اردیویسه هلند"},
    {"code": "PPL", "name": "لیگ پرتغال"},
    {"code": "CL", "name": "لیگ قهرمانان اروپا"},
    {"code": "BSA", "name": "سری آ برزیل"},
]

@app.get("/health")
async def health():
    return {"ok": True, "token_configured": bool(TOKEN)}

@app.get("/api/competitions")
async def competitions():
    return {"competitions": COMPETITIONS}

@app.get("/api/matches")
async def matches(
    dateFrom: date = Query(...),
    dateTo: date = Query(...),
    competition: str = Query(default="ALL"),
):
    if not TOKEN:
        return {
            "error": "توکن فوتبال در تنظیمات Render ثبت نشده است (FOOTBALL_DATA_TOKEN).",
            "matches": [],
        }
    if dateTo < dateFrom:
        return {"error": "تاریخ پایان نامعتبر است.", "matches": []}

    params = {
        "dateFrom": dateFrom.isoformat(),
        # Send the next day as the exclusive upper boundary.
        "dateTo": (dateTo + timedelta(days=1)).isoformat(),
    }
    if competition and competition.upper() != "ALL":
        params["competitions"] = competition.upper()

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.get(
                f"{API}/matches",
                params=params,
                headers={"X-Auth-Token": TOKEN},
            )

        if response.status_code != 200:
            return {
                "error": f"خطای سرویس مسابقات (HTTP {response.status_code})",
                "details": response.text[:400],
                "matches": [],
            }

        matches_out = []
        for match in response.json().get("matches", []):
            competition_data = match.get("competition") or {}
            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}
            full_time = ((match.get("score") or {}).get("fullTime") or {})
            raw_date = match.get("utcDate")
            local_time = ""
            if raw_date:
                local_time = datetime.fromisoformat(
                    raw_date.replace("Z", "+00:00")
                ).astimezone(TZ).strftime("%H:%M")

            matches_out.append({
                "id": match.get("id"),
                "competition": competition_data.get("name", ""),
                "competitionCode": competition_data.get("code", ""),
                "homeTeam": home.get("name", "نامشخص"),
                "awayTeam": away.get("name", "نامشخص"),
                "localTime": local_time,
                "status": match.get("status", ""),
                "homeScore": full_time.get("home"),
                "awayScore": full_time.get("away"),
            })

        matches_out.sort(key=lambda item: item.get("localTime") or "")
        return {
            "ok": True,
            "matches": matches_out,
            "count": len(matches_out),
            "from": dateFrom.isoformat(),
            "to": dateTo.isoformat(),
            "timezone": "Asia/Tehran",
        }
    except httpx.RequestError:
        return {"error": "ارتباط با سرویس مسابقات برقرار نشد.", "matches": []}

@app.get("/", response_class=HTMLResponse)
async def home():
    path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(path, encoding="utf-8") as file:
        return file.read()
