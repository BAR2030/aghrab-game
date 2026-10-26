import os
from datetime import date, timedelta
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI(title="Football Live API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_URL = "https://api.football-data.org/v4"

COMPETITIONS = {
    "PL": "لیگ برتر انگلیس",
    "ELC": "چمپیونشیپ انگلیس",
    "PD": "لالیگای اسپانیا",
    "BL1": "بوندسلیگای آلمان",
    "SA": "سری آ ایتالیا",
    "FL1": "لیگ فرانسه",
    "DED": "اردیویسه هلند",
    "PPL": "لیگ پرتغال",
    "CL": "لیگ قهرمانان اروپا",
    "BSA": "سری آ برزیل",
}


def get_token():
    return (
        os.getenv("FOOTBALL_DATA_TOKEN")
        or os.getenv("API_TOKEN")
        or os.getenv("FOOTBALL_API_KEY")
    )


@app.get("/health")
def health():
    return {
        "ok": True,
        "token_configured": bool(get_token()),
    }


@app.get("/api/competitions")
def competitions():
    return {
        "competitions": [
            {"code": code, "name": name}
            for code, name in COMPETITIONS.items()
        ]
    }


@app.get("/api/matches")
def matches(
    dateFrom: date = Query(default=None),
    dateTo: date = Query(default=None),
    competition: str = Query(default=None),
):
    token = get_token()

    if not token:
        return {
            "ok": False,
            "error": "API token is not configured on the server",
            "matches": [],
        }

    start = dateFrom or date.today()
    end = dateTo or start

    if end < start:
        return {
            "ok": False,
            "error": "تاریخ پایان نباید قبل از تاریخ شروع باشد",
            "matches": [],
        }

    # football-data.org treats dateTo as inclusive for our requested range
    # by passing the following day as the exclusive boundary.
    params = {
        "dateFrom": start.isoformat(),
        "dateTo": (end + timedelta(days=1)).isoformat(),
    }

    codes = (
        [competition.upper()]
        if competition and competition.upper() in COMPETITIONS
        else list(COMPETITIONS.keys())
    )
    params["competitions"] = ",".join(codes)

    try:
        response = requests.get(
            f"{API_URL}/matches",
            headers={"X-Auth-Token": token},
            params=params,
            timeout=25,
        )

        if response.status_code != 200:
            return {
                "ok": False,
                "error": f"Football API error: {response.status_code}",
                "details": response.text[:500],
                "matches": [],
            }

        data = response.json()
        results = []

        for match in data.get("matches", []):
            comp = match.get("competition") or {}
            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}
            score = match.get("score") or {}
            full_time = score.get("fullTime") or {}

            results.append({
                "id": match.get("id"),
                "utcDate": match.get("utcDate"),
                "status": match.get("status"),
                "competition": comp.get("name", ""),
                "competitionCode": comp.get("code", ""),
                "homeTeam": home.get("name", "نامشخص"),
                "awayTeam": away.get("name", "نامشخص"),
                "homeScore": full_time.get("home"),
                "awayScore": full_time.get("away"),
            })

        results.sort(key=lambda item: item.get("utcDate") or "")

        return {
            "ok": True,
            "matches": results,
            "count": len(results),
            "from": start.isoformat(),
            "to": end.isoformat(),
            "timezone": "Asia/Tehran",
            "competitions": COMPETITIONS,
        }

    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": "اتصال به سرویس مسابقات ناموفق بود",
            "details": str(exc),
            "matches": [],
}
