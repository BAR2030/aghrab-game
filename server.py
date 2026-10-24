import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
app=FastAPI()
TOKEN=os.getenv("FOOTBALL_DATA_TOKEN","").strip()
API="https://api.football-data.org/v4"
TZ=ZoneInfo("Asia/Tehran")
COMPETITIONS=[{"code":"PL","name":"لیگ برتر انگلیس"},{"code":"PD","name":"لالیگا اسپانیا"},{"code":"SA","name":"سری آ ایتالیا"},{"code":"FL1","name":"لیگ یک فرانسه"},{"code":"DED","name":"اردیویسه هلند"},{"code":"PPL","name":"لیگ پرتغال"},{"code":"BL1","name":"بوندس‌لیگا آلمان"},{"code":"CL","name":"لیگ قهرمانان اروپا"},{"code":"ELC","name":"چمپیونشیپ انگلیس"},{"code":"BSA","name":"سری آ برزیل"}]
@app.get("/health")
async def health(): return {"ok":True,"token_configured":bool(TOKEN)}
@app.get("/api/competitions")
async def competitions(): return {"competitions":COMPETITIONS}
@app.get("/api/matches")
async def matches(dateFrom:date=Query(...),dateTo:date=Query(...),competition:str=""):
 if not TOKEN:return {"error":"توکن FOOTBALL_DATA_TOKEN تنظیم نشده است.","matches":[]}
 params={"dateFrom":dateFrom.isoformat(),"dateTo":(dateTo+timedelta(days=1)).isoformat()}
 if competition and competition!="ALL":params["competitions"]=competition
 try:
  async with httpx.AsyncClient(timeout=20) as c:r=await c.get(API+"/matches",params=params,headers={"X-Auth-Token":TOKEN})
  if r.status_code!=200:return {"error":f"خطای سرویس مسابقات: HTTP {r.status_code}","details":r.text[:300],"matches":[]}
  out=[]
  for m in r.json().get("matches",[]):
   dt=datetime.fromisoformat(m["utcDate"].replace("Z","+00:00")).astimezone(TZ);ft=(m.get("score") or {}).get("fullTime") or {}
   out.append({"competition":(m.get("competition") or {}).get("name",""),"competitionCode":(m.get("competition") or {}).get("code",""),"homeTeam":(m.get("homeTeam") or {}).get("name","نامشخص"),"awayTeam":(m.get("awayTeam") or {}).get("name","نامشخص"),"localTime":dt.strftime("%H:%M"),"status":m.get("status",""),"homeScore":ft.get("home"),"awayScore":ft.get("away")})
  return {"matches":out,"from":str(dateFrom),"to":str(dateTo),"timezone":"Asia/Tehran"}
 except httpx.RequestError:return {"error":"ارتباط با سرویس مسابقات برقرار نشد.","matches":[]}
@app.get("/",response_class=HTMLResponse)
async def home():
 with open(os.path.join(os.path.dirname(__file__),"index.html"),encoding="utf-8") as f:return f.read()
