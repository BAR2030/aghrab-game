import os, hmac, hashlib, json, sqlite3, time
from urllib.parse import parse_qsl
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio, uuid
from dotenv import load_dotenv
load_dotenv()
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from fastapi.staticfiles import StaticFiles

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DATABASE_PATH", "aghrab.sqlite3")
API_SECRET = os.getenv("API_SECRET", "CHANGE_ME")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "CHANGE_ME_TOO")

app = FastAPI(title="Aghrab Admin API")
bot = Bot(BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          telegram_id INTEGER PRIMARY KEY,
          username TEXT DEFAULT '',
          first_name TEXT DEFAULT '',
          points INTEGER NOT NULL DEFAULT 0,
          tier TEXT NOT NULL DEFAULT 'free',
          blocked INTEGER NOT NULL DEFAULT 0,
          joined_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS point_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          telegram_id INTEGER NOT NULL,
          admin_id INTEGER NOT NULL,
          delta INTEGER NOT NULL,
          reason TEXT DEFAULT '',
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payments (
          payment_id TEXT PRIMARY KEY,
          telegram_id INTEGER NOT NULL,
          tier TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at INTEGER NOT NULL,
          confirmed_at INTEGER
        );
        """)
init_db()

# Existing fixed checkout links from the supplied Aghrab mini-app.
PAYMENT_LINKS = {
    "vip": "https://pay.pexn.ir/l/dwpBjsf",
    "cip": "https://pay.pexn.ir/l/j3pZMXG",
}

def verify_init_data(init_data: str):
    """Validate Telegram WebApp initData using the bot token."""
    if not BOT_TOKEN:
        raise HTTPException(503, "Bot token is not configured")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Missing Telegram initData hash")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise HTTPException(401, "Invalid Telegram initData")
    auth_date = int(pairs.get("auth_date", "0"))
    if time.time() - auth_date > 86400:
        raise HTTPException(401, "Telegram initData expired")
    try:
        user = json.loads(pairs["user"])
        return user
    except Exception:
        raise HTTPException(401, "Invalid Telegram user data")

def upsert_user(user):
    now = int(time.time())
    uid = int(user["id"])
    with db() as con:
        con.execute("""INSERT INTO users(telegram_id,username,first_name,joined_at,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
        username=excluded.username, first_name=excluded.first_name, updated_at=excluded.updated_at""",
        (uid, user.get("username",""), user.get("first_name",""), now, now))
        row = con.execute("SELECT * FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return dict(row)

def user_from_auth(authorization):
    if not authorization or not authorization.startswith("tma "):
        raise HTTPException(401, "Telegram WebApp authorization required")
    user = verify_init_data(authorization[4:])
    row = upsert_user(user)
    if row["blocked"]:
        raise HTTPException(403, "This user is blocked")
    return row

class PointsBody(BaseModel):
    delta: int
    reason: str = "admin adjustment"

class TierBody(BaseModel):
    tier: str

@app.get("/health")
def health():
    return {"ok": True, "service": "aghrab-admin"}

@app.get("/api/me")
def me(authorization: str = Header(default="")):
    u = user_from_auth(authorization)
    return {"telegram_id": u["telegram_id"], "points": u["points"], "tier": u["tier"], "blocked": bool(u["blocked"])}

@app.get("/api/subscription")
def subscription(authorization: str = Header(default="")):
    u = user_from_auth(authorization)
    with db() as con:
        row = con.execute("SELECT MAX(confirmed_at) AS activated_at FROM payments WHERE telegram_id=? AND status='paid'", (u["telegram_id"],)).fetchone()
    return {"tier": u["tier"], "activated_at": row["activated_at"] if row else None}

@app.post("/api/admin/points/{telegram_id}")
def change_points(telegram_id: int, body: PointsBody, x_api_secret: str = Header(default="")):
    if not hmac.compare_digest(x_api_secret, API_SECRET):
        raise HTTPException(401, "Unauthorized")
    now = int(time.time())
    with db() as con:
        cur = con.execute("UPDATE users SET points=MAX(0, points+?), updated_at=? WHERE telegram_id=?", (body.delta, now, telegram_id))
        if cur.rowcount == 0: raise HTTPException(404, "User not found")
        con.execute("INSERT INTO point_log(telegram_id,admin_id,delta,reason,created_at) VALUES(?,?,?,?,?)",
                    (telegram_id, 0, body.delta, body.reason, now))
        row = con.execute("SELECT points FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    return {"ok": True, "points": row["points"]}

@app.post("/api/payments/create")
def create_payment(body: TierBody, authorization: str = Header(default="")):
    """Create a local pending order and open the existing Pexn checkout link.

    IMPORTANT: Pexn must preserve/pass payment_id, telegram_id and tier to its
    verified server callback for automatic activation to work. Confirm its actual
    callback/metadata support before production.
    """
    u = user_from_auth(authorization)
    tier = body.tier
    if tier not in PAYMENT_LINKS:
        raise HTTPException(400, "tier must be vip or cip")
    payment_id = uuid.uuid4().hex
    now = int(time.time())
    with db() as con:
        con.execute("INSERT INTO payments(payment_id,telegram_id,tier,status,created_at) VALUES(?,?,?,?,?)",
                    (payment_id, u["telegram_id"], tier, "pending", now))
    parts = urlsplit(PAYMENT_LINKS[tier])
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"payment_id": payment_id, "telegram_id": str(u["telegram_id"]), "tier": tier})
    payment_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return {"payment_url": payment_url, "payment_id": payment_id, "tier": tier}

@app.post("/api/payments/confirmed")
async def payment_confirmed(request: Request, x_webhook_secret: str = Header(default="")):
    """Generic webhook endpoint. Adapt payload mapping to your payment provider before production."""
    if not hmac.compare_digest(x_webhook_secret, WEBHOOK_SECRET):
        raise HTTPException(401, "Unauthorized")
    payload = await request.json()
    # Expected payload: {"payment_id":"...", "telegram_id":123, "tier":"vip", "status":"paid"}
    if payload.get("status") != "paid" or payload.get("tier") not in ("vip", "cip"):
        raise HTTPException(400, "Expected a confirmed VIP/CIP payment")
    payment_id, uid, tier = str(payload.get("payment_id","")), int(payload.get("telegram_id",0)), payload["tier"]
    if not payment_id or not uid:
        raise HTTPException(400, "payment_id and telegram_id are required")
    now = int(time.time())
    with db() as con:
        existing = con.execute("SELECT status FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
        if existing and existing["status"] == "paid":
            return {"ok": True, "already_processed": True}
        con.execute("""INSERT INTO payments(payment_id,telegram_id,tier,status,created_at,confirmed_at)
        VALUES(?,?,?,?,?,?) ON CONFLICT(payment_id) DO UPDATE SET status='paid',confirmed_at=excluded.confirmed_at""",
                    (payment_id, uid, tier, "paid", now, now))
        con.execute("UPDATE users SET tier=?,updated_at=? WHERE telegram_id=?", (tier, now, uid))
    return {"ok": True, "telegram_id": uid, "tier": tier}

def is_admin(user_id):
    return user_id in ADMIN_IDS

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 کاربران اخیر", callback_data="users")],
        [InlineKeyboardButton(text="🔎 جستجوی کاربر با آیدی", callback_data="search")],
        [InlineKeyboardButton(text="📊 آمار", callback_data="stats")],
        [InlineKeyboardButton(text="ℹ️ راهنما", callback_data="help")]
    ])

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("ربات مدیریت عقرب فعال است. برای پنل ادمین /admin را بزنید.")

@dp.message(Command("admin"))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ دسترسی ندارید.")
        return
    await message.answer("👑 پنل مدیریت عقرب", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "users")
async def recent_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی ندارید", show_alert=True); return
    with db() as con:
        rows = con.execute("SELECT telegram_id,username,first_name,points,tier,blocked FROM users ORDER BY updated_at DESC LIMIT 15").fetchall()
    if not rows:
        await call.message.answer("هنوز کاربری از طریق API ثبت نشده است.")
    else:
        lines = ["👥 کاربران اخیر:"]
        for r in rows:
            lines.append(f"ID: {r['telegram_id']} | @{r['username'] or '-'} | {r['first_name']} | امتیاز: {r['points']} | {r['tier']} | {'مسدود' if r['blocked'] else 'فعال'}")
        await call.message.answer("\n".join(lines))
    await call.answer()

@dp.callback_query(F.data == "stats")
async def stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی ندارید", show_alert=True); return
    with db() as con:
        total = con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        vip = con.execute("SELECT COUNT(*) n FROM users WHERE tier='vip'").fetchone()["n"]
        cip = con.execute("SELECT COUNT(*) n FROM users WHERE tier='cip'").fetchone()["n"]
        blocked = con.execute("SELECT COUNT(*) n FROM users WHERE blocked=1").fetchone()["n"]
    await call.message.answer(f"📊 آمار عقرب\nکل کاربران ثبت‌شده: {total}\nVIP: {vip}\nCIP: {cip}\nمسدود: {blocked}")
    await call.answer()

@dp.callback_query(F.data == "search")
async def search_prompt(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی ندارید", show_alert=True); return
    await call.message.answer("برای جستجو، دستور زیر را بفرست:\n/user 123456789")
    await call.answer()

@dp.callback_query(F.data == "help")
async def help_panel(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی ندارید", show_alert=True); return
    await call.message.answer(
        "دستورهای مدیریتی:\n"
        "/user ID — نمایش کاربر\n"
        "/addpoints ID AMOUNT دلیل — افزایش امتیاز\n"
        "/removepoints ID AMOUNT دلیل — کاهش امتیاز\n"
        "/block ID — مسدودسازی\n"
        "/unblock ID — رفع مسدودیت\n"
        "/tier ID free|vip|cip — تنظیم اشتراک\n\n"
        "مثال: /addpoints 123456789 5000 جایزه"
    )
    await call.answer()

@dp.message(Command("user"))
async def get_user(message: Message):
    if not is_admin(message.from_user.id): return await message.answer("⛔️ دسترسی ندارید.")
    args = (message.text or "").split()
    if len(args) != 2 or not args[1].isdigit(): return await message.answer("فرمت: /user ID")
    with db() as con: row = con.execute("SELECT * FROM users WHERE telegram_id=?", (int(args[1]),)).fetchone()
    if not row: return await message.answer("کاربر پیدا نشد؛ باید حداقل یک بار از طریق API وارد شده باشد.")
    await message.answer(f"👤 {row['first_name']} (@{row['username'] or '-'})\nID: {row['telegram_id']}\nامتیاز: {row['points']}\nاشتراک: {row['tier']}\nوضعیت: {'مسدود' if row['blocked'] else 'فعال'}")

@dp.message(Command("addpoints", "removepoints"))
async def points_cmd(message: Message):
    if not is_admin(message.from_user.id): return await message.answer("⛔️ دسترسی ندارید.")
    args = (message.text or "").split(maxsplit=3)
    if len(args) < 3 or not args[1].isdigit() or not args[2].lstrip("-").isdigit():
        return await message.answer("فرمت: /addpoints ID AMOUNT دلیل\nیا /removepoints ID AMOUNT دلیل")
    uid, amount = int(args[1]), abs(int(args[2]))
    delta = amount if message.text.startswith("/addpoints") else -amount
    reason = args[3] if len(args) > 3 else "admin adjustment"
    now = int(time.time())
    with db() as con:
        cur = con.execute("UPDATE users SET points=MAX(0,points+?),updated_at=? WHERE telegram_id=?", (delta, now, uid))
        if cur.rowcount == 0: return await message.answer("کاربر پیدا نشد.")
        con.execute("INSERT INTO point_log(telegram_id,admin_id,delta,reason,created_at) VALUES(?,?,?,?,?)",
                    (uid, message.from_user.id, delta, reason, now))
        points = con.execute("SELECT points FROM users WHERE telegram_id=?", (uid,)).fetchone()["points"]
    await message.answer(f"✅ موجودی کاربر {uid} تغییر کرد.\nموجودی فعلی: {points}")

@dp.message(Command("block", "unblock"))
async def block_cmd(message: Message):
    if not is_admin(message.from_user.id): return await message.answer("⛔️ دسترسی ندارید.")
    args = (message.text or "").split()
    if len(args) != 2 or not args[1].isdigit(): return await message.answer("فرمت: /block ID یا /unblock ID")
    blocked = 1 if message.text.startswith("/block") else 0
    with db() as con:
        cur = con.execute("UPDATE users SET blocked=?,updated_at=? WHERE telegram_id=?", (blocked, int(time.time()), int(args[1])))
    if not cur.rowcount: return await message.answer("کاربر پیدا نشد.")
    await message.answer("✅ کاربر مسدود شد." if blocked else "✅ محدودیت کاربر برداشته شد.")

@dp.message(Command("tier"))
async def tier_cmd(message: Message):
    if not is_admin(message.from_user.id): return await message.answer("⛔️ دسترسی ندارید.")
    args = (message.text or "").split()
    if len(args) != 3 or not args[1].isdigit() or args[2] not in ("free","vip","cip"):
        return await message.answer("فرمت: /tier ID free|vip|cip")
    with db() as con:
        cur = con.execute("UPDATE users SET tier=?,updated_at=? WHERE telegram_id=?", (args[2], int(time.time()), int(args[1])))
    if not cur.rowcount: return await message.answer("کاربر پیدا نشد.")
    await message.answer(f"✅ اشتراک کاربر تنظیم شد: {args[2]}")

async def run_bot():
    if not bot:
        print("BOT_TOKEN is missing; Telegram bot polling is disabled.")
        return
    await dp.start_polling(bot)

# Serve the connected mini-app from the same origin as the API.
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "web"), html=True), name="web")

if __name__ == "__main__":
    async def runner():
        import uvicorn
        config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
        server = uvicorn.Server(config)
        await asyncio.gather(server.serve(), run_bot())
    asyncio.run(runner())
