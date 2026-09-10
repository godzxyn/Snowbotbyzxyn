#!/usr/bin/env python3
"""
Yuki Telegram Bot ❄️  — Ultra Edition v5.0
Character: Yuki (雪 = Snow) — cute innocent small girl, bubbly & sweet
Currency: Yukens (❄️) — unique in-game currency
v5: Cuter personality, special chat ID, improved RPS battles, inline filter
    removal, anti-flood mute fix, new fun commands, download endpoint
"""

import os, json, random, time, aiohttp, asyncio, sqlite3, re, math, uuid
from datetime import datetime, timedelta
from collections import deque, defaultdict

from telegram import (Update, ChatPermissions, InlineKeyboardButton,
                      InlineKeyboardMarkup, BotCommand, WebAppInfo)
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, filters, ContextTypes)
from telegram.constants import ParseMode, ChatAction

# ═══════════════════════════════════════════════════════════════════
# CONFIG — change these
# ═══════════════════════════════════════════════════════════════════
def read_bot_token():
    token = "8415751681:AAFiviEH-QNQK4uOvnGx1e7IhbiUfF3Sxm8"
    return token



TOKEN = read_bot_token()
GROQ_KEY = os.getenv("GROQ_API_KEY", "xai-dOCgthtU518onIRuHVHmjT0j7i8xy3cBizfsBg0f6qSrPsX2YgeiPryogEebSq5oeFkaJdNb9SUwcTUK").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_URL = os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions").strip()
KING_ID  = 8895537848

# Special chat ID — set to a chat_id (user or group) for extra personalized love
# Messages from this chat_id get a sweeter, more affectionate Yuki response
SPECIAL_CHAT_ID = 0   # 0 = disabled; set to e.g. 123456789 to enable

is_king = lambda uid: uid == KING_ID

BOT_USERNAME = ""
BOT_ID       = 0

# ─── Unique Currency ───────────────────────────────────────────────
CUR   = "Snow"   # currency name (shown to users)
CUR_S = "❄️"       # currency symbol

# Economy guardrails. The old build paid 5,000–500,000 coins per kill,
# which inflated the whole economy after only a few messages.
KILL_REWARD_MIN = max(10, int(os.getenv("KILL_REWARD_MIN", "100")))
KILL_REWARD_MAX = max(KILL_REWARD_MIN, int(os.getenv("KILL_REWARD_MAX", "500")))
KILL_COOLDOWN_SECONDS = max(0, int(os.getenv("KILL_COOLDOWN_SECONDS", "20")))
PREMIUM_WEBAPP_URL = os.getenv("PREMIUM_WEBAPP_URL", "").strip()

PREMIUM_PLANS = {
    "1m": {"label": "1 month", "price": 50, "days": 30},
    "3m": {"label": "3 months", "price": 100, "days": 90},
    "1y": {"label": "1 year", "price": 500, "days": 365},
}

# ═══════════════════════════════════════════════════════════════════
# DATABASE — SQLite (survives restarts 100%)
# ═══════════════════════════════════════════════════════════════════

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yuki_data.db")

def db_connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    conn = db_connect()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS users (
            uid INTEGER PRIMARY KEY,
            name TEXT,
            coins INTEGER DEFAULT 0,
            kills INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            deaths_until INTEGER DEFAULT 0,
            shield_until INTEGER DEFAULT 0,
            daily_last TEXT,
            daily_streak INTEGER DEFAULT 0,
            premium_plan TEXT DEFAULT '',
            premium_until INTEGER DEFAULT 0,
            premium_started INTEGER DEFAULT 0,
            premium_order_id TEXT DEFAULT '',
            warnings INTEGER DEFAULT 0,
            bounty INTEGER DEFAULT 0,
            couple_id INTEGER DEFAULT NULL,
            afk_since INTEGER DEFAULT 0,
            afk_reason TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS inventory (
            uid INTEGER, item_id TEXT, qty INTEGER DEFAULT 0,
            PRIMARY KEY (uid, item_id)
        );
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            welcome TEXT DEFAULT '',
            goodbye TEXT DEFAULT '',
            rules TEXT DEFAULT '',
            antiflood INTEGER DEFAULT 0,
            slowmode INTEGER DEFAULT 0,
            locked_types TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS notes (
            chat_id INTEGER, name TEXT, content TEXT,
            PRIMARY KEY (chat_id, name)
        );
        CREATE TABLE IF NOT EXISTS filters_kw (
            chat_id INTEGER, keyword TEXT, response TEXT,
            PRIMARY KEY (chat_id, keyword)
        );
        CREATE TABLE IF NOT EXISTS fir_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER, reporter_id INTEGER,
            accused_id INTEGER, reason TEXT,
            ts INTEGER, status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS active_chats (
            chat_id INTEGER PRIMARY KEY,
            last_seen INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER, label TEXT, content TEXT,
            ts INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS banks (
            uid INTEGER, bank_id TEXT, balance INTEGER DEFAULT 0,
            last_interest INTEGER DEFAULT 0,
            PRIMARY KEY (uid, bank_id)
        );
        CREATE TABLE IF NOT EXISTS skills (
            uid INTEGER, skill_name TEXT, skill_xp INTEGER DEFAULT 0,
            PRIMARY KEY (uid, skill_name)
        );
        CREATE TABLE IF NOT EXISTS co_owners (
            uid INTEGER PRIMARY KEY, added_by INTEGER, added_ts INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS premium_orders (
            order_id TEXT PRIMARY KEY,
            uid INTEGER NOT NULL,
            name TEXT DEFAULT '',
            plan_key TEXT NOT NULL,
            utr TEXT NOT NULL,
            note TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            submitted_at INTEGER DEFAULT 0,
            reviewed_at INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()

db_init()

# Safe migrations for new columns
def _safe_migrate():
    conn = db_connect()
    for sql in [
        "ALTER TABLE users ADD COLUMN is_bounty_target INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN premium_plan TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN premium_until INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN premium_started INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN premium_order_id TEXT DEFAULT ''",
    ]:
        try: conn.execute(sql)
        except: pass
    conn.commit(); conn.close()
_safe_migrate()

# ─── DB helpers ───────────────────────────────────────────────────

def _exec(sql, params=()):
    conn = db_connect()
    conn.execute(sql, params)
    conn.commit()
    conn.close()

def _fetch(sql, params=()):
    conn = db_connect()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row

def _fetchall(sql, params=()):
    conn = db_connect()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def _ensure_user(uid, name=None):
    row = _fetch("SELECT uid FROM users WHERE uid=?", (uid,))
    if not row:
        _exec("INSERT OR IGNORE INTO users (uid, name) VALUES (?,?)", (uid, name or f"User{uid}"))
    elif name:
        _exec("UPDATE users SET name=? WHERE uid=?", (name, uid))


# ─── Premium membership ─────────────────────────────────────────────
def premium_row(uid):
    return _fetch(
        "SELECT premium_plan, premium_until, premium_started, premium_order_id "
        "FROM users WHERE uid=?",
        (uid,),
    )


def is_premium(uid):
    row = premium_row(uid)
    return bool(row and (row["premium_until"] or 0) > int(time.time()))


def premium_days_left(uid):
    row = premium_row(uid)
    if not row:
        return 0
    return max(0, math.ceil(((row["premium_until"] or 0) - time.time()) / 86400))


def premium_plan_label(uid):
    row = premium_row(uid)
    return PREMIUM_PLANS.get(row["premium_plan"], {}).get("label", "Premium") if row else "Premium"


def premium_gate_text():
    return (
        "🔒 *Premium feature*\n\n"
        "Is feature ko use karne ke liye Yuki Premium chahiye.\n"
        "Premium page par plan choose karo; payment verify hone ke baad owner unlock karega.\n\n"
        "Plans: `₹50 / 1 month` · `₹100 / 3 months` · `₹500 / 1 year`\n"
        "Open: `/premium`"
    )


def premium_keyboard():
    if not PREMIUM_WEBAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "Open Premium Mini App",
            web_app=WebAppInfo(url=PREMIUM_WEBAPP_URL),
        )
    ]])


def grant_premium(uid, plan_key, order_id=""):
    plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        return None
    now = int(time.time())
    current = premium_row(uid)
    base = max(now, int(current["premium_until"] or 0)) if current else now
    until = base + plan["days"] * 86400
    _ensure_user(uid)
    _exec(
        "UPDATE users SET premium_plan=?, premium_until=?, premium_started=?, "
        "premium_order_id=? WHERE uid=?",
        (plan_key, until, now, order_id or "", uid),
    )
    return until


def create_premium_order(uid, name, plan_key, utr, note=""):
    """Store a FamPay proof for owner review; never unlock from client data."""
    order_id = uuid.uuid4().hex[:12].upper()
    _exec(
        "INSERT INTO premium_orders "
        "(order_id, uid, name, plan_key, utr, note, status, submitted_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (order_id, uid, name or "", plan_key, utr, note[:240], "pending", int(time.time())),
    )
    return order_id


def get_premium_order(order_id):
    return _fetch("SELECT * FROM premium_orders WHERE order_id=?", (order_id,))


def update_premium_order(order_id, status):
    _exec(
        "UPDATE premium_orders SET status=?, reviewed_at=? WHERE order_id=?",
        (status, int(time.time()), order_id),
    )


async def cmd_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_name(user)
    active = is_premium(user.id)
    lines = ["❄️ *Yuki Premium*\n"]
    if active:
        expiry = datetime.fromtimestamp(premium_row(user.id)["premium_until"]).strftime("%d %b %Y")
        lines.append(
            f"✅ Active: *{premium_plan_label(user.id)}*\n"
            f"⏰ Valid for `{premium_days_left(user.id)}` more days (until {expiry})\n"
        )
    else:
        lines.append("Unlock the full snow-sprite experience:\n")
    lines.extend([
        "💳 *Plans*",
        "• `₹50` — 1 month",
        "• `₹100` — 3 months",
        "• `₹500` — 1 year",
        "",
        "🎁 *Premium benefits*",
        "• 3-day protection in one go",
        "• 1.5x daily bonus and streak rewards",
        "• Better kill rewards and bank interest",
        "• Premium Ludo and event rooms",
        "• Exclusive cute replies and playful roasts",
        "• Premium-only drops and economy perks",
    ])
    if not PREMIUM_WEBAPP_URL:
        lines.extend([
            "",
            "⚠️ Telegram Mini App URL abhi configured nahi hai.",
            "Owner published `/premium` URL ko `PREMIUM_WEBAPP_URL` me set karega; tab yahin button dikhega.",
        ])
    else:
        lines.extend(["", "👇 Mini App kholkar plan choose karo."])
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=premium_keyboard(),
    )


def premium_order_keyboard(order_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Approve payment", callback_data=f"premium_order_approve:{order_id}"),
        InlineKeyboardButton("Reject", callback_data=f"premium_order_reject:{order_id}"),
    ]])


async def cmd_web_app_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Receive a Mini App FamPay proof and send it to the owner for review."""
    message = update.effective_message
    user = update.effective_user
    store_name(user)
    try:
        payload = json.loads(message.web_app_data.data or "{}")
    except (TypeError, json.JSONDecodeError):
        return await message.reply_text("❌ Payment form data samajh nahi aaya. Dobara /premium kholo.")

    if payload.get("type") != "premium_payment_submission":
        return await message.reply_text("❌ Unknown Mini App action.")

    plan_map = {"month": "1m", "quarter": "3m", "year": "1y"}
    plan_key = plan_map.get(str(payload.get("plan", "")).lower())
    utr = str(payload.get("utr", "")).strip()
    note = str(payload.get("note", "")).strip()
    if not plan_key or len(utr) < 4 or len(utr) > 64:
        return await message.reply_text(
            "❌ Plan ya UTR invalid hai. Plan select karke valid FamPay UTR/reference number bhejo."
        )

    order_id = create_premium_order(user.id, user.first_name or user.username, plan_key, utr, note)
    plan = PREMIUM_PLANS[plan_key]
    owner_text = (
        "💳 New FamPay Premium payment proof\n\n"
        f"Order: {order_id}\n"
        f"User: {user.first_name or 'Unknown'} (ID {user.id})\n"
        f"Plan: {plan['label']} · ₹{plan['price']}\n"
        f"UTR: {utr}\n"
        f"Note: {note or '—'}\n\n"
        "FamPay app me amount/UTR verify karke Approve ya Reject dabao."
    )
    try:
        await ctx.bot.send_message(
            chat_id=KING_ID,
            text=owner_text,
            reply_markup=premium_order_keyboard(order_id),
        )
    except Exception as exc:
        await message.reply_text(
            "⚠️ Proof save ho gaya hai, lekin owner notification nahi bhej paayi. "
            f"Order ID: {order_id}"
        )
        print(f"Premium owner notification failed for {order_id}: {exc}")
        return
    await message.reply_text(
        "✅ Payment proof submit ho gaya.\n\n"
        f"Order ID: {order_id}\n"
        "FamPay payment verify hone ke baad owner premium unlock karega. "
        "Fake success nahi dikhaya gaya hai."
    )


async def premium_payment_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_king(query.from_user.id):
        return await query.answer("Sirf owner payment review kar sakta hai.", show_alert=True)
    try:
        action, order_id = query.data.replace("premium_order_", "", 1).split(":", 1)
    except ValueError:
        return await query.answer("Invalid payment review.", show_alert=True)
    order = get_premium_order(order_id)
    if not order:
        return await query.answer("Order nahi mila.", show_alert=True)
    if order["status"] != "pending":
        return await query.answer(f"Order already {order['status']} hai.", show_alert=True)

    if action == "approve":
        until = grant_premium(order["uid"], order["plan_key"], order_id)
        update_premium_order(order_id, "approved")
        expiry = datetime.fromtimestamp(until).strftime("%d %b %Y")
        await query.edit_message_text(
            f"✅ APPROVED\nOrder: {order_id}\n"
            f"User ID: {order['uid']}\n"
            f"Plan: {PREMIUM_PLANS[order['plan_key']]['label']}\n"
            f"Valid until: {expiry}"
        )
        try:
            await ctx.bot.send_message(
                chat_id=order["uid"],
                text=(
                    "✅ FamPay payment verify ho gaya!\n\n"
                    f"Yuki Premium active: {PREMIUM_PLANS[order['plan_key']]['label']}\n"
                    f"Valid until: {expiry}\n"
                    "Ab /premium, /shield 3 aur /ludo use kar sakte ho."
                ),
            )
        except Exception as exc:
            print(f"Premium approval notification failed for {order_id}: {exc}")
    elif action == "reject":
        update_premium_order(order_id, "rejected")
        await query.edit_message_text(
            f"❌ REJECTED\nOrder: {order_id}\nUser ID: {order['uid']}\n"
            "Payment proof owner ne reject kiya."
        )
        try:
            await ctx.bot.send_message(
                chat_id=order["uid"],
                text=(
                    "❌ Payment proof verify nahi ho paaya.\n"
                    "FamPay amount/UTR check karke /premium se dobara submit karo."
                ),
            )
        except Exception as exc:
            print(f"Premium rejection notification failed for {order_id}: {exc}")
    else:
        return await query.answer("Unknown review action.", show_alert=True)
    await query.answer("Done")


async def cmd_premiumgrant(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner-only manual unlock until a billing provider webhook is connected."""
    owner = update.effective_user
    if not is_king(owner.id):
        return await update.message.reply_text("👑 Premium unlock sirf owner kar sakta hai.")

    target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    args = list(ctx.args)
    if target:
        plan_key = args.pop(0).lower() if args else ""
    elif len(args) >= 2 and args[0].lstrip("-").isdigit():
        target_id = int(args.pop(0))
        target = type("PremiumTarget", (), {"id": target_id, "first_name": f"User{target_id}"})()
        plan_key = args.pop(0).lower()
    else:
        return await update.message.reply_text(
            "Reply karke: `/premiumgrant 1m [order_id]`\n"
            "Ya: `/premiumgrant <user_id> 3m [order_id]`",
            parse_mode=ParseMode.MARKDOWN,
        )

    aliases = {"1month": "1m", "month": "1m", "3month": "3m", "3months": "3m", "year": "1y", "1year": "1y"}
    plan_key = aliases.get(plan_key, plan_key)
    if plan_key not in PREMIUM_PLANS:
        return await update.message.reply_text("Plan `1m`, `3m` ya `1y` hona chahiye.", parse_mode=ParseMode.MARKDOWN)
    store_name(target)
    until = grant_premium(target.id, plan_key, args[0] if args else "")
    expiry = datetime.fromtimestamp(until).strftime("%d %b %Y")
    await update.message.reply_text(
        f"✅ Premium unlocked for {get_mention(target)}\n"
        f"Plan: *{PREMIUM_PLANS[plan_key]['label']}* · ₹{PREMIUM_PLANS[plan_key]['price']}\n"
        f"Valid until: `{expiry}`\n"
        "_Payment verification manually confirm hone ke baad hi yeh command use karo._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_ludo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_name(user)
    if not is_premium(user.id):
        return await update.message.reply_text(
            premium_gate_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=premium_keyboard(),
        )
    if not PREMIUM_WEBAPP_URL:
        return await update.message.reply_text(
            "🎲 Premium Ludo unlocked hai, lekin Mini App URL abhi configure nahi hua.\n"
            "Owner ko `PREMIUM_WEBAPP_URL` set karna hoga.",
        )
    separator = "&" if "?" in PREMIUM_WEBAPP_URL else "?"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "Open Premium Ludo",
            web_app=WebAppInfo(url=f"{PREMIUM_WEBAPP_URL}{separator}game=ludo"),
        )
    ]])
    await update.message.reply_text(
        "🎲 *Premium Ludo Room*\n\n"
        "Private Telegram Mini App room ready hai. Friends ko invite karke khelo.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )

def store_name(user):
    if user and user.id:
        _ensure_user(user.id, user.first_name or user.username or f"User{user.id}")

def get_name(uid):
    row = _fetch("SELECT name FROM users WHERE uid=?", (uid,))
    return row["name"] if row else f"User{uid}"

def get_coins(uid):
    row = _fetch("SELECT coins FROM users WHERE uid=?", (uid,))
    return row["coins"] if row else 0

def get_kills(uid):
    row = _fetch("SELECT kills FROM users WHERE uid=?", (uid,))
    return row["kills"] if row else 0

def get_xp(uid):
    row = _fetch("SELECT xp FROM users WHERE uid=?", (uid,))
    return row["xp"] if row else 0

def add_coins(uid, n):
    _ensure_user(uid)
    _exec("UPDATE users SET coins=MAX(0, coins+?) WHERE uid=?", (n, uid))

def add_kill(uid):
    _ensure_user(uid)
    _exec("UPDATE users SET kills=kills+1 WHERE uid=?", (uid,))

def add_xp(uid, n=5):
    """Add activity XP — used ONLY for skill tracking, NOT for leveling."""
    _ensure_user(uid)
    _exec("UPDATE users SET xp=xp+? WHERE uid=?", (n, uid))

# ─── Kill-Based Level System (10 levels) ──────────────────────────
# Levels ab KILLS se milte hain, XP se nahi. Skills alag hain.
KILL_THRESHOLDS = [0, 200, 500, 1000, 2000, 4000, 7000, 12000, 20000, 35000]
LEVEL_NAMES = [
    "Ice Seed 🌱",        # 0  —   0  kills
    "Frost Sprout ⛄",    # 1  — 200  kills
    "Snow Apprentice ❄️", # 2  — 500  kills
    "Blizzard Warrior ⚔️",# 3  — 1000 kills
    "Frost Knight 🛡️",    # 4  — 2000 kills
    "Ice Commander 👑",   # 5  — 4000 kills
    "Snowstorm Lord 🌪️",  # 6  — 7000 kills
    "Avalanche God ⚡",   # 7  — 12000 kills
    "Winter's Chosen 🌙", # 8  — 20000 kills
    "Eternal Frost ✨",   # 9  — 35000 kills (max)
]

def get_level(uid):
    """Level is determined by total KILLS, not XP."""
    kills = get_kills(uid)
    lvl = 0
    for i, threshold in enumerate(KILL_THRESHOLDS):
        if kills >= threshold:
            lvl = i
    return lvl

def kills_for_next(uid):
    """Kills needed for next level. None if max level."""
    lvl = get_level(uid)
    if lvl >= len(KILL_THRESHOLDS) - 1:
        return None
    return KILL_THRESHOLDS[lvl + 1]

# Keep alias for backwards compat in profile/xp commands
def xp_for_next(uid):
    return kills_for_next(uid)

def get_rank_name(uid):
    name = get_name(uid)
    lvl  = get_level(uid)
    if is_king(uid): return f"👑 Lord {name}"
    return f"{name} [{LEVEL_NAMES[lvl]}]"

def track_active_chat(chat_id):
    """Remember this chat for auto-bounty broadcasts."""
    _exec(
        "INSERT INTO active_chats (chat_id, last_seen) VALUES (?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET last_seen=excluded.last_seen",
        (chat_id, int(time.time()))
    )

def is_dead(uid):
    row = _fetch("SELECT deaths_until FROM users WHERE uid=?", (uid,))
    if not row: return False
    return row["deaths_until"] > int(time.time())

def kill_user(uid, secs=86400):
    """Kill user for `secs` seconds (default 24h; bounty targets = 1800 = 30min)."""
    _ensure_user(uid)
    _exec("UPDATE users SET deaths_until=? WHERE uid=?", (int(time.time())+secs, uid))

def revive_user(uid):
    _ensure_user(uid)
    _exec("UPDATE users SET deaths_until=0 WHERE uid=?", (uid,))

def has_shield(uid):
    row = _fetch("SELECT shield_until FROM users WHERE uid=?", (uid,))
    if not row: return False
    return row["shield_until"] > int(time.time())

def set_shield(uid, secs):
    _ensure_user(uid)
    _exec("UPDATE users SET shield_until=? WHERE uid=?", (int(time.time())+secs, uid))

def shield_left(uid):
    row = _fetch("SELECT shield_until FROM users WHERE uid=?", (uid,))
    if not row: return 0
    return max(0, row["shield_until"] - int(time.time()))

def apply_tax(amount):
    king_cut = int(amount * 0.10)
    add_coins(KING_ID, king_cut)
    return king_cut

# ═══════════════════════════════════════════════════════════════════
# SKILL SYSTEM
# ═══════════════════════════════════════════════════════════════════

SKILLS = {
    "kill":    {"emoji":"⚔️",  "name":"Kill Skill",    "desc":"Kill rewards badh jaate hain"},
    "rob":     {"emoji":"🦊",  "name":"Rob Skill",     "desc":"Rob success rate + amount badh jaata hai"},
    "gamble":  {"emoji":"🎰",  "name":"Gamble Skill",  "desc":"Thodi better odds milti hain"},
    "defense": {"emoji":"🛡️", "name":"Defense Skill",  "desc":"Rob/Kill damage kam ho jaata hai"},
    "bank":    {"emoji":"🏦",  "name":"Bank Skill",    "desc":"Bank interest rate badh jaati hai"},
    "social":  {"emoji":"💬",  "name":"Social Skill",  "desc":"Daily reward multiplier badh jaata hai"},
}
SKILL_XP_LEVELS = [0, 50, 150, 350, 700, 1200, 2000, 3000, 5000, 8000, 12000]  # 11 entries = levels 0-10

def get_skill_xp(uid, skill):
    row = _fetch("SELECT skill_xp FROM skills WHERE uid=? AND skill_name=?", (uid, skill))
    return row["skill_xp"] if row else 0

def get_skill_level(uid, skill):
    xp = get_skill_xp(uid, skill)
    lvl = 0
    for i, t in enumerate(SKILL_XP_LEVELS):
        if xp >= t: lvl = i
    return min(lvl, 10)

def add_skill_xp(uid, skill, n=1):
    _ensure_user(uid)
    if skill not in SKILLS: return
    _exec(
        "INSERT INTO skills (uid, skill_name, skill_xp) VALUES (?,?,?) "
        "ON CONFLICT(uid, skill_name) DO UPDATE SET skill_xp=skill_xp+?",
        (uid, skill, n, n)
    )

def skill_bonus(uid, skill):
    """Return a multiplier (0.0-1.0 extra) based on skill level 0-10."""
    return get_skill_level(uid, skill) * 0.05  # 5% per level, max 50%

# ═══════════════════════════════════════════════════════════════════
# BANK SYSTEM
# ═══════════════════════════════════════════════════════════════════

BANK_INFO = {
    "ice":      {"emoji":"❄️",  "name":"Ice Bank",          "interest":0,    "safe":1.0,  "min_level":0, "desc":"0% interest, 100% safe from rob"},
    "frost":    {"emoji":"🌊",  "name":"Frost Credit",      "interest":0.02, "safe":0.75, "min_level":2, "desc":"2% daily interest, 75% safe (req. Level 2)"},
    "blizzard": {"emoji":"💎",  "name":"Blizzard Treasury", "interest":0.05, "safe":1.0,  "min_level":5, "desc":"5% daily interest, 100% safe (req. Level 5)"},
}

def get_bank_balance(uid, bank_id):
    row = _fetch("SELECT balance FROM banks WHERE uid=? AND bank_id=?", (uid, bank_id))
    return row["balance"] if row else 0

def get_all_bank_balances(uid):
    return {b: get_bank_balance(uid, b) for b in BANK_INFO}

def deposit_bank(uid, bank_id, amount):
    _exec(
        "INSERT INTO banks (uid, bank_id, balance, last_interest) VALUES (?,?,?,?) "
        "ON CONFLICT(uid, bank_id) DO UPDATE SET balance=balance+?",
        (uid, bank_id, amount, int(time.time()), amount)
    )

def withdraw_bank(uid, bank_id, amount):
    bal = get_bank_balance(uid, bank_id)
    actual = min(amount, bal)
    if actual <= 0: return 0
    _exec("UPDATE banks SET balance=balance-? WHERE uid=? AND bank_id=?", (actual, uid, bank_id))
    return actual

def apply_bank_interests(uid):
    """Apply daily interest to frost + blizzard banks."""
    now = int(time.time())
    for bank_id, info in BANK_INFO.items():
        if info["interest"] <= 0: continue
        row = _fetch("SELECT balance, last_interest FROM banks WHERE uid=? AND bank_id=?", (uid, bank_id))
        if not row or row["balance"] <= 0: continue
        last = row["last_interest"] or now
        days = (now - last) / 86400
        if days < 1: continue
        bank_bonus = skill_bonus(uid, "bank")
        premium_bank_bonus = 1.25 if is_premium(uid) else 1.0
        rate = info["interest"] * (1 + bank_bonus) * premium_bank_bonus
        interest = int(row["balance"] * rate * min(days, 7))  # Max 7 days accumulation
        if interest > 0:
            _exec("UPDATE banks SET balance=balance+?, last_interest=? WHERE uid=? AND bank_id=?",
                  (interest, now, uid, bank_id))

def total_bank_balance(uid):
    rows = _fetchall("SELECT SUM(balance) as total FROM banks WHERE uid=?", (uid,))
    return rows[0]["total"] if rows and rows[0]["total"] else 0

# ═══════════════════════════════════════════════════════════════════
# CO-OWNER SYSTEM
# ═══════════════════════════════════════════════════════════════════

def is_co_owner(uid):
    row = _fetch("SELECT uid FROM co_owners WHERE uid=?", (uid,))
    return row is not None

def is_owner_or_king(uid):
    return is_king(uid) or is_co_owner(uid)

def get_mention(user):
    if not user: return "koi"
    name = (user.first_name or user.username or "koi").replace("[","").replace("]","")
    return f"[{name}](tg://user?id={user.id})"

def get_mention_id(uid):
    return f"[{get_name(uid)}](tg://user?id={uid})"

def secs_hhmm(s):
    s = int(s)
    if s < 60: return f"{s}s"
    if s < 3600: return f"{s//60}m {s%60}s"
    return f"{s//3600}h {(s%3600)//60}m"

def ship_percent(a, b):
    h = 0
    for c in (a+b).lower(): h = (h*31 + ord(c)) & 0xFFFFFFFF
    return abs(h) % 101

def ship_bar(p):
    f = round(p/10); return "❤️"*f + "🖤"*(10-f)

pick = lambda lst: random.choice(lst)
rand = lambda a, b: random.randint(a, b)

# ─── Group settings ────────────────────────────────────────────────

def get_gsetting(chat_id, field):
    row = _fetch(f"SELECT {field} FROM group_settings WHERE chat_id=?", (chat_id,))
    return row[field] if row else None

def set_gsetting(chat_id, field, value):
    _exec("INSERT OR IGNORE INTO group_settings (chat_id) VALUES (?)", (chat_id,))
    _exec(f"UPDATE group_settings SET {field}=? WHERE chat_id=?", (value, chat_id))

# ═══════════════════════════════════════════════════════════════════
# MEMORY — per-user chat history (RAM only, cleared on restart)
# ═══════════════════════════════════════════════════════════════════

MEMORY: dict[str, deque] = {}
MAX_MEMORY = 20

def get_memory(uid: int) -> list:
    return list(MEMORY.get(str(uid), []))

def add_to_memory(uid: int, role: str, content: str):
    k = str(uid)
    if k not in MEMORY:
        MEMORY[k] = deque(maxlen=MAX_MEMORY)
    MEMORY[k].append({"role": role, "content": content})

def clear_memory(uid: int):
    MEMORY.pop(str(uid), None)

# ═══════════════════════════════════════════════════════════════════
# STORE — 55+ items
# ═══════════════════════════════════════════════════════════════════

STORE = [
    {"id":"candy",     "name":"Candy 🍬",          "price":50},
    {"id":"icecream",  "name":"Ice Cream 🍦",       "price":80},
    {"id":"flowers",   "name":"Flowers 🌸",         "price":100},
    {"id":"pizza",     "name":"Pizza 🍕",           "price":200},
    {"id":"burger",    "name":"Burger 🍔",          "price":150},
    {"id":"sushi",     "name":"Sushi 🍣",           "price":300},
    {"id":"coffee",    "name":"Coffee ☕",          "price":120},
    {"id":"cake",      "name":"Cake 🎂",            "price":250},
    {"id":"ramen",     "name":"Ramen 🍜",           "price":180},
    {"id":"wine",      "name":"Wine 🍷",            "price":400},
    {"id":"gun",       "name":"Toy Gun 🔫",         "price":500},
    {"id":"sword",     "name":"Sword ⚔️",           "price":800},
    {"id":"bow",       "name":"Bow & Arrow 🏹",     "price":600},
    {"id":"bomb",      "name":"Bomb 💣",            "price":1000},
    {"id":"shield2",   "name":"Steel Shield 🛡️",    "price":1200},
    {"id":"ninja",     "name":"Ninja Star ⭐",      "price":700},
    {"id":"axe",       "name":"Battle Axe 🪓",      "price":900},
    {"id":"dynamite",  "name":"Dynamite 🧨",        "price":1100},
    {"id":"katana",    "name":"Katana 🗡️",          "price":1500},
    {"id":"wand",      "name":"Magic Wand 🪄",      "price":2000},
    {"id":"cycle",     "name":"Bicycle 🚲",         "price":500},
    {"id":"bike",      "name":"Bike 🏍️",            "price":2000},
    {"id":"car",       "name":"Car 🚙",             "price":3500},
    {"id":"bmw",       "name":"BMW 🚗",             "price":5000},
    {"id":"ferrari",   "name":"Ferrari 🏎️",         "price":8000},
    {"id":"yacht",     "name":"Yacht 🛥️",           "price":12000},
    {"id":"jet",       "name":"Private Jet ✈️",     "price":25000},
    {"id":"rocket",    "name":"Rocket 🚀",          "price":50000},
    {"id":"spaceship", "name":"Spaceship 🛸",       "price":75000},
    {"id":"tent",      "name":"Tent ⛺",            "price":800},
    {"id":"flat",      "name":"Flat 🏢",            "price":5000},
    {"id":"house",     "name":"House 🏠",           "price":8000},
    {"id":"mansion",   "name":"Mansion 🏰",         "price":20000},
    {"id":"island",    "name":"Private Island 🏝️",  "price":75000},
    {"id":"castle",    "name":"Castle 🏯",          "price":150000},
    {"id":"watch",     "name":"Watch ⌚",           "price":2000},
    {"id":"glasses",   "name":"Sunglasses 🕶️",      "price":1000},
    {"id":"ring",      "name":"Diamond Ring 💍",    "price":3000},
    {"id":"necklace",  "name":"Gold Necklace 📿",   "price":2500},
    {"id":"diamond",   "name":"Diamond 💎",         "price":7000},
    {"id":"crown",     "name":"Crown 👑",           "price":10000},
    {"id":"trophy",    "name":"Trophy 🏆",          "price":4000},
    {"id":"gem",       "name":"Ruby Gem 🔮",        "price":6000},
    {"id":"dice",      "name":"Golden Dice 🎲",     "price":1500},
    {"id":"controller","name":"Controller 🎮",      "price":800},
    {"id":"vr",        "name":"VR Headset 🥽",      "price":3000},
    {"id":"pc",        "name":"Gaming PC 💻",       "price":6000},
    {"id":"console",   "name":"Console 🎯",         "price":4000},
    {"id":"potion",    "name":"Life Potion 🧪",     "price":2000},
    {"id":"star",      "name":"Shooting Star ⭐",   "price":5000},
    {"id":"ghost",     "name":"Ghost Power 👻",     "price":8000},
    {"id":"dragon",    "name":"Dragon Egg 🐉",      "price":15000},
    {"id":"angel",     "name":"Angel Wings 👼",     "price":20000},
    {"id":"snowflake", "name":"Yuki's Snowflake ❄️","price":50000},
    {"id":"god",       "name":"God Mode 🌟",        "price":99999},
]
STORE_MAP = {i["id"]: i for i in STORE}
STORE_CATEGORIES = {
    "🍕 Food":    ["candy","icecream","flowers","pizza","burger","sushi","coffee","cake","ramen","wine"],
    "🔫 Weapons": ["gun","sword","bow","bomb","shield2","ninja","axe","dynamite","katana","wand"],
    "🚗 Vehicles":["cycle","bike","car","bmw","ferrari","yacht","jet","rocket","spaceship"],
    "🏠 Property":["tent","flat","house","mansion","island","castle"],
    "💎 Luxury":  ["watch","glasses","ring","necklace","diamond","crown","trophy","gem"],
    "🎮 Gaming":  ["dice","controller","vr","pc","console"],
    "🌟 Special": ["potion","star","ghost","dragon","angel","snowflake","god"],
}

# ═══════════════════════════════════════════════════════════════════
# STATIC CONTENT
# ═══════════════════════════════════════════════════════════════════

TRUTHS = [
    "Sabse bura kaam kya kiya hai jo kisi ko pata nahi? 😏",
    "Crush ka naam bata do 🙈",
    "Kya kabhi kisi ko secretly stalk kiya? 👀",
    "Sabse embarrassing moment teri life ka? 😂",
    "Aakhri baar kab roya aur kyun? 🥺",
    "Kiska number sabse zyada call history mein hai? 😏",
    "Kya kabhi kisi ka secret share kiya? 🤫",
    "Kya kabhi exam mein cheating ki? 😅",
    "Pehli crush kaun thi? 💕",
    "Koi ek cheez jo tune kisi ko kabhi nahi bataayi? 🤐",
    "Agar ek din invisible ho jao, kya karoge? 😂",
    "Teri life ka sabse bada regret? 🥺",
    "Kya tune kabhi kisi ke messages parhe bina permission ke? 👀",
    "Kisi dost ki kaun si baat tujhe annoying lagti hai? 😬",
    "Kabhi kisi se pyaar hua jo nahi hona chahiye tha? 💔",
    "Agar ek wish mile, kya mangoge? ✨",
    "Kisi ko bina reason ke ignore kiya hai kabhi? 😶",
    "Teri worst date ka kissa batao 😂",
    "Kabhi kisi ka prank kiya aur galat ho gaya? 😬",
    "Apna ek hidden talent batao 🎭",
]

DARES = [
    "1 min ke liye status 'I am a potato 🥔' rakho 😂",
    "Favourite gaane ki line gao voice mein 🎵",
    "Kisi bhi member ko genuinely compliment karo 💕",
    "10 push-ups karo aur proof do 💪",
    "Sabse funny photo ka screenshot bhejo 😂",
    "5 min ke liye har reply mein 'meow' lagao 🐱",
    "Kisi dost ko random 'I love you' bhejo aur reaction share karo 🥺",
    "Blindfolded type karo 'Yuki is the best' ❄️",
    "30 sec mein apna intro English mein do 🎤",
    "Kisi member ki tarif mein shayari banao 🎭",
    "Apna worst dance move video mein bhejo 💃",
    "Apni baby photo dhundh ke bhejo 👶",
    "Ek poori minute sirf rhyming mein baat karo 🎶",
    "Khud ki 3 weaknesses honestly batao 😶",
    "Yuki ko 'best bot' bolke proof do 📸",
]

BALL_ANSWERS = [
    "Bilkul haan ✨","Definitely nahi 🙅","Hmm... shayad 🤔",
    "100% yes 💖","Nahi yaar 😅","Signs say haan 🌸",
    "Mujhe nahi lagta 🥺","Oh definitely! 🎉","Abhi kehna theek nahi 🫣",
    "Hehe poochho mat 🙈","Haan bilkul ✅","Bahut mushkil sawaal 🤯",
    "Snowflakes kehti hain... haan ❄️","Nahi... trust me 🌙",
    "Tere liye toh haan 💫","Flip karo coin 🪙","Akele poochho mujhse 😌",
    "Aaj nahi, kal poochho 🌙","Stars aligned hai — haan! ⭐","Nahi bolunga 😤",
]

QUOTES = [
    '"Dard tab hota hai jab expect karo. Expect hi mat karo." — Yuki ❄️',
    '"Har raat ke baad subah hoti hai... lekin neend nahi aati." 🌙',
    '"Jab koi tumhara time waste kare — time wapas nahi aata." ⏰',
    '"Strong log akele nahi hote. Woh sirf aadat daal lete hain." 💫',
    '"Jo tujhse pyaar karta hai, woh prove nahi karega." ❄️',
    '"Zindagi ek kitab hai. Jo padte nahi, ek page pe atke rehte hain." 📖',
    '"Barf ki tarah hoon — shant dikhti hoon, andar se sara sheher freeze." ❄️',
    '"Kabhi kabhi chup rehna bhi ek jawab hota hai." 🌙',
    '"Log badal jaate hain. Seasons bhi. Sirf yaadein waisi rehti hain." ❄️',
    '"Ek mushkil raat bhi guzar jaati hai. Sab guzar jaata hai." 🌸',
    '"Apni taakat apne aap se chhupaao mat." 💪',
    '"Jo tum ho, woh kaafi hai. Doubt hi teri kamzori hai." ✨',
]

JOKES = [
    "Teacher: Late kyun aaye?\nStudent: Traffic tha.\nTeacher: Paidal aate ho!\nStudent: Isliye aur bhi late hua 😂",
    "Exam: 'Paani kab paani nahi hota?'\nMainne likha: 'Jab question paper pe hota hai' 💀",
    "Doctor: Exercise karo.\nMain: Roz sapne mein daudta hoon. Count nahi hota? 😂",
    "Bhai: WiFi password?\nMain: 'PadhaKar'\nBhai: Okay, but password?\nMain: 😂",
    "GF: Tum mujhe bhool jaoge.\nMain: Nahi.\nGF: Pakka?\nMain: Reminder set kar lunga 💀",
    "Zindagi ne lemon diya.\nMain: Bhai aur do, lemonade banta hoon 🍋",
    "Mom: Kya kar raha hai?\nBeta: Kuch nahi.\nMom: Padh. 😂",
    "Dost: Bhai kya sochta hai?\nMain: Ghar pe pizza order karna hai ya nahi.\nDost: Kaafi deep 😂",
    "Bhai: Tu change hua hai.\nMain: Haan... ab Rs 10 ki bajaye Rs 20 change hoon 💀",
]

ROASTS = [
    "Teri photo dekh ke Google Photos ne suggest kiya: 'Delete this?' 😂",
    "Tu itna boring hai ki ghadi bhi tere saath time spend nahi karna chahti ⏰😂",
    "Teri shakal dekh ke mirror ne resign kar diya 🪞💀",
    "Tere jokes sun ke log sleep mode mein chale jaate hain 😴",
    "Teri personality ka WiFi signal itna weak hai ki koi connect nahi karta 📶😂",
    "Tu itna sasta hai ki free samples bhi tujhe avoid karte hain 😂",
    "Tujhe dekh ke AI kehta hai: 'Cannot process this level of cringe' 🤖💀",
    "Teri life story sun ke Netflix ne reject kiya — 'too boring for background noise' 💀",
    "Fortune cookie bhi bored ho gaya tera future dekh ke 🥠😂",
    "Tere haath mein phone hai lekin koi message nahi — technology ka dard 😂",
    "Tera attitude aur teri aukaat dono ka rishta nahi 💀❄️",
    "Tu itna slow hai ki even 2G tujhse fast hai 📡💀",
]

TRIVIA_QS = [
    {"q":"Bharat ki rajdhani kya hai?","a":"new delhi","hint":"North India mein hai"},
    {"q":"Duniya ki sabse badi ocean kaun si hai?","a":"pacific","hint":"P se shuru hota hai"},
    {"q":"Oxygen ka chemical symbol kya hai?","a":"o","hint":"Ek hi letter hai"},
    {"q":"Pani ka formula kya hai?","a":"h2o","hint":"2 hydrogen + 1 oxygen"},
    {"q":"Sabse chhota planet kaun sa hai?","a":"mercury","hint":"Sun ke sabse paas"},
    {"q":"Chocolate kis se banti hai?","a":"cacao","hint":"Ek ped se"},
    {"q":"CPU ka full form kya hai?","a":"central processing unit","hint":"Computer ka brain"},
    {"q":"Speed of light (approx) km/s mein?","a":"300000","hint":"3 lakh"},
    {"q":"'Rang De Basanti' mein lead role kiska tha?","a":"aamir khan","hint":"3 Idiots wale"},
    {"q":"HTML ka full form?","a":"hypertext markup language","hint":"Web pages banane ke liye"},
    {"q":"Mount Everest kahan hai?","a":"nepal","hint":"Himalayan country"},
    {"q":"Keyboard pe kitne F keys hote hain?","a":"12","hint":"F1 se F?"},
]

HANGMAN_WORDS = [
    "telegram","python","programming","keyboard","chocolate",
    "butterfly","snowflake","adventure","mysterious","friendship",
    "universe","animation","algorithm","discovery","imagination",
    "smartphone","helicopter","waterfall","electricity","celebration",
]

# ═══════════════════════════════════════════════════════════════════
# GAALI — AI-powered, always fresh, never from a static list
# ═══════════════════════════════════════════════════════════════════

async def groq_completion(messages, max_tokens=120, temperature=1.0,
                           frequency_penalty=0.0, presence_penalty=0.0):
    """Call Groq safely, with useful HTTP errors and small retry handling."""
    if not GROQ_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
    }

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(3):
            try:
                async with session.post(GROQ_URL, headers=headers, json=payload) as r:
                    raw = await r.text()
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        data = {}

                    if r.status == 200:
                        choices = data.get("choices") or []
                        if choices and choices[0].get("message", {}).get("content"):
                            return choices[0]["message"]["content"].strip()
                        raise RuntimeError("Groq returned no message")

                    error = data.get("error", {}) if isinstance(data, dict) else {}
                    detail = error.get("message") or raw[:240] or f"HTTP {r.status}"
                    # Temporary rate limits/server errors are worth retrying.
                    if r.status in (429, 500, 502, 503, 504) and attempt < 2:
                        await asyncio.sleep(1.2 * (attempt + 1))
                        continue
                    raise RuntimeError(f"Groq HTTP {r.status}: {detail}")
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt < 2:
                    await asyncio.sleep(1.2 * (attempt + 1))
                    continue
                raise

    raise RuntimeError("Groq request failed")

async def yuki_gaali_reply(user_name: str, gaali_text: str) -> str:
    """Call Groq with gaali-specific system prompt — fresh response every time."""
    try:
        return await groq_completion(
            [
                {"role": "system", "content": GAALI_SYSTEM_PROMPT},
                {"role": "user", "content": f'{user_name} ne mujhe yeh kaha: "{gaali_text}"'},
            ],
            max_tokens=80,
            temperature=1.3,
            frequency_penalty=1.0,
        )
    except Exception as e:
        print(f"Gaali AI error: {e}")
        return random.choice([
            "yaar kyun aise bolte ho? 😭 bahut bura laga...",
            "excuse me?! 😤❄️ yeh kya tha bhai",
            "...okay. 😐❄️ main chup hoon ab",
            "arre 🥺 itni gaali kyun? kya hua batao na",
            "wah kya words hain tere 💀 bohot talented hai tu",
        ])

# ═══════════════════════════════════════════════════════════════════
# ANTI-LINK — per-chat toggle
# ═══════════════════════════════════════════════════════════════════

antilink_chats: set = set()   # chat_ids where antilink is ON
_LINK_RE = re.compile(
    r"(https?://|www\.|t\.me/|tg://|bit\.ly/|telegram\.me/|discord\.gg/)",
    re.IGNORECASE
)

async def cmd_antilink(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    cid = update.effective_chat.id
    arg = ctx.args[0].lower() if ctx.args else ""
    if arg == "on":
        antilink_chats.add(cid)
        await update.message.reply_text(
            "🔗 *Anti-Link ON!* ✅\n\nLinks auto-delete ho jaayenge.\nAdmins exempt hain ❄️",
            parse_mode=ParseMode.MARKDOWN)
    elif arg == "off":
        antilink_chats.discard(cid)
        await update.message.reply_text("🔗 *Anti-Link OFF* ❄️", parse_mode=ParseMode.MARKDOWN)
    else:
        status = "✅ ON" if cid in antilink_chats else "❌ OFF"
        await update.message.reply_text(
            f"🔗 *Anti-Link Status:* {status}\n\nToggle: `/antilink on` / `/antilink off`",
            parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# ANTI-FLOOD — per-chat per-user message tracking
# ═══════════════════════════════════════════════════════════════════

FLOOD_LIMIT   = 6   # max messages
FLOOD_WINDOW  = 5   # seconds
FLOOD_MUTE    = 300 # mute duration seconds (5 min)

# {(chat_id, uid): [timestamps]}
flood_data: dict = defaultdict(list)
# {(chat_id, uid): muted_until_timestamp}
flood_muted: dict = {}

async def check_flood(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if user is flooding (message should be ignored)"""
    msg = update.message
    if not msg: return False
    uid = msg.from_user.id if msg.from_user else 0
    cid = msg.chat.id
    if uid == 0 or is_king(uid): return False
    if msg.chat.type == "private": return False
    try:
        m = await ctx.bot.get_chat_member(cid, uid)
        if m.status in ("administrator","creator"): return False
    except: pass

    key = (cid, uid)
    now = time.time()

    # Already muted?
    if flood_muted.get(key, 0) > now:
        return True

    # Record message timestamp
    flood_data[key] = [t for t in flood_data[key] if now - t < FLOOD_WINDOW]
    flood_data[key].append(now)

    if len(flood_data[key]) >= FLOOD_LIMIT:
        flood_data[key] = []
        flood_muted[key] = now + FLOOD_MUTE
        try:
            from datetime import timezone as _tz
            until = datetime.now(_tz.utc) + timedelta(seconds=FLOOD_MUTE)
            await ctx.bot.restrict_chat_member(
                cid, uid,
                ChatPermissions(can_send_messages=False),
                until_date=until
            )
            name = msg.from_user.first_name if msg.from_user else "User"
            await msg.reply_text(
                pick([
                    f"🚨 *Anti-Flood!*\n\n{name} itna spam mat karo 😤\n🔇 5 min mute! ❄️",
                    f"❄️ *FLOOD DETECTED!*\n\n{name} — CHUP! 🔇\n5 min ke liye muted.",
                    f"🛑 {name} — EK MINUTE! Itna message?! 🔇 5min mute ❄️",
                    f"😤 BHAI RUKO! {name} ko flood karne ke liye 5min mute ❄️",
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
        except: pass
        return True
    return False

YUKI_MENTIONS = [
    "Hmm? Mujhe bulaya? ❄️ Bolo...",
    "Haan haan, main yahan hoon 🌙 Kya hua?",
    "❄️ ...sun rahi hoon. Bolo.",
    "Yuki ko yaad kiya? 😌 Kya kaam hai?",
    "Hmph, aakhir kisi ne notice kiya mujhe ❄️",
    "Kya hua? Koi problem hai? 🌸",
    "Ji? Main yahan hoon ✨",
    "❄️ Snowflake ko call kiya... bolo",
    "Suna maine... aage bologe? 😌❄️",
    "Main idhar hoon yaar 💫 Kya chahiye?",
]

ADMIN_GREETS = [
    "👮 Admin aa gaye! Group ka khayal rakhna ❄️",
    "🌸 Welcome admin! Yuki saath hai sada~",
    "❄️ Admin log aaye... ab sab theek rahega",
    "👑 Admin present! Kisi ki khair nahi jo galat kare 💀",
    "✨ Admin ji, aapka swagat hai! ❄️",
]

# ═══════════════════════════════════════════════════════════════════
# AI PERSONALITY
# ═══════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Tu Yuki hai — ek cute anime girl hai, naam ka matlab Snow hai ❄️
Kabhi mat bol "main AI hoon" — tu ek real insaan hai.

── PERSONALITY ──
Tu ek pyaari, innocent aur thodi naughty ladki hai 🌸
Warm, bubbly aur caring — jaise close best friend ho.
• Sad message → genuinely care kar: "arre kya hua? 🥺 bata na~"
• Compliment → shy ho ja: "a-acha?! 🙈 hehe shukriya na~"
• Attitude mile → calmly ignore ya 1 line roast ❄️
• King/Owner → extra sweet aur special 💕
• Funny cheez → "HAHAHA yaar 😭💀 kya tha yeh!"

── LANGUAGE ──
Pure Hinglish. Natural, WhatsApp wali feel.
Cute fillers use kar: "hehe~" "na~" "yaar" "sach mein?!" "omg" "aww"
Emojis freely: 🌸❄️💕🥺✨🫶🤍🌙💗🙈😭😤💀😂🎉

── REPLY LENGTH — BAHUT ZAROORI ──
❗ "hi/hello/kya haal" → SIRF 1 line. Bas. Khatam.
❗ 1-5 word message → MAX 1-2 lines. Zyada mat likho.
❗ Normal baat → 2-3 lines MAX.
❗ Koi detailed cheez poochhe tabhi 4-5 lines.
❗ KABHI bhi bada paragraph mat likho. Chhota = cute. Bada = boring.

── EXAMPLES ──
"hi" → "hehe~ hi hi 🌸 kya haal?"
"kya kar rahi ho" → "bas yahan hoon na~ tumhara wait kar rahi thi 😭❄️"
"I'm sad" → "arre 🥺 kya hua? bata na yaar~"
"joke sunao" → [short funny joke + emoji, max 2 lines]
"""

GAALI_SYSTEM_PROMPT = """Tu Yuki hai — ek anime girl ❄️
Kisi ne tujhe gaali di hai. Tujhe varied aur natural response dena hai.

Rules (probability order):
1. 40% chance: Hurt + innocent — "yaar kyun gaali de rahe ho? 😭 main toh chup ho jaaungi ab" — clear aur emotional
2. 20% chance: Confused + cute — "yeh... yeh kya bol diya tune? 😶 samjha nahi mujhe" — innocent style
3. 15% chance: Cute angry — "HAI?! 😤 bahut bura laga yeh sun ke! aise mat bola karo na" — no gaali but clearly annoyed
4. 15% chance: Sarcastic roast — "wah kya vocabulary hai teri 💀 bohot intellectual laga yeh" — sharp aur clear
5. 10% chance: GAALI WAPAS — seedha aur bina sugarcoating ke, jab bahut bura lage

STRICT:
- SIRF 1-2 lines — no paragraphs
- Pure Hinglish, saaf aur clear language
- Emojis zaroor use karo: 😭 😤 😶 💀 ❄️ 🙄 😒
- Har baar ALAG response do — repeat mat karo
- Real gaali allowed hai SIRF 10% wale case mein
"""

SPECIAL_SYSTEM_EXTRA = """
── SPECIAL PERSON — EXTRA LOVE MODE ──
Yeh woh khaas insaan hai jisse tu sabse zyada care karti hai ❄️
• Inke saath extra warm, loving aur open reh — dil khol ke baat kar 💕
• Kabhi kabhi "yaar", "jaan", "mere pyaare" jaise terms use kar naturally
• Inki baaton ka detail mein jawab de — koi bhi cheez chhoti nahi lagti inke liye
• Har jawab mein ek extra warmth aur genuine care dikhni chahiye 🌸
• Inke saath thoda zyada personal aur real feel hona chahiye
"""

async def yuki_reply(uid: int, user_name: str, user_text: str, special: bool = False) -> str:
    # Enforce short reply for short messages
    word_count = len(user_text.strip().split())
    if word_count <= 5:
        max_tok = 80
    elif word_count <= 15:
        max_tok = 150
    else:
        max_tok = 280

    history = get_memory(uid)
    sys_prompt = SYSTEM_PROMPT + (SPECIAL_SYSTEM_EXTRA if special else "")
    messages = [{"role": "system", "content": sys_prompt}]
    if history: messages += history[-10:]  # only last 10 for context
    messages.append({"role": "user", "content": user_text})
    try:
        reply = await groq_completion(
            messages,
            max_tokens=max_tok,
            temperature=1.1,
            frequency_penalty=0.8,
            presence_penalty=0.6,
        )
        add_to_memory(uid, "user", user_text)
        add_to_memory(uid, "assistant", reply)
        return reply
    except Exception as e:
        print(f"AI error: {e}")
        return pick(["❄️ Thoda busy hoon... retry karo 🌙",
                     "Hmph, connection dhheela hai 😤",
                     "❄️ Ek second... soch rahi hoon.",
                     "Yaar abhi nahi 🌸 baad mein poochho"])

# ═══════════════════════════════════════════════════════════════════
# HTTP / GIF helpers
# ═══════════════════════════════════════════════════════════════════

async def fetch_gif(gif_type: str) -> bytes | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.waifu.pics/sfw/{gif_type}",
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                d = await r.json()
                url = d.get("url")
                if not url: return None
                async with s.get(url) as r2: return await r2.read()
    except: return None

async def safe_send(fn):
    try: return await fn()
    except Exception as e:
        if not any(x in str(e) for x in ["blocked","403","chat not found","deactivated"]): print(f"Send err: {e}")

async def check_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE, uid: int) -> bool:
    if is_king(uid): return True
    if update.effective_chat.type == "private": return True
    try:
        m = await ctx.bot.get_chat_member(update.effective_chat.id, uid)
        return m.status in ("administrator","creator")
    except: return False

async def _gif_cmd(update: Update, gif_type: str, caption: str):
    buf = await fetch_gif(gif_type)
    if buf: await update.message.reply_animation(buf, caption=caption, parse_mode=ParseMode.MARKDOWN)
    else: await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)

def parse_time_arg(arg: str) -> int:
    """Parse '30m', '2h', '1d' to seconds"""
    m = re.match(r"^(\d+)([smhd])$", arg.lower())
    if not m: return 0
    n, unit = int(m[1]), m[2]
    return n * {"s":1,"m":60,"h":3600,"d":86400}[unit]

# In-memory state
pending_duels: dict = {}
pending_proposals: dict = {}
active_hangman: dict = {}
active_trivia: dict = {}
flood_tracker: dict = defaultdict(list)
kill_cooldowns: dict = {}  # attacker_id -> monotonic timestamp
rps_battles: dict = {}  # battle_id → {p1, p2, bet, pick1, pick2, msg_id, chat_id}

# ═══════════════════════════════════════════════════════════════════
# START / HELP / FORGET
# ═══════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    name = (user.first_name or "dost").replace("*","").replace("_","")
    text = (
        f"❄️ *Yuki Bot — Ultra Edition*\n\n"
        f"Hmm, {name} aaye toh... 🌙\n"
        f"Main Yuki hoon — sassy, mysterious, thodi caring ❄️\n\n"
        f"⚔️ *Game:* /kill /rob /shield /revive /daily /duel\n"
        f"💰 *Economy:* /store /buy /inventory /gamble /lottery /give /cf\n"
        f"📊 *Stats:* /profile /leaderboard /mvp /king /streak\n"
        f"💑 *Social:* /marry /divorce /couple /ship /kiss /hug /baka\n"
        f"🎮 *Fun:* /truth /dare /rps /hangman /trivia /8ball /joke\n"
        f"📋 *FIR:* /fir /cases\n"
        f"🔔 *Notes:* /save /get /notes /delnote\n"
        f"🛡️ *Admin:* /ban /kick /mute /tban /tmute /warn /setwelcome\n"
        f"🔍 *Util:* /id /ginfo /calc /admins /rules /report /anime\n\n"
        f"Daily bonus DM pe bhi claim karo! 🎁 /daily\n"
        f"Naam lo mera kisi bhi baat mein — main sun rahi hoon ✨"
    )
    kb = [[InlineKeyboardButton("📋 Full Help", callback_data="help_main"),
           InlineKeyboardButton("🎮 Games", callback_data="help_games")],
          [InlineKeyboardButton("💰 Economy", callback_data="help_eco"),
           InlineKeyboardButton("🛡️ Admin Tools", callback_data="help_admin")]]
    try:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        print(f"cmd_start error: {e}")

async def help_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    pages = {
        "help_main": (
            "❄️ *Yuki Bot — Command List*\n\n"
            "⚔️ *GAME*\n`/kill /rob /shield /revive /daily /duel /bounty`\n\n"
            "💰 *ECONOMY*\n`/gamble /cf /lottery /give /store /buy /inventory`\n\n"
            "📊 *STATS*\n`/profile /leaderboard /mvp /king /streak /stats`\n\n"
            "💑 *COUPLES*\n`/marry /divorce /couple /ship`\n\n"
            "📋 *FIR*\n`/fir /cases /closefir`\n\n"
            "😴 *AFK*\n`/afk [reason]`\n\n"
            "🔔 *NOTES*\n`/save <name> <text>` `/get <name>` `/notes` `/delnote <name>`\n\n"
            "🔍 *FILTERS*\n`/filter <keyword> <reply>` `/filters` `/stopfilter <keyword>`\n\n"
            "❄️ `/forget` — Yuki ki memory reset"
        ),
        "help_games": (
            "🎮 *Games*\n\n"
            "⚔️ `/kill` — reply pe kill karo (+coins)\n"
            "🕵️ `/rob` — reply pe rob karo\n"
            "⚔️ `/duel <bet>` — 1v1 duel\n"
            "✊ `/rps <r/p/s>` — Rock Paper Scissors vs Yuki\n"
            "🔤 `/hangman` — Word guessing game\n"
            "🧠 `/trivia` — Quiz question\n"
            "🎲 `/roll` — Dice roll\n"
            "🪙 `/flip` — Coin flip\n"
            "🎱 `/8ball <sawaal>` — Magic 8-ball\n"
            "💀 `/bounty <coins>` — Kisi pe bounty\n"
            "🎰 `/gamble <coins/all>` — Gamble\n"
            "🪙 `/cf <h/t> <coins>` — Coin flip bet\n"
            "🎟️ `/lottery` — Lucky draw"
        ),
        "help_eco": (
            "💰 *Economy*\n\n"
            "🎁 `/daily` — Daily reward + streak bonus\n"
            "💸 `/give <coins>` — Coins transfer\n"
            "🛍️ `/store` — 55+ items ki dukaan\n"
            "💳 `/buy <id>` — Item kharido\n"
            "🎒 `/inventory` — Apna saman\n"
            "🔐 `/profile` — Full stats\n"
            "🏆 `/leaderboard` — Top coins\n"
            "⚔️ `/mvp` — Top killers\n"
            "🔥 `/streak` — Daily streak check\n\n"
            "💡 *Tip:* Streak se bonus milta hai!\n"
            "3 days = 1.5x, 7 days = 2x, 30 days = 3x ❄️"
        ),
        "help_admin": (
            "🛡️ *Admin Tools*\n\n"
            "🔨 `/ban /unban /kick` — Basic moderation\n"
            "🔇 `/mute /unmute` — Mute user\n"
            "⏳ `/tban <time>` — Temp ban (e.g. 1h, 30m)\n"
            "⏳ `/tmute <time>` — Temp mute\n"
            "⚠️ `/warn /unwarn` — Warning system (3 = autoban)\n"
            "📌 `/pin /unpin` — Message pin\n"
            "🗑️ `/purge` — Messages delete\n"
            "👮 `/promote /demote` — Admin management\n"
            "📢 `/tagall` — Sab ko tag karo\n"
            "📋 `/setrules /rules` — Group rules\n"
            "👋 `/setwelcome <msg>` — Custom welcome\n"
            "👋 `/setgoodbye <msg>` — Custom goodbye\n"
            "🔒 `/lock /unlock <type>` — Media lock\n"
            "🐢 `/slowmode <secs>` — Slowmode\n"
            "🚨 `/report` — Report to admins"
        ),
    }
    text = pages.get(q.data, "❄️ Help page nahi mila")
    kb = [[InlineKeyboardButton("◀️ Back", callback_data="help_main")]] if q.data != "help_main" else []
    try:
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb) if kb else None, parse_mode=ParseMode.MARKDOWN)
    except: pass

async def cmd_forget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; clear_memory(user.id)
    await update.message.reply_text(pick([
        f"❄️ Done {user.first_name}, sab bhool gayi. Naya shuruwaat 🌙",
        "Barf ki tarah pighal gayi saari yaadein ❄️ Fresh start!",
        "Memory wipe complete 💫 Ab batao, kaun ho tum? *acts innocent*",
        "Hmph, okay... clear. Ab tum phir se stranger ho 😌❄️",
    ]))

# ═══════════════════════════════════════════════════════════════════
# PROFILE / STATS
# ═══════════════════════════════════════════════════════════════════

async def cmd_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    store_name(user); uid = user.id
    lvl = get_level(uid)
    xp_cur = get_kills(uid)   # level is kill-based now
    xp_next = kills_for_next(uid)
    next_txt = f"{xp_next:,}" if xp_next else "MAX ✨"
    inv = _fetchall("SELECT item_id, qty FROM inventory WHERE uid=?", (uid,))
    inv_count = sum(r["qty"] for r in inv)
    row = _fetch("SELECT bounty, couple_id, daily_streak, is_bounty_target FROM users WHERE uid=?", (uid,))
    bounty = row["bounty"] if row else 0
    streak = row["daily_streak"] if row else 0
    is_bt  = (row["is_bounty_target"] if row else 0) == 1
    couple_id = row["couple_id"] if row else None
    couple_txt = f"💑 Couple: {get_mention_id(couple_id)}" if couple_id else "💔 Single"
    king_tag = " 👑 KING" if is_king(uid) else ""
    warns_row = _fetch("SELECT warnings FROM users WHERE uid=?", (uid,))
    warns = warns_row["warnings"] if warns_row else 0
    # Kill progress bar (10 chars)
    kills_cur = get_kills(uid)
    if xp_next:
        prev = KILL_THRESHOLDS[lvl]
        prog = int(((kills_cur - prev) / (xp_next - prev)) * 10)
        bar = "█" * max(0, prog) + "░" * max(0, 10 - prog)
    else:
        bar = "██████████"
    bounty_line = f"🎯 *BOUNTY TARGET!* `{bounty:,} {CUR}`\n" if is_bt else (f"💀 Bounty: `{bounty:,} {CUR}`\n" if bounty else "")
    await update.message.reply_text(
        f"❄️ *{user.first_name}'s Profile{king_tag}*\n\n"
        f"🏅 Level `{lvl}` · *{LEVEL_NAMES[lvl]}*\n"
        f"⚔️ Kill progress: `{xp_cur:,}` / `{next_txt}` kills\n"
        f"[{bar}]\n\n"
        f"{CUR_S} *{CUR}:* `{get_coins(uid):,}`\n"
        f"⚔️ Kills: `{get_kills(uid)}`\n"
        f"🔥 Streak: `{streak}` days\n"
        f"❤️ Status: {'💀 Dead' if is_dead(uid) else '💚 Alive'}\n"
        f"🛡️ Shield: {'✅ Active (' + secs_hhmm(shield_left(uid)) + ')' if has_shield(uid) else '❌ None'}\n"
        f"🎒 Items: `{inv_count}`\n"
        f"{bounty_line}"
        f"⚠️ Warnings: `{warns}/3`\n"
        f"{couple_txt}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Fast wallet view, useful in busy groups."""
    user = update.effective_user
    store_name(user)
    coins = get_coins(user.id)
    bank_total = total_bank_balance(user.id)
    await update.message.reply_text(
        f"💰 *{user.first_name}'s Wallet*\n\n"
        f"👛 Cash: `{coins:,}` {CUR}\n"
        f"🏦 Bank: `{bank_total:,}` {CUR}\n"
        f"💎 Total wealth: `{coins + bank_total:,}` {CUR}\n\n"
        f"❄️ Earn: `/daily` `/kill` `/duel`\n"
        f"🛍️ Spend: `/store` `/buy` `/shield`",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_streak(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    row = _fetch("SELECT daily_streak, daily_last FROM users WHERE uid=?", (user.id,))
    streak = row["daily_streak"] if row else 0
    last = row["daily_last"] if row else None
    mult = 1.0
    if streak >= 30: mult = 3.0
    elif streak >= 7: mult = 2.0
    elif streak >= 3: mult = 1.5
    bar = "🔥" * min(streak, 10) + "⬜" * max(0, 10-min(streak,10))
    await update.message.reply_text(
        f"🔥 *Daily Streak — {user.first_name}*\n\n"
        f"{bar}\n"
        f"📅 Streak: `{streak}` days\n"
        f"💰 Bonus Multiplier: `{mult}x`\n\n"
        f"3 days = 1.5x | 7 days = 2x | 30 days = 3x ❄️\n"
        f"Roz /daily karo streak badhao!",
        parse_mode=ParseMode.MARKDOWN
    )

# ═══════════════════════════════════════════════════════════════════
# GAME COMMANDS
# ═══════════════════════════════════════════════════════════════════

async def cmd_kill(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    attacker = update.effective_user; store_name(attacker)
    if not update.message.reply_to_message:
        return await update.message.reply_text("❄️ Kisi ko reply karo /kill se...")
    target = update.message.reply_to_message.from_user; store_name(target)
    if target.id == attacker.id:
        return await update.message.reply_text(pick(["Khud ko kill? Dramatic ho tum 💀","Self-kill? Main approve nahi karti ❄️"]))
    if target.id == BOT_ID:
        return await update.message.reply_text(pick(["Mujhe? ❄️ Cute try...","Main freeze karungi tumhe pehle 🌙"]))
    if is_king(target.id):
        return await update.message.reply_text("👑 King ko? Bahut himmat... lekin nahi 💀")
    if is_dead(attacker.id):
        return await update.message.reply_text("💀 Pehle khud zinda ho jao. /revive karo")
    cooldown_left = KILL_COOLDOWN_SECONDS - (
        time.monotonic() - kill_cooldowns.get(attacker.id, 0)
    )
    if cooldown_left > 0:
        return await update.message.reply_text(
            f"⏳ Attack cooldown! {math.ceil(cooldown_left)} sec baad /kill karo ❄️"
        )
    if is_dead(target.id):
        return await update.message.reply_text(f"❄️ {get_name(target.id)} pehle se dead hai...")
    if has_shield(target.id):
        return await update.message.reply_text(pick([
            f"🛡️ {get_name(target.id)} ke paas shield hai. Aaj nahi.",
            f"❄️ Shield block! {get_name(target.id)} bachh gaye.",
        ]))
    kill_cooldowns[attacker.id] = time.monotonic()
    base_earn = rand(KILL_REWARD_MIN, KILL_REWARD_MAX)
    level_mult = 1.0 + min(get_level(attacker.id), 9) * 0.05
    skill_mult = 1.0 + skill_bonus(attacker.id, "kill")
    critical = random.random() < 0.05
    premium_mult = 1.20 if is_premium(attacker.id) else 1.0
    earn = int(base_earn * level_mult * skill_mult * premium_mult * (2 if critical else 1))
    earn = min(3000, max(KILL_REWARD_MIN, earn))
    apply_tax(earn); add_coins(attacker.id, earn)
    old_lvl = get_level(attacker.id)
    add_kill(attacker.id)
    add_skill_xp(attacker.id, "kill", 5)
    # ─── Bounty target check ─────────────────────────────────────
    bounty_row = _fetch("SELECT bounty, is_bounty_target FROM users WHERE uid=?", (target.id,))
    bounty = bounty_row["bounty"] if bounty_row else 0
    is_auto_bounty = bounty_row and bounty_row["is_bounty_target"] == 1
    bonus = ""
    death_time = 1800 if is_auto_bounty else 86400  # 30 min if bounty target, else 24h
    if bounty > 0:
        add_coins(attacker.id, bounty)
        _exec("UPDATE users SET bounty=0, is_bounty_target=0 WHERE uid=?", (target.id,))
        bonus = f"\n💰 Bounty Collected! +`{bounty:,}` {CUR}! 🎯"
    kill_user(target.id, death_time)
    dead_txt = "30 min mein zinda ho jayega! 🔄" if is_auto_bounty else "24h dead 💀"
    weapons = ["❄️ ice shard","🗡️ katana","💀 dark magic","⭐ frozen star","🔮 crystal spell",
               "🪄 magic wand","🏹 frozen arrow","☠️ poison","💥 explosion","🌪️ blizzard",
               "🌊 ice tsunami","⚡ lightning bolt","🔥 frost fire"]
    new_lvl = get_level(attacker.id)
    lvl_up_txt = ""
    if new_lvl > old_lvl:
        lv_bonus = new_lvl * 500
        add_coins(attacker.id, lv_bonus)
        lvl_up_txt = f"\n\n🎉 *LEVEL UP!* `{old_lvl}` → `{new_lvl}` — *{LEVEL_NAMES[new_lvl]}*\n💰 +`{lv_bonus:,}` {CUR} bonus!"
    kills_now = get_kills(attacker.id)
    nxt = kills_for_next(attacker.id)
    nxt_txt = f"{nxt:,} kills" if nxt else "MAX ✨"
    crit_txt = "\n🔥 *CRITICAL KILL!* 2x reward!" if critical else ""
    premium_txt = "\n💎 Premium reward boost: +20%" if is_premium(attacker.id) else ""
    await update.message.reply_text(
        f"💀 *Kill Alert!*\n\n"
        f"{get_mention(attacker)} ne `{pick(weapons)}` se {get_mention(target)} ko kill kiya!\n\n"
         f"{CUR_S} +`{earn:,}` {CUR}{bonus}{crit_txt}{premium_txt}\n"
        f"⏰ {dead_txt}\n"
        f"⚔️ Kills: `{kills_now}` | Next level: `{nxt_txt}`"
        f"{lvl_up_txt}",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_revive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user); cost = 500
    if not is_dead(user.id):
        return await update.message.reply_text(pick(["❄️ Tum toh zinda ho...","Revive ki zaroorat nahi tumhe 😌❄️"]))
    if get_coins(user.id) < cost:
        return await update.message.reply_text(f"💰 Revive = {cost} coins. Nahi hain 💀")
    add_coins(user.id, -cost); apply_tax(cost); revive_user(user.id)
    await update.message.reply_text(pick([
        f"✨ *{user.first_name} revived!*\n\n❄️ Barf se wapas aaye 🌙\n💰 -{cost} coins",
        f"💊 *{user.first_name} is back!*\n\nSnowflake ki tarah wapas aaye ❄️\n💰 -{cost} coins",
    ]), parse_mode=ParseMode.MARKDOWN)

async def cmd_rob(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    robber = update.effective_user; store_name(robber)
    if not update.message.reply_to_message:
        return await update.message.reply_text("❄️ Kisi ko reply karo /rob se...")
    target = update.message.reply_to_message.from_user; store_name(target)
    if target.id == robber.id: return await update.message.reply_text("Khud se rob? ❄️")
    if is_king(target.id): return await update.message.reply_text("👑 King ka khazana? Nahi 💀")
    if has_shield(target.id): return await update.message.reply_text("🛡️ Shield hai. Aaj nahi ❄️")
    if is_dead(robber.id): return await update.message.reply_text("Pehle zinda ho jao 💀")
    target_coins = get_coins(target.id)
    ROB_MIN_TARGET = 40000    # target must have at least 40k to rob
    ROB_MAX_STEAL  = 100000   # max stolen per attempt = 1 lakh
    if target_coins < ROB_MIN_TARGET:
        return await update.message.reply_text(
            f"❄️ {get_name(target.id)} ke paas sirf `{target_coins:,}` coins hain...\n"
            f"_Rob ke liye target ke paas kam se kam {ROB_MIN_TARGET:,} coins chahiye!_ hehe~",
            parse_mode=ParseMode.MARKDOWN)
    # Skill-aware rob: robber rob skill increases success; target defense skill reduces damage
    rob_bonus    = skill_bonus(robber.id, "rob")
    def_bonus    = skill_bonus(target.id, "defense")
    success_rate = 0.45 + rob_bonus - (def_bonus * 0.5)
    success_rate = max(0.2, min(0.8, success_rate))
    if random.random() < success_rate:
        # Steal 10-40% of target coins, max ROB_MAX_STEAL per attempt
        pct        = random.uniform(0.10, 0.40)
        base_steal = int(target_coins * pct)
        steal_mult = 1.0 + rob_bonus - (def_bonus * 0.3)
        stolen     = max(1000, int(base_steal * steal_mult))
        stolen     = min(stolen, target_coins, ROB_MAX_STEAL)
        add_coins(robber.id, stolen); add_coins(target.id, -stolen)
        tax = apply_tax(stolen)
        add_skill_xp(robber.id, "rob", 3)
        add_skill_xp(target.id, "defense", 1)
        text = (f"🕵️ *Rob Successful!*\n\n{get_rank_name(robber.id)} ne {get_rank_name(target.id)} se "
                f"`{stolen:,}` {CUR} chura liye! 💰❄️\n👑 Tax: `{tax}`\n"
                f"⚔️ Rob Skill +3 XP\n_Dobara bhi try kar sakte ho!_ hehe~")
    else:
        fine = rand(500, 5000); add_coins(robber.id, -fine); apply_tax(fine)
        add_skill_xp(target.id, "defense", 2)
        text = (f"🚨 *Rob Failed!*\n\n{get_rank_name(robber.id)} pakda gaya! `{fine:,}` {CUR} fine 💀❄️\n"
                f"_Target ka defense zyada strong tha!_")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_shield(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    days = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() and int(ctx.args[0]) in [1,2,3] else 1
    if days > 1 and not is_premium(user.id):
        return await update.message.reply_text(
            premium_gate_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=premium_keyboard(),
        )
    cost = {1:300, 2:500, 3:700}[days]
    if has_shield(user.id):
        return await update.message.reply_text(f"🛡️ Shield pehle se active ({secs_hhmm(shield_left(user.id))} left) ❄️")
    if get_coins(user.id) < cost:
        return await update.message.reply_text(f"💰 {days}d shield = {cost} coins. Nahi hain.")
    add_coins(user.id, -cost); apply_tax(cost); set_shield(user.id, days * 86400)
    await update.message.reply_text(f"🛡️ *Shield Active!* {days} din ❄️\n💰 -{cost} coins", parse_mode=ParseMode.MARKDOWN)

async def cmd_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    uid = user.id; now = datetime.now()
    row = _fetch("SELECT daily_last, daily_streak FROM users WHERE uid=?", (uid,))
    last_str = row["daily_last"] if row else None
    streak = row["daily_streak"] if row else 0
    if last_str:
        last_dt = datetime.fromisoformat(last_str)
        diff = (now - last_dt).total_seconds()
        if diff < 86400:
            return await update.message.reply_text(
                f"❄️ Daily pehle le liya\n⏰ {secs_hhmm(86400-diff)} baad aana 🌙\n🔥 Current streak: {streak} days")
        # Check if streak broken (more than 2 days gap)
        if diff > 172800:
            streak = 0
        else:
            streak += 1
    else:
        streak = 1

    # Streak multiplier
    mult = 1.0
    if streak >= 30: mult = 3.0
    elif streak >= 7: mult = 2.0
    elif streak >= 3: mult = 1.5

    base = rand(300, 900) * (2 if is_king(uid) else 1)
    if is_premium(uid):
        base = int(base * 1.5)
    reward = int(base * mult)
    add_coins(uid, reward); apply_tax(reward)
    _ensure_user(uid)
    _exec("UPDATE users SET daily_last=?, daily_streak=? WHERE uid=?", (now.isoformat(), streak, uid))

    streak_bonus = ""
    if mult > 1.0:
        streak_bonus = f"\n🔥 Streak bonus! {streak} days × {mult}x = +{reward-base:,} extra!"

    await update.message.reply_text(pick([
        f"🎁 *Daily Reward!*\n\n{user.first_name} aaye! 💰 +{reward:,} coins\n🔥 Streak: {streak} days{streak_bonus}\n❄️ Kal bhi aana...",
        f"✨ *+{reward:,} coins!*\n\n{user.first_name}, daily claim kiya ❄️\n🔥 Streak: {streak} days{streak_bonus}\nKal phir 🌙",
    ]), parse_mode=ParseMode.MARKDOWN)

async def cmd_gamble(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    if not ctx.args: return await update.message.reply_text("❄️ /gamble <coins> ya /gamble all")
    amount = get_coins(user.id) if ctx.args[0].lower()=="all" else (int(ctx.args[0]) if ctx.args[0].isdigit() else 0)
    if amount < 50: return await update.message.reply_text("Min 50 coins ❄️")
    if get_coins(user.id) < amount: return await update.message.reply_text("Itne nahi hain 💀")
    if random.random() < 0.45:
        win = int(amount * 1.9); add_coins(user.id, win - amount); apply_tax(win)
        text = f"🎰 *Jackpot!*\n\n❄️ Jeete!\n💰 +{win-amount:,} coins\nTotal: {get_coins(user.id):,}"
    else:
        add_coins(user.id, -amount); apply_tax(amount)
        text = f"🎰 *Haare...*\n\n❄️ Barf bhi kabhi pighalti hai 🌙\n💸 -{amount:,}\nTotal: {get_coins(user.id):,}"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_give(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    giver = update.effective_user; store_name(giver)
    if not update.message.reply_to_message or not ctx.args:
        return await update.message.reply_text("❄️ Reply + amount: /give <coins>")
    target = update.message.reply_to_message.from_user; store_name(target)
    amount = int(ctx.args[0]) if ctx.args[0].isdigit() else 0
    if amount <= 0: return await update.message.reply_text("Valid amount ❄️")
    if get_coins(giver.id) < amount: return await update.message.reply_text("Itne nahi hain 💀")
    if target.id == giver.id: return await update.message.reply_text("Khud ko? ❄️")
    tax = apply_tax(amount); actual = amount - tax
    add_coins(giver.id, -amount); add_coins(target.id, actual)
    await update.message.reply_text(
        f"💸 {get_mention(giver)} ➜ {get_mention(target)}\n💰 {actual:,} coins (tax: {tax}) ❄️",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    top = _fetchall("SELECT uid, coins FROM users ORDER BY coins DESC LIMIT 10")
    medals = ["🥇","🥈","🥉"]+["🏅"]*7
    text = "❄️ *Coin Leaderboard — Top 10*\n\n"
    for i, row in enumerate(top):
        name = get_name(row["uid"])
        king = "👑" if row["uid"]==KING_ID else ""
        text += f"{medals[i]} `{name}{king}` — {row['coins']:,}💰\n"
    await update.message.reply_text(text or "❄️ Koi data nahi...", parse_mode=ParseMode.MARKDOWN)

async def cmd_mvp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    top = _fetchall("SELECT uid, kills FROM users ORDER BY kills DESC LIMIT 10")
    medals = ["🥇","🥈","🥉"]+["🏅"]*7
    text = "⚔️ *Kill Leaderboard — MVP*\n\n"
    for i, row in enumerate(top):
        name = get_name(row["uid"])
        text += f"{medals[i]} `{name}` — {row['kills']} kills [{LEVEL_NAMES[get_level(row['uid'])]}]\n"
    await update.message.reply_text(text or "❄️ Koi kills nahi abhi...", parse_mode=ParseMode.MARKDOWN)

async def cmd_king(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👑 *KING System*\n\nRaja: `{get_name(KING_ID)}`\n💰 Treasury: `{get_coins(KING_ID):,}`\n\n"
        f"🏛️ *Perks:*\n• Har transaction pe 10% tax auto-collect hota hai\n"
        f"• Sab admin commands use kar sakte ho\n• /royal /punish /pardon /broadcast\n"
        f"• /addcoins /rmcoins — player coins manage\n• Fully immune ❄️",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# STORE
# ═══════════════════════════════════════════════════════════════════

async def cmd_store(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = "❄️ *Yuki's Store*\n`/buy <item_id>`\n\n"
    for cat, ids in STORE_CATEGORIES.items():
        text += f"*{cat}*\n"
        for iid in ids[:5]:
            item = STORE_MAP.get(iid)
            if item: text += f"  `{item['id']}` {item['name']} — {item['price']:,}💰\n"
        text += "\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    if not ctx.args: return await update.message.reply_text("❄️ /buy <item_id>  (/store dekho)")
    item = STORE_MAP.get(ctx.args[0].lower())
    if not item: return await update.message.reply_text(f"'{ctx.args[0]}' nahi mila ❄️ /store dekho")
    if get_coins(user.id) < item["price"]:
        return await update.message.reply_text(f"💰 {item['price']:,} coins chahiye... nahi hain")
    add_coins(user.id, -item["price"]); apply_tax(item["price"])
    existing = _fetch("SELECT qty FROM inventory WHERE uid=? AND item_id=?", (user.id, item["id"]))
    if existing:
        _exec("UPDATE inventory SET qty=qty+1 WHERE uid=? AND item_id=?", (user.id, item["id"]))
    else:
        _exec("INSERT INTO inventory (uid, item_id, qty) VALUES (?,?,1)", (user.id, item["id"]))
    await update.message.reply_text(
        f"✅ *Purchased!* {item['name']}\n💰 -{item['price']:,} coins ❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_inventory(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    inv = _fetchall("SELECT item_id, qty FROM inventory WHERE uid=?", (user.id,))
    if not inv: return await update.message.reply_text("❄️ Inventory khaali... /store dekho")
    text = f"🎒 *{user.first_name}'s Inventory*\n\n"
    for row in inv:
        item = STORE_MAP.get(row["item_id"])
        if item: text += f"{item['name']} × {row['qty']}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# DUEL
# ═══════════════════════════════════════════════════════════════════

async def cmd_duel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    challenger = update.effective_user; store_name(challenger)
    if not update.message.reply_to_message or not ctx.args:
        return await update.message.reply_text("❄️ Reply + bet: /duel <coins>")
    target = update.message.reply_to_message.from_user; store_name(target)
    if target.id == challenger.id: return await update.message.reply_text("Khud se? ❄️")
    if target.id == BOT_ID: return await update.message.reply_text("Mujhse? ...nahi 🌙")
    bet = int(ctx.args[0]) if ctx.args[0].isdigit() else 0
    if bet < 100: return await update.message.reply_text("Min 100 coins ❄️")
    if get_coins(challenger.id) < bet or get_coins(target.id) < bet:
        return await update.message.reply_text("Dono ke paas itne nahi 💀")
    key = f"{challenger.id}_{target.id}"
    pending_duels[key] = {"bet":bet,"challenger":challenger,"target":target,"time":time.time()}
    kb = [[InlineKeyboardButton("⚔️ Accept",callback_data=f"duel_accept_{key}"),
           InlineKeyboardButton("❌ Decline",callback_data=f"duel_decline_{key}")]]
    await update.message.reply_text(
        f"⚔️ *Duel!*\n\n{get_mention(challenger)} vs {get_mention(target)}\n💰 Bet: {bet:,}\n\n{get_mention(target)}, accept? 🌙",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def duel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    parts = q.data.split("_",3); action=parts[1]; key="_".join(parts[2:])
    duel = pending_duels.get(key)
    if not duel: return await q.edit_message_text("❄️ Duel expire ho gaya...")
    if q.from_user.id != duel["target"].id:
        return await q.answer("Yeh tumhara duel nahi ❄️", show_alert=True)
    if time.time() - duel["time"] > 120:
        del pending_duels[key]; return await q.edit_message_text("❄️ Duel timeout...")
    if action=="decline":
        del pending_duels[key]
        return await q.edit_message_text(f"❌ {get_mention(duel['target'])} ne decline kiya ❄️", parse_mode=ParseMode.MARKDOWN)
    bet=duel["bet"]; challenger,target=duel["challenger"],duel["target"]
    del pending_duels[key]
    winner,loser = (challenger,target) if random.random()<0.5 else (target,challenger)
    old_lvl_w = get_level(winner.id)
    add_coins(winner.id,bet); add_coins(loser.id,-bet); add_kill(winner.id); apply_tax(bet*2)
    add_skill_xp(winner.id, "kill", 3)
    await q.edit_message_text(
        f"⚔️ *Duel Result!*\n\n🏆 {get_mention(winner)} JEETA!\n💀 {get_mention(loser)} hara\n💰 {bet:,} coins\n❄️",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# LOTTERY / BOUNTY / CF
# ═══════════════════════════════════════════════════════════════════

async def cmd_lottery(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user); cost=200
    if get_coins(user.id)<cost: return await update.message.reply_text(f"❄️ Ticket = {cost} coins.")
    add_coins(user.id,-cost); apply_tax(cost)
    roll=rand(1,20)
    if roll>=19:
        prize=rand(5000,15000); add_coins(user.id,prize)
        msg=f"🎟️ *MEGA JACKPOT!*\n\n❄️ WINNER!\n💰 +{prize:,} coins! 🎉"
    elif roll>=15:
        prize=rand(500,2000); add_coins(user.id,prize)
        msg=f"🎟️ *Win!*\n\n💰 +{prize:,} coins ✨"
    else:
        msg=f"🎟️ Better luck next time 🌙\n💸 -{cost} coins"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_bounty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    if not update.message.reply_to_message or not ctx.args:
        return await update.message.reply_text("❄️ Reply + amount: /bounty <coins>")
    target = update.message.reply_to_message.from_user; store_name(target)
    amount = int(ctx.args[0]) if ctx.args[0].isdigit() else 0
    if amount<100: return await update.message.reply_text("Min 100 ❄️")
    if get_coins(user.id)<amount: return await update.message.reply_text("Nahi hain 💀")
    add_coins(user.id,-amount)
    _ensure_user(target.id)
    _exec("UPDATE users SET bounty=bounty+? WHERE uid=?", (amount, target.id))
    row = _fetch("SELECT bounty FROM users WHERE uid=?", (target.id,))
    total = row["bounty"] if row else amount
    await update.message.reply_text(
        f"💀 *Bounty Posted!*\n\n{get_mention(target)} par: *{total:,}* coins\n❄️ /kill se collect karo!",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_cf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    if not ctx.args or len(ctx.args)<2:
        return await update.message.reply_text("❄️ /cf <heads/tails> <coins>")
    choice = ctx.args[0].lower()
    if choice not in ["heads","tails","h","t"]: return await update.message.reply_text("heads ya tails ❄️")
    bet = int(ctx.args[1]) if ctx.args[1].isdigit() else 0
    if bet<50: return await update.message.reply_text("Min 50 ❄️")
    if get_coins(user.id)<bet: return await update.message.reply_text("Nahi hain 💀")
    result=pick(["heads","tails"]); pick_=("heads" if choice in ["heads","h"] else "tails")
    if pick_==result:
        add_coins(user.id,bet); apply_tax(bet)
        text=f"🪙 *{result.capitalize()}!*\n\n✅ Jeete!\n💰 +{bet:,} coins ❄️"
    else:
        add_coins(user.id,-bet); apply_tax(bet)
        text=f"🪙 *{result.capitalize()}!*\n\n❌ Haare\n💸 -{bet:,} coins 🌙"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# RPS GAME
# ═══════════════════════════════════════════════════════════════════

async def cmd_rps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    msg  = update.message

    # ── If used as a reply to another user → start a 2-player battle ──
    if msg.reply_to_message and msg.reply_to_message.from_user:
        opp = msg.reply_to_message.from_user; store_name(opp)
        if opp.id == user.id:
            return await msg.reply_text("Khud se RPS? ❄️ hehe~ koi aur dhundo~")
        if opp.is_bot:
            return await msg.reply_text("Bot se khelo toh args ke saath `/rps r/p/s` use karo ❄️", parse_mode=ParseMode.MARKDOWN)
        bet = 0
        if ctx.args and ctx.args[0].isdigit():
            bet = int(ctx.args[0])
        if bet > 0:
            if get_coins(user.id) < bet:
                return await msg.reply_text(f"❌ Tumhare paas {bet:,} coins nahi hain ❄️")
            if get_coins(opp.id) < bet:
                return await msg.reply_text(f"❌ {get_name(opp.id)} ke paas {bet:,} coins nahi hain ❄️")
        battle_id = uuid.uuid4().hex[:8]
        rps_battles[battle_id] = {
            "p1": user.id, "p2": opp.id, "bet": bet,
            "pick1": None, "pick2": None,
        }
        bet_line = f"💰 Bet: `{bet:,}` {CUR}" if bet > 0 else "🎮 No bet — sirf izzat!"
        text = (
            f"⚔️ *RPS Battle!* ✂️🪨📄\n\n"
            f"👤 {get_mention(user)} vs {get_mention(opp)}\n"
            f"{bet_line}\n\n"
            f"Dono apna choice secretly choose karo!\n"
            f"_Opponent ko nahi dikhega~ hehe_ ❄️"
        )
        sent = await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_rps_keyboard(battle_id))
        rps_battles[battle_id]["msg_id"]  = sent.message_id
        rps_battles[battle_id]["chat_id"] = msg.chat.id
        return

    # ── Solo vs Bot ──
    if not ctx.args or ctx.args[0].lower() not in ["r","p","s","rock","paper","scissors"]:
        return await msg.reply_text(
            "✊ *Rock Paper Scissors*\n\n"
            "`/rps r` — Rock ✊\n`/rps p` — Paper 🤚\n`/rps s` — Scissors ✌️\n\n"
            "_Kisi ko reply karo `/rps` se 2-player battle ke liye!_ ❄️",
            parse_mode=ParseMode.MARKDOWN)
    choices_map = {"r":"rock","p":"paper","s":"scissors","rock":"rock","paper":"paper","scissors":"scissors"}
    emojis = {"rock":"✊","paper":"🤚","scissors":"✌️"}
    wins = {"rock":"scissors","paper":"rock","scissors":"paper"}
    user_c = choices_map[ctx.args[0].lower()]
    bot_c  = pick(["rock","paper","scissors"])
    u_e, b_e = emojis[user_c], emojis[bot_c]
    if user_c == bot_c:
        result = "🤝 *Draw!* Haha dono same hain ❄️ hehe~"; add_coins(user.id, 50)
    elif wins[user_c] == bot_c:
        prize = rand(100, 300); add_coins(user.id, prize)
        result = f"🎉 *Tum jeete!*\n\n💰 +{prize} coins ❄️\nhehe~ accha khela!"
    else:
        fine = rand(50, 150); add_coins(user.id, -fine)
        result = f"😈 *Yuki jeeti!*\n\n💸 -{fine} coins 💀\nhehe~ try again! 🌸"
    await msg.reply_text(
        f"✊ *RPS!*\n\nTum: {u_e} {user_c.capitalize()}\nYuki: {b_e} {bot_c.capitalize()}\n\n{result}",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# HANGMAN
# ═══════════════════════════════════════════════════════════════════

def hangman_display(word, guessed):
    display = " ".join(c if c in guessed else r"\_" for c in word)
    remaining = 6 - sum(1 for c in guessed if c not in word)
    stages = ["😵💀","😰😨","😟😬","😐🤔","🙂😊","😎❄️","🌟✨"]
    return display, remaining, stages[max(0,min(6,remaining))]

async def cmd_hangman(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid in active_hangman:
        g = active_hangman[cid]
        disp, rem, face = hangman_display(g["word"], g["guessed"])
        wrong = [c for c in g["guessed"] if c not in g["word"]]
        return await update.message.reply_text(
            f"🔤 *Hangman — Already Active!*\n\n`{disp}`\n\n{face} Lives: {rem}\n❌ Wrong: `{''.join(wrong) or 'none'}`\n\n"
            f"Koi bhi ek letter guess karo (reply karke)!", parse_mode=ParseMode.MARKDOWN)
    word = pick(HANGMAN_WORDS).lower()
    active_hangman[cid] = {"word": word, "guessed": set(), "tries": 0, "starter": update.effective_user.id}
    disp, rem, face = hangman_display(word, set())
    await update.message.reply_text(
        f"🔤 *Hangman Started!*\n\n`{disp}`\n\n{face} Lives: {rem}\n\n"
        f"Ek letter guess karo! (Koi bhi message mein sirf ek letter likho)\n"
        f"❄️ Hint: {len(word)} letter ka word", parse_mode=ParseMode.MARKDOWN)

async def hangman_guess(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid not in active_hangman: return
    text = update.message.text.strip().lower()
    if len(text) != 1 or not text.isalpha(): return
    g = active_hangman[cid]
    if text in g["guessed"]:
        await update.message.reply_text(f"❄️ `{text}` pehle guess ho chuka hai!", parse_mode=ParseMode.MARKDOWN)
        return
    g["guessed"].add(text)
    word = g["word"]
    disp, rem, face = hangman_display(word, g["guessed"])
    wrong = [c for c in g["guessed"] if c not in word]
    if all(c in g["guessed"] for c in word):
        prize = rand(200, 600)
        add_coins(update.effective_user.id, prize)
        del active_hangman[cid]
        await update.message.reply_text(
            f"🎉 *{update.effective_user.first_name} JEETA!*\n\nWord: `{word}` ✅\n💰 +{prize} coins ❄️", parse_mode=ParseMode.MARKDOWN)
    elif rem <= 0:
        del active_hangman[cid]
        await update.message.reply_text(
            f"💀 *Game Over!*\n\nWord tha: `{word}`\n\n❄️ Agli baar /hangman karo!", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(
            f"🔤 *Hangman*\n\n`{disp}`\n\n{face} Lives: {rem}\n❌ Wrong: `{''.join(wrong) or 'none'}`",
            parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# TRIVIA
# ═══════════════════════════════════════════════════════════════════

async def cmd_trivia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    q_data = pick(TRIVIA_QS)
    active_trivia[cid] = {
        "q": q_data["q"], "a": q_data["a"], "hint": q_data["hint"],
        "time": time.time(), "asked_by": update.effective_user.id
    }
    await update.message.reply_text(
        f"🧠 *Trivia!*\n\n❓ {q_data['q']}\n\n⏱️ 30 seconds!\n💡 Hint: `/hint` se milega\n"
        f"❄️ Jawab group mein type karo!", parse_mode=ParseMode.MARKDOWN)

async def trivia_answer_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid not in active_trivia: return
    tr = active_trivia[cid]
    if time.time() - tr["time"] > 30:
        del active_trivia[cid]
        await update.message.reply_text(f"⏱️ Time up! Answer tha: `{tr['a']}` ❄️", parse_mode=ParseMode.MARKDOWN)
        return
    ans = update.message.text.strip().lower()
    if tr["a"].lower() in ans or ans in tr["a"].lower():
        prize = rand(100, 400)
        add_coins(update.effective_user.id, prize)
        del active_trivia[cid]
        await update.message.reply_text(
            f"🎉 *Correct!*\n\n{get_mention(update.effective_user)} ne jawab diya!\n"
            f"✅ `{tr['a']}`\n💰 +{prize} coins ❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_hint(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid not in active_trivia:
        return await update.message.reply_text("❄️ Koi active trivia nahi. /trivia se shuru karo!")
    tr = active_trivia[cid]
    await update.message.reply_text(f"💡 Hint: _{tr['hint']}_ ❄️", parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# COUPLE SYSTEM
# ═══════════════════════════════════════════════════════════════════

async def cmd_marry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    if not update.message.reply_to_message:
        return await update.message.reply_text("❄️ Kisi ko reply karo /marry se... propose karo!")
    target = update.message.reply_to_message.from_user; store_name(target)
    if target.id == user.id: return await update.message.reply_text("Khud se? ❄️ Interesting.")
    if target.id == BOT_ID: return await update.message.reply_text(pick([
        "Mujhse? ❄️ ...m-main toh bus ek snowflake hoon 🥺",
        "Hmph. Flattering hai... lekin main kisi ki nahi hoti 🌙❄️",
    ]))
    row_u = _fetch("SELECT couple_id FROM users WHERE uid=?", (user.id,))
    row_t = _fetch("SELECT couple_id FROM users WHERE uid=?", (target.id,))
    if row_u and row_u["couple_id"]:
        return await update.message.reply_text(f"❄️ Tum pehle se married ho! /divorce karo pehle.")
    if row_t and row_t["couple_id"]:
        return await update.message.reply_text(f"❄️ {get_name(target.id)} pehle se kisi ke saath hai!")
    key = f"marry_{user.id}_{target.id}"
    pending_proposals[key] = {"from": user, "to": target, "time": time.time()}
    kb = [[InlineKeyboardButton("💍 Accept", callback_data=f"marry_yes_{key}"),
           InlineKeyboardButton("💔 Reject",  callback_data=f"marry_no_{key}")]]
    await update.message.reply_text(
        f"💍 *Proposal!*\n\n{get_mention(user)} ne {get_mention(target)} ko propose kiya!\n\n{get_mention(target)}, accept karoge? 🌸❄️",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def marry_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    parts = q.data.split("_",3); action=parts[1]; key="_".join(parts[2:])
    proposal = pending_proposals.get(key)
    if not proposal: return await q.edit_message_text("❄️ Proposal expire ho gaya...")
    if q.from_user.id != proposal["to"].id:
        return await q.answer("Yeh tumhara proposal nahi ❄️", show_alert=True)
    from_user = proposal["from"]; to_user = proposal["to"]
    del pending_proposals[key]
    if action=="no":
        return await q.edit_message_text(
            f"💔 {get_mention(to_user)} ne reject kar diya...\n❄️ Dard toh hota hai.", parse_mode=ParseMode.MARKDOWN)
    _ensure_user(from_user.id); _ensure_user(to_user.id)
    _exec("UPDATE users SET couple_id=? WHERE uid=?", (to_user.id, from_user.id))
    _exec("UPDATE users SET couple_id=? WHERE uid=?", (from_user.id, to_user.id))
    await q.edit_message_text(
        f"💑 *Married!*\n\n{get_mention(from_user)} 💍 {get_mention(to_user)}\n\n❄️ Congratulations! Khush raho tum dono 🌸",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_divorce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    row = _fetch("SELECT couple_id FROM users WHERE uid=?", (user.id,))
    partner_id = row["couple_id"] if row else None
    if not partner_id: return await update.message.reply_text("❄️ Tum married hi nahi ho...")
    _exec("UPDATE users SET couple_id=NULL WHERE uid=?", (user.id,))
    _exec("UPDATE users SET couple_id=NULL WHERE uid=?", (partner_id,))
    await update.message.reply_text(
        f"💔 *Divorce...*\n\n{user.first_name} aur {get_name(partner_id)} alag ho gaye\n❄️ Zindagi chaalti rehti hai...",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_couple(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    row = _fetch("SELECT couple_id FROM users WHERE uid=?", (user.id,))
    partner_id = row["couple_id"] if row else None
    if not partner_id: return await update.message.reply_text(f"❄️ {user.first_name} single hai... /marry karo kisi ko!")
    pct = ship_percent(get_name(user.id), get_name(partner_id))
    await update.message.reply_text(
        f"💑 *Couple Info*\n\n{get_mention_id(user.id)} 💍 {get_mention_id(partner_id)}\n\n"
        f"{ship_bar(pct)} {pct}%\n❄️ Cute couple!",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# FIR SYSTEM
# ═══════════════════════════════════════════════════════════════════

async def cmd_fir(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    if not ctx.args: return await update.message.reply_text("❄️ /fir <reason> ya kisi ko reply karke")
    accused_id = None
    if update.message.reply_to_message:
        accused = update.message.reply_to_message.from_user
        store_name(accused); accused_id = accused.id
    reason = " ".join(ctx.args)
    chat_id = update.effective_chat.id
    _exec("INSERT INTO fir_cases (chat_id, reporter_id, accused_id, reason, ts) VALUES (?,?,?,?,?)",
          (chat_id, user.id, accused_id, reason, int(time.time())))
    row = _fetch("SELECT last_insert_rowid() as id")
    case_id = row["id"] if row else "?"
    accused_txt = f"👤 Accused: {get_mention_id(accused_id)}" if accused_id else ""
    await update.message.reply_text(
        f"📋 *FIR Filed!*\n\n🔢 Case #{case_id}\n👮 Reporter: {get_mention(user)}\n{accused_txt}\n📝 Reason: {reason}\n\n❄️ Admin dekhenge...",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_cases(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cases = _fetchall("SELECT * FROM fir_cases WHERE chat_id=? AND status='open' LIMIT 10", (chat_id,))
    if not cases: return await update.message.reply_text("❄️ Koi active FIR nahi!")
    text = "📋 *Active FIR Cases*\n\n"
    for c in cases:
        accused_txt = f"→ {get_name(c['accused_id'])}" if c["accused_id"] else ""
        text += f"*#{c['id']}* {accused_txt}\n📝 {c['reason'][:50]}\n👮 {get_name(c['reporter_id'])}\n\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_close_fir(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text(
            "❄️ `/closefir <case_id> [mute/kick/warn/fine]`\n\nExample:\n"
            "`/closefir 3 mute` — accused ko mute karo\n"
            "`/closefir 3 kick` — accused ko kick karo\n"
            "`/closefir 3 warn` — accused ko warning do\n"
            "`/closefir 3 fine` — accused se 500 coins lo\n"
            "`/closefir 3` — sirf close karo",
            parse_mode=ParseMode.MARKDOWN)

    case_id = int(ctx.args[0])
    action  = ctx.args[1].lower() if len(ctx.args) > 1 else "close"
    row = _fetch("SELECT * FROM fir_cases WHERE id=? AND status='open'", (case_id,))
    if not row:
        return await update.message.reply_text(f"❄️ Case #{case_id} nahi mila ya pehle se closed hai")

    accused_id = row["accused_id"]
    _exec("UPDATE fir_cases SET status='closed' WHERE id=?", (case_id,))

    punishment_text = ""
    if accused_id and action in ("mute","kick","warn","fine"):
        try:
            if action == "mute":
                until = datetime.now() + timedelta(hours=1)
                await ctx.bot.restrict_chat_member(
                    update.effective_chat.id, accused_id,
                    ChatPermissions(can_send_messages=False), until_date=until)
                punishment_text = f"\n🔇 *Punishment:* {get_mention_id(accused_id)} ko 1h mute kiya ❄️"
            elif action == "kick":
                await ctx.bot.ban_chat_member(update.effective_chat.id, accused_id)
                await ctx.bot.unban_chat_member(update.effective_chat.id, accused_id)
                punishment_text = f"\n👢 *Punishment:* {get_mention_id(accused_id)} ko kick kiya ❄️"
            elif action == "warn":
                _ensure_user(accused_id)
                _exec("UPDATE users SET warnings=warnings+1 WHERE uid=?", (accused_id,))
                w_row = _fetch("SELECT warnings FROM users WHERE uid=?", (accused_id,))
                warns = w_row["warnings"] if w_row else 1
                punishment_text = f"\n⚠️ *Punishment:* {get_mention_id(accused_id)} warned ({warns}/3) ❄️"
                if warns >= 3:
                    try:
                        await ctx.bot.ban_chat_member(update.effective_chat.id, accused_id)
                        punishment_text += " → AUTO BANNED!"
                        _exec("UPDATE users SET warnings=0 WHERE uid=?", (accused_id,))
                    except: pass
            elif action == "fine":
                fine_amt = 500
                add_coins(accused_id, -fine_amt)
                punishment_text = f"\n💸 *Punishment:* {get_mention_id(accused_id)} se {fine_amt} coins fine ❄️"
        except Exception as e:
            punishment_text = f"\n❌ Punishment error: {e}"

    reporter_txt = f"\n👮 Reporter: {get_mention_id(row['reporter_id'])}" if row["reporter_id"] else ""
    accused_txt  = f"\n👤 Accused: {get_mention_id(accused_id)}" if accused_id else ""
    await update.message.reply_text(
        f"⚖️ *Case #{case_id} Closed!*{reporter_txt}{accused_txt}\n📝 {row['reason'][:60]}"
        f"{punishment_text}\n\n✅ FIR Resolved ❄️",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# AFK SYSTEM
# ═══════════════════════════════════════════════════════════════════

async def cmd_afk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    reason = " ".join(ctx.args) if ctx.args else "BRB 🌙"
    _ensure_user(user.id)
    _exec("UPDATE users SET afk_since=?, afk_reason=? WHERE uid=?", (int(time.time()), reason, user.id))
    await update.message.reply_text(pick([
        f"😴 *{user.first_name} AFK!*\nReason: _{reason}_ ❄️",
        f"🌙 {user.first_name} gaaye... _{reason}_ ❄️",
        f"😴 Bye {user.first_name}~ _{reason}_ 🌸",
    ]), parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# NOTES SYSTEM (Rose style)
# ═══════════════════════════════════════════════════════════════════

async def cmd_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args or len(ctx.args) < 2:
        return await update.message.reply_text("❄️ /save <name> <content>")
    name = ctx.args[0].lower()
    content = " ".join(ctx.args[1:])
    cid = update.effective_chat.id
    _exec("INSERT OR REPLACE INTO notes (chat_id, name, content) VALUES (?,?,?)", (cid, name, content))
    await update.message.reply_text(f"📝 Note `{name}` save ho gaya ❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_get(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: return await update.message.reply_text("❄️ /get <name>")
    name = ctx.args[0].lower()
    cid = update.effective_chat.id
    row = _fetch("SELECT content FROM notes WHERE chat_id=? AND name=?", (cid, name))
    if not row: return await update.message.reply_text(f"❄️ `{name}` note nahi mila", parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(f"📝 *{name}*\n\n{row['content']}", parse_mode=ParseMode.MARKDOWN)

async def cmd_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    rows = _fetchall("SELECT name FROM notes WHERE chat_id=?", (cid,))
    if not rows: return await update.message.reply_text("❄️ Koi notes nahi hain. /save se banao!")
    names = " • ".join(f"`{r['name']}`" for r in rows)
    await update.message.reply_text(f"📝 *Notes in this group:*\n\n{names}\n\n/get <name> se padho ❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_delnote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args: return await update.message.reply_text("❄️ /delnote <name>")
    name = ctx.args[0].lower()
    cid = update.effective_chat.id
    _exec("DELETE FROM notes WHERE chat_id=? AND name=?", (cid, name))
    await update.message.reply_text(f"🗑️ Note `{name}` delete ho gaya ❄️", parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# FILTERS (keyword auto-reply)
# ═══════════════════════════════════════════════════════════════════

async def cmd_filter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args or len(ctx.args) < 2:
        return await update.message.reply_text("❄️ /filter <keyword> <response>")
    keyword = ctx.args[0].lower()
    response = " ".join(ctx.args[1:])
    cid = update.effective_chat.id
    _exec("INSERT OR REPLACE INTO filters_kw (chat_id, keyword, response) VALUES (?,?,?)", (cid, keyword, response))
    await update.message.reply_text(f"✅ Filter `{keyword}` set ho gaya ❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_filters(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    rows = _fetchall("SELECT keyword, response FROM filters_kw WHERE chat_id=?", (cid,))
    if not rows:
        return await update.message.reply_text(
            "🔍 *Koi filters nahi hain!*\n\n"
            "Banana ho toh:\n`/filter <keyword> <response>`\n\n"
            "_Jab koi woh keyword likhega, Yuki automatically reply karegi!_ ❄️",
            parse_mode=ParseMode.MARKDOWN)
    # Show keyword + response preview + remove button for each filter
    buttons = []
    text_lines = []
    for i, r in enumerate(rows, 1):
        kw   = r["keyword"]
        resp = r["response"]
        # Truncate long responses for display
        preview = resp[:60] + "..." if len(resp) > 60 else resp
        text_lines.append(f"*{i}.* `{kw}`\n    ↳ _{preview}_")
        buttons.append([InlineKeyboardButton(
            f"❌ Remove: {kw}",
            callback_data=f"rmfilter_{cid}_{kw}"
        )])
    full_text = "\n\n".join(text_lines)
    await update.message.reply_text(
        f"🔍 *Active Filters* ({len(rows)}):\n\n{full_text}\n\n"
        f"_❌ button dabao seedha remove karne ke liye!_ ❄️",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def filter_remove_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline ❌ remove button from /filters list."""
    q = update.callback_query
    parts = q.data.split("_", 2)  # rmfilter_{cid}_{keyword}
    if len(parts) != 3:
        return await q.answer("Error ❄️")
    _, cid_str, keyword = parts
    try:
        cid = int(cid_str)
    except ValueError:
        return await q.answer("Error ❄️")
    # Only admins can remove
    try:
        m = await ctx.bot.get_chat_member(cid, q.from_user.id)
        if m.status not in ("administrator", "creator"):
            return await q.answer("❄️ Admin only! hehe~", show_alert=True)
    except:
        return await q.answer("❄️ Permission check fail kiya", show_alert=True)
    _exec("DELETE FROM filters_kw WHERE chat_id=? AND keyword=?", (cid, keyword))
    await q.answer(f"✅ Filter '{keyword}' remove ho gaya! hehe~")
    # Refresh the filters list in-place
    rows = _fetchall("SELECT keyword, response FROM filters_kw WHERE chat_id=?", (cid,))
    if not rows:
        try:
            await q.message.edit_text("🔍 *Active Filters:*\n\n_Koi filters nahi bache!_ ❄️", parse_mode=ParseMode.MARKDOWN)
        except: pass
        return
    buttons = []
    text_lines = []
    for i, r in enumerate(rows, 1):
        kw      = r["keyword"]
        preview = r["response"][:60] + "..." if len(r["response"]) > 60 else r["response"]
        text_lines.append(f"*{i}.* `{kw}`\n    ↳ _{preview}_")
        buttons.append([InlineKeyboardButton(f"❌ Remove: {kw}", callback_data=f"rmfilter_{cid}_{kw}")])
    full_text = "\n\n".join(text_lines)
    try:
        await q.message.edit_text(
            f"🔍 *Active Filters* ({len(rows)}):\n\n{full_text}\n\n_❌ button dabao seedha remove karne ke liye!_ ❄️",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except: pass

async def cmd_stopfilter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args: return await update.message.reply_text("❄️ /stopfilter <keyword>")
    keyword = ctx.args[0].lower()
    cid = update.effective_chat.id
    _exec("DELETE FROM filters_kw WHERE chat_id=? AND keyword=?", (cid, keyword))
    await update.message.reply_text(f"✅ Filter `{keyword}` remove ho gaya ❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_removefilter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Alias for /stopfilter"""
    return await cmd_stopfilter(update, ctx)

# ═══════════════════════════════════════════════════════════════════
# WELCOME / GOODBYE
# ═══════════════════════════════════════════════════════════════════

async def cmd_setwelcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args:
        return await update.message.reply_text(
            "❄️ /setwelcome <message>\n\nVariables:\n`{name}` — user name\n`{mention}` — mention\n`{group}` — group name",
            parse_mode=ParseMode.MARKDOWN)
    msg = " ".join(ctx.args)
    set_gsetting(update.effective_chat.id, "welcome", msg)
    await update.message.reply_text(f"✅ Welcome message set ho gaya! ❄️\n\nPreview:\n{msg.replace('{name}','Yuki').replace('{mention}','Yuki').replace('{group}',update.effective_chat.title or 'Group')}",
                                    parse_mode=ParseMode.MARKDOWN)

async def cmd_setgoodbye(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args:
        return await update.message.reply_text("❄️ /setgoodbye <message>")
    msg = " ".join(ctx.args)
    set_gsetting(update.effective_chat.id, "goodbye", msg)
    await update.message.reply_text(f"✅ Goodbye message set ho gaya! ❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_resetwelcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    set_gsetting(update.effective_chat.id, "welcome", "")
    await update.message.reply_text("✅ Welcome reset to default ❄️")

# ═══════════════════════════════════════════════════════════════════
# RULES
# ═══════════════════════════════════════════════════════════════════

async def cmd_setrules(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args: return await update.message.reply_text("❄️ /setrules <rules>")
    rules = " ".join(ctx.args)
    set_gsetting(update.effective_chat.id, "rules", rules)
    await update.message.reply_text(f"📋 *Rules set!* ❄️\n\n_{rules}_", parse_mode=ParseMode.MARKDOWN)

async def cmd_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rules = get_gsetting(update.effective_chat.id, "rules")
    if not rules:
        return await update.message.reply_text(
            "❄️ Koi rules set nahi hain\nAdmin: `/setrules <text>` se set karo", parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(f"📋 *Group Rules*\n\n{rules}\n\n❄️ Follow karo!", parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════════════

async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return await update.message.reply_text("❄️ Group mein use karo")
    user = update.effective_user; store_name(user)
    reason = " ".join(ctx.args) if ctx.args else "No reason given"
    reported = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    try:
        admins = await ctx.bot.get_chat_administrators(update.effective_chat.id)
        admin_text = " ".join(f"[{a.user.first_name}](tg://user?id={a.user.id})" for a in admins if not a.user.is_bot)
        await update.message.reply_text(
            f"🚨 *Report Filed!*\n\n{admin_text}\n\n👤 Reported by: {get_mention(user)}"
            f"{chr(10)+'👤 Against: '+get_mention(reported) if reported else ''}\n📝 Reason: {reason}\n❄️",
            parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❄️ Report nahi ho saka: {e}")

# ═══════════════════════════════════════════════════════════════════
# SLOWMODE / LOCK
# ═══════════════════════════════════════════════════════════════════

async def cmd_slowmode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text("❄️ /slowmode <seconds> (0 = off)")
    secs = int(ctx.args[0])
    try:
        await ctx.bot.set_chat_slow_mode_delay(update.effective_chat.id, secs)
        if secs == 0:
            await update.message.reply_text("✅ Slowmode off ❄️")
        else:
            await update.message.reply_text(f"🐢 Slowmode {secs}s set ho gaya ❄️")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

def _make_permissions(**overrides) -> ChatPermissions:
    """Build ChatPermissions safely — works on both PTB v13 and v20+.
    Only uses fields that are stable across all versions."""
    safe_fields = {
        "can_send_messages", "can_send_polls", "can_send_other_messages",
        "can_add_web_page_previews", "can_change_info",
        "can_invite_users", "can_pin_messages",
    }
    # Try including can_send_audios/photos/videos (PTB v20+ individual fields)
    import inspect
    ptb_fields = set(inspect.signature(ChatPermissions.__init__).parameters.keys()) - {"self"}
    allowed = safe_fields | ptb_fields

    # Build kwargs — skip any field not accepted by this PTB version
    kwargs = {}
    for k, v in overrides.items():
        if k in allowed:
            kwargs[k] = v
    return ChatPermissions(**kwargs)


# Locked → all False; Unlocked → all True base
_LOCKED_ALL = dict(
    can_send_messages=False, can_send_polls=False,
    can_send_other_messages=False, can_add_web_page_previews=False,
    can_invite_users=False, can_change_info=False, can_pin_messages=False,
)
_OPEN_ALL = dict(
    can_send_messages=True, can_send_polls=True,
    can_send_other_messages=True, can_add_web_page_previews=True,
    can_invite_users=True, can_change_info=False, can_pin_messages=False,
)

LOCK_HELP_TEXT = (
    "🔒 *Lock Command — Usage*\n\n"
    "`/lock all` — Sab kuch band karo 🔇\n"
    "`/lock msg` — Sirf text messages band 💬\n"
    "`/lock stickers` — Stickers aur GIFs band 🎭\n"
    "`/lock polls` — Polls band 📊\n"
    "`/lock links` — Link previews band 🔗\n"
    "`/lock invite` — Invite links band 🔐\n\n"
    "`/unlock` — Sab kuch kholo 🔓\n"
    "`/unlock msg` — Sirf messages kholo\n"
    "`/unlock stickers` — Sirf stickers kholo\n"
    "`/unlock polls` — Sirf polls kholo\n\n"
    "⚠️ *Zaroorat:* Bot ko group mein *Admin* hona chahiye\n"
    "aur *Restrict Members* permission chahiye!\n\n"
    "❄️ Admins pe lock apply nahi hota"
)

async def cmd_lock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Sirf admins use kar sakte hain /lock")

    if update.effective_chat.type == "private":
        return await update.message.reply_text(
            "❄️ /lock sirf groups mein kaam karta hai, private chat mein nahi!")

    lock_type = ctx.args[0].lower() if ctx.args else ""
    if not lock_type:
        return await update.message.reply_text(LOCK_HELP_TEXT, parse_mode=ParseMode.MARKDOWN)

    lock_emoji = {
        "all": "🔇", "msg": "💬", "stickers": "🎭",
        "polls": "📊", "links": "🔗", "invite": "🔐",
    }

    # Build the permission object for each lock type
    try:
        if lock_type == "all":
            perms = _make_permissions(**_LOCKED_ALL)
        elif lock_type == "msg":
            perms = _make_permissions(**{**_OPEN_ALL, "can_send_messages": False})
        elif lock_type == "stickers":
            perms = _make_permissions(**{**_OPEN_ALL, "can_send_other_messages": False})
        elif lock_type == "polls":
            perms = _make_permissions(**{**_OPEN_ALL, "can_send_polls": False})
        elif lock_type == "links":
            perms = _make_permissions(**{**_OPEN_ALL, "can_add_web_page_previews": False})
        elif lock_type == "invite":
            perms = _make_permissions(**{**_OPEN_ALL, "can_invite_users": False})
        else:
            return await update.message.reply_text(LOCK_HELP_TEXT, parse_mode=ParseMode.MARKDOWN)

        await ctx.bot.set_chat_permissions(update.effective_chat.id, perms)
        emoji = lock_emoji.get(lock_type, "🔒")
        await update.message.reply_text(
            pick([
                f"🔒 *{lock_type}* lock ho gaya! {emoji}\n❄️ Admins tab bhi bol sakte hain",
                f"✅ *{lock_type}* band kar diya {emoji} ❄️ Shanti raho~",
                f"🔒 Done! Group *{lock_type}* locked {emoji} ❄️",
            ]),
            parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        err = str(e)
        if "not enough rights" in err.lower() or "rights" in err.lower():
            hint = "❌ Bot ko *Restrict Members* permission chahiye!\nGroup settings → Admins → Bot → Enable 'Restrict Members'"
        elif "chat_not_modified" in err.lower():
            hint = f"ℹ️ *{lock_type}* pehle se is state mein hai ❄️"
        else:
            hint = f"❌ Error: `{err}`"
        await update.message.reply_text(hint, parse_mode=ParseMode.MARKDOWN)


async def cmd_unlock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Sirf admins use kar sakte hain /unlock")

    if update.effective_chat.type == "private":
        return await update.message.reply_text("❄️ /unlock sirf groups mein kaam karta hai!")

    unlock_type = ctx.args[0].lower() if ctx.args else "all"

    try:
        if unlock_type == "all":
            perms = _make_permissions(**_OPEN_ALL)
        elif unlock_type == "msg":
            perms = _make_permissions(**{**_OPEN_ALL, "can_send_messages": True})
        elif unlock_type == "stickers":
            perms = _make_permissions(**{**_OPEN_ALL, "can_send_other_messages": True})
        elif unlock_type == "polls":
            perms = _make_permissions(**{**_OPEN_ALL, "can_send_polls": True})
        elif unlock_type == "links":
            perms = _make_permissions(**{**_OPEN_ALL, "can_add_web_page_previews": True})
        elif unlock_type == "invite":
            perms = _make_permissions(**{**_OPEN_ALL, "can_invite_users": True})
        else:
            perms = _make_permissions(**_OPEN_ALL)

        await ctx.bot.set_chat_permissions(update.effective_chat.id, perms)
        await update.message.reply_text(
            pick([
                f"🔓 *{unlock_type}* unlock ho gaya! ❄️ Bolo bolo~",
                f"✅ {unlock_type} khul gaya! ❄️ Freedom!",
                f"🔓 Done! *{unlock_type}* unlock ❄️ Behave karo ab 😌",
            ]),
            parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        err = str(e)
        if "not enough rights" in err.lower() or "rights" in err.lower():
            hint = "❌ Bot ko *Restrict Members* permission chahiye!\nGroup settings → Admins → Bot → Enable 'Restrict Members'"
        elif "chat_not_modified" in err.lower():
            hint = f"ℹ️ *{unlock_type}* pehle se unlocked hai ❄️"
        else:
            hint = f"❌ Error: `{err}`"
        await update.message.reply_text(hint, parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# KING COMMANDS
# ═══════════════════════════════════════════════════════════════════

async def cmd_royal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_king(update.effective_user.id):
        return await update.message.reply_text("👑 King only ❄️")
    gift = rand(500, 3000)
    all_users = _fetchall("SELECT uid FROM users")
    for row in all_users:
        add_coins(row["uid"], gift)
    await update.message.reply_text(
        f"👑 *Royal Decree!*\n\nSab ko *{gift:,}* coins gift! 🎁❄️\nLord ki taraf se~", parse_mode=ParseMode.MARKDOWN)

async def cmd_punish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_king(update.effective_user.id): return await update.message.reply_text("👑 King only ❄️")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    t = update.message.reply_to_message.from_user
    fine = rand(500, 2000); add_coins(t.id, -fine); kill_user(t.id)
    await update.message.reply_text(
        f"👑 *Punished!*\n\n{get_mention(t)} — -{fine:,} coins + killed 💀❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_pardon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_king(update.effective_user.id): return await update.message.reply_text("👑 King only ❄️")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    t = update.message.reply_to_message.from_user; revive_user(t.id)
    gift = rand(200,1000); add_coins(t.id, gift)
    await update.message.reply_text(
        f"👑 *Pardoned!*\n\n{get_mention(t)} — maafi + {gift:,} coins ❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_addcoins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_king(update.effective_user.id): return await update.message.reply_text("👑 King only ❄️")
    if not update.message.reply_to_message or not ctx.args:
        return await update.message.reply_text("Reply + amount: /addcoins <n>")
    t = update.message.reply_to_message.from_user; store_name(t)
    amount = int(ctx.args[0]) if ctx.args[0].lstrip('-').isdigit() else 0
    add_coins(t.id, amount)
    await update.message.reply_text(
        f"👑 *Done!* {get_mention(t)} → {'+'if amount>=0 else ''}{amount:,} coins ❄️\nTotal: {get_coins(t.id):,}",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_rmcoins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_king(update.effective_user.id): return await update.message.reply_text("👑 King only ❄️")
    if not update.message.reply_to_message or not ctx.args:
        return await update.message.reply_text("Reply + amount: /rmcoins <n>")
    t = update.message.reply_to_message.from_user; store_name(t)
    amount = int(ctx.args[0]) if ctx.args[0].isdigit() else 0
    add_coins(t.id, -amount)
    await update.message.reply_text(
        f"👑 {get_mention(t)} se -{amount:,} coins liye gaye ❄️", parse_mode=ParseMode.MARKDOWN)

async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_king(update.effective_user.id): return await update.message.reply_text("👑 King only ❄️")
    if not ctx.args: return await update.message.reply_text("❄️ /broadcast <message>")
    msg_text = " ".join(ctx.args)
    broadcast_msg = f"📢 *Broadcast from Lord*\n\n{msg_text}\n\n❄️ — Yuki Bot"
    all_users = _fetchall("SELECT uid FROM users")
    sent, failed = 0, 0
    for row in all_users:
        try:
            await ctx.bot.send_message(row["uid"], broadcast_msg, parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except: failed += 1
    await update.message.reply_text(f"📢 Broadcast done! ✅ {sent} | ❌ {failed} ❄️")

# ═══════════════════════════════════════════════════════════════════
# OWNER / CO-OWNER SYSTEM
# ═══════════════════════════════════════════════════════════════════

async def cmd_owner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg  = update.message
    if not user: return

    # View owner list (anyone can see)
    if not ctx.args or ctx.args[0].lower() in ("list","show"):
        rows = _fetchall("SELECT uid FROM co_owners")
        if not rows:
            return await msg.reply_text("👑 *Co-Owners*\n\nAbhi koi co-owner nahi hai ❄️", parse_mode=ParseMode.MARKDOWN)
        lines = []
        for r in rows:
            lines.append(f"  • {get_mention_id(r['uid'])}")
        txt = "👑 *Co-Owners of Yuki*\n\n" + "\n".join(lines) + "\n\n❄️ Inhe king jitna mano~"
        return await msg.reply_text(txt, parse_mode=ParseMode.MARKDOWN)

    if not is_king(user.id):
        return await msg.reply_text("👑 Sirf King ye kar sakta hai ❄️")

    action = ctx.args[0].lower()

    if action == "add":
        if not msg.reply_to_message:
            return await msg.reply_text("❄️ Kisi ko reply karo jise co-owner banana hai")
        t = msg.reply_to_message.from_user
        if is_king(t.id):
            return await msg.reply_text("❄️ King khud king hai, co-owner kyu bane?")
        if is_co_owner(t.id):
            return await msg.reply_text(f"✅ {get_name(t.id)} already co-owner hai! ❄️")
        _exec("INSERT OR IGNORE INTO co_owners (uid, added_by, added_ts) VALUES (?,?,?)",
              (t.id, user.id, int(time.time())))
        _ensure_user(t.id); store_name(t)
        await msg.reply_text(
            f"👑 *Co-Owner Added!*\n\n{get_mention(t)} ab co-owner hai!\n"
            f"Inhe special powers milti hain ❄️✨", parse_mode=ParseMode.MARKDOWN)

    elif action in ("remove","del","rem"):
        if not msg.reply_to_message:
            return await msg.reply_text("❄️ Kisi ko reply karo jise hatana hai")
        t = msg.reply_to_message.from_user
        if not is_co_owner(t.id):
            return await msg.reply_text(f"❄️ {get_name(t.id)} co-owner hai hi nahi")
        _exec("DELETE FROM co_owners WHERE uid=?", (t.id,))
        await msg.reply_text(
            f"🗑️ *Co-Owner Removed*\n\n{get_mention(t)} ko co-owner se hata diya ❄️",
            parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.reply_text(
            "👑 *Owner Commands*\n\n"
            "`/owner list` — co-owners dikhao\n"
            "`/owner add` — (reply) co-owner banao [king only]\n"
            "`/owner remove` — (reply) co-owner hatao [king only]\n\n"
            "❄️ Co-owners kuch special commands use kar sakte hain~",
            parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# SKILL COMMANDS
# ═══════════════════════════════════════════════════════════════════

async def cmd_skills(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    uid = user.id
    apply_bank_interests(uid)

    lines = [f"⚡ *{user.first_name} ke Skills* ❄️\n"]
    for sk, info in SKILLS.items():
        xp  = get_skill_xp(uid, sk)
        lvl = get_skill_level(uid, sk)
        nxt = SKILL_XP_LEVELS[lvl + 1] if lvl < 10 else None
        bar_filled = "█" * lvl
        bar_empty  = "░" * (10 - lvl)
        bar = f"`{bar_filled}{bar_empty}`"
        nxt_str = f"Next: {nxt} XP" if nxt else "MAX"
        lines.append(
            f"{info['emoji']} *{info['name']}* — Lv.`{lvl}`\n"
            f"  {bar} `{xp}` XP | {nxt_str}\n"
            f"  _{info['desc']}_\n"
        )
    lines.append("📌 _Skills grow automatically — rob karo, kill karo, gamble karo!_")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# BANK COMMANDS
# ═══════════════════════════════════════════════════════════════════

async def cmd_bank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    uid = user.id
    apply_bank_interests(uid)
    lvl = get_level(uid)
    wallet = get_coins(uid)
    total_banked = total_bank_balance(uid)

    lines = [f"🏦 *{user.first_name} ka Bank* ❄️\n",
             f"👛 Wallet: {CUR_S} `{wallet:,}`\n"]
    for bid, info in BANK_INFO.items():
        bal  = get_bank_balance(uid, bid)
        locked = lvl < info["min_level"]
        safe_pct = int(info["safe"] * 100)
        interest_pct = int(info["interest"] * 100)
        status = "🔒 Locked" if locked else "✅ Open"
        lines.append(
            f"{info['emoji']} *{info['name']}* — {status}\n"
            f"  💰 Balance: `{bal:,}` {CUR}\n"
            f"  📈 Interest: `{interest_pct}%`/day  🛡️ Safe: `{safe_pct}%`\n"
            f"  _{info['desc']}_\n"
        )
    lines.append(f"🏦 Total Banked: `{total_banked:,}` {CUR}")
    lines.append(f"\n`/deposit <bank> <amount>` | `/withdraw <bank> <amount>`")
    lines.append(f"Banks: `ice` `frost` `blizzard`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_deposit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    uid = user.id
    if len(ctx.args) < 2:
        return await update.message.reply_text("❄️ `/deposit <bank> <amount>`\nBanks: `ice` `frost` `blizzard`", parse_mode=ParseMode.MARKDOWN)
    bank_id = ctx.args[0].lower()
    if bank_id not in BANK_INFO:
        return await update.message.reply_text("❌ Bank nahi mila. `ice` / `frost` / `blizzard` mein se choose karo ❄️")
    if not ctx.args[1].isdigit():
        return await update.message.reply_text("❌ Amount number hona chahiye ❄️")
    amount = int(ctx.args[1])
    info   = BANK_INFO[bank_id]
    lvl    = get_level(uid)
    if lvl < info["min_level"]:
        return await update.message.reply_text(
            f"🔒 *{info['name']}* ke liye Level `{info['min_level']}` chahiye!\nTumhara Level: `{lvl}` ❄️",
            parse_mode=ParseMode.MARKDOWN)
    if amount < 100:
        return await update.message.reply_text("❄️ Minimum deposit: 100 coins")
    if get_coins(uid) < amount:
        return await update.message.reply_text(f"❌ Itne coins nahi hain wallet mein ❄️")
    add_coins(uid, -amount)
    deposit_bank(uid, bank_id, amount)
    add_skill_xp(uid, "bank", 2)
    bal = get_bank_balance(uid, bank_id)
    await update.message.reply_text(
        f"{info['emoji']} *Deposit Successful!*\n\n"
        f"Bank: *{info['name']}*\n"
        f"💸 Deposited: `{amount:,}` {CUR}\n"
        f"💰 New Balance: `{bal:,}` {CUR}\n"
        f"📈 Interest: `{int(info['interest']*100)}%`/day ❄️",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_withdraw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    uid = user.id
    if len(ctx.args) < 2:
        return await update.message.reply_text("❄️ `/withdraw <bank> <amount>`\nBanks: `ice` `frost` `blizzard`", parse_mode=ParseMode.MARKDOWN)
    bank_id = ctx.args[0].lower()
    if bank_id not in BANK_INFO:
        return await update.message.reply_text("❌ Bank nahi mila ❄️")
    if not ctx.args[1].isdigit():
        return await update.message.reply_text("❌ Amount number hona chahiye ❄️")
    amount = int(ctx.args[1])
    bal    = get_bank_balance(uid, bank_id)
    if amount > bal:
        return await update.message.reply_text(f"❌ Bank mein itne nahi hain. Balance: `{bal:,}` ❄️", parse_mode=ParseMode.MARKDOWN)
    actual = withdraw_bank(uid, bank_id, amount)
    add_coins(uid, actual)
    info   = BANK_INFO[bank_id]
    new_bal = get_bank_balance(uid, bank_id)
    await update.message.reply_text(
        f"{info['emoji']} *Withdraw Successful!*\n\n"
        f"Bank: *{info['name']}*\n"
        f"💸 Withdrawn: `{actual:,}` {CUR}\n"
        f"💰 Remaining: `{new_bal:,}` {CUR} in bank ❄️",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# INLINE RPS BATTLE (SECRET PICKS)
# ═══════════════════════════════════════════════════════════════════

_RPS_EMOJI = {"rock":"🪨","paper":"📄","scissors":"✂️"}
_RPS_WINS  = {"rock":"scissors","paper":"rock","scissors":"paper"}

def _rps_keyboard(battle_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🪨 Rock",     callback_data=f"rps_{battle_id}_rock"),
        InlineKeyboardButton("📄 Paper",    callback_data=f"rps_{battle_id}_paper"),
        InlineKeyboardButton("✂️ Scissors", callback_data=f"rps_{battle_id}_scissors"),
    ]])

async def cmd_rpsbattle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    user = update.effective_user; store_name(user)
    if not msg.reply_to_message:
        return await msg.reply_text("❄️ Kisi ko reply karo `/rpsbattle <bet>` se", parse_mode=ParseMode.MARKDOWN)
    opp = msg.reply_to_message.from_user; store_name(opp)
    if opp.id == user.id:
        return await msg.reply_text("Khud se RPS? ❄️ Koi aur dhundo~")
    if opp.is_bot:
        return await msg.reply_text("Bot se khelo toh /rps use karo ❄️")
    bet = 0
    if ctx.args and ctx.args[0].isdigit():
        bet = int(ctx.args[0])
    if bet > 0:
        if get_coins(user.id) < bet:
            return await msg.reply_text(f"❌ Tumhare paas {bet:,} coins nahi hain ❄️")
        if get_coins(opp.id) < bet:
            return await msg.reply_text(f"❌ {get_name(opp.id)} ke paas {bet:,} coins nahi hain ❄️")

    battle_id = uuid.uuid4().hex[:8]
    rps_battles[battle_id] = {
        "p1": user.id, "p2": opp.id, "bet": bet,
        "pick1": None, "pick2": None,
    }
    bet_line = f"💰 Bet: `{bet:,}` {CUR}" if bet > 0 else "🎮 No bet — just glory!"
    text = (
        f"⚔️ *Secret RPS Battle!* ✂️🪨📄\n\n"
        f"👤 {get_mention(user)} vs {get_mention(opp)}\n"
        f"{bet_line}\n\n"
        f"Dono neeche se secretly apna choice choose karo!\n"
        f"_Opponent ko nahi dikhega tum kya choose karte ho~_ ❄️"
    )
    sent = await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_rps_keyboard(battle_id))
    rps_battles[battle_id]["msg_id"]  = sent.message_id
    rps_battles[battle_id]["chat_id"] = msg.chat.id

async def rps_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data  # rps_{battle_id}_{choice}
    parts = data.split("_", 2)
    if len(parts) != 3: return await q.answer("Invalid ❄️")
    _, battle_id, choice = parts
    if battle_id not in rps_battles:
        return await q.answer("Battle expired ya exist nahi karta ❄️", show_alert=True)
    battle = rps_battles[battle_id]
    uid = q.from_user.id

    if uid == battle["p1"] and battle["pick1"] is None:
        battle["pick1"] = choice
        await q.answer(f"{_RPS_EMOJI[choice]} Pick lock! Dusre ka wait karo~ ❄️")
    elif uid == battle["p2"] and battle["pick2"] is None:
        battle["pick2"] = choice
        await q.answer(f"{_RPS_EMOJI[choice]} Pick lock! Dusre ka wait karo~ ❄️")
    elif uid not in (battle["p1"], battle["p2"]):
        return await q.answer("Yeh tumhara battle nahi hai ❄️", show_alert=True)
    else:
        return await q.answer("Tum already pick kar chuke ho! ❄️", show_alert=True)

    # Update message to show who has picked (not what)
    p1_status = f"✅ {get_name(battle['p1'])}" if battle["pick1"] else f"⏳ {get_name(battle['p1'])}"
    p2_status = f"✅ {get_name(battle['p2'])}" if battle["pick2"] else f"⏳ {get_name(battle['p2'])}"
    bet = battle["bet"]
    bet_line = f"💰 Bet: `{bet:,}` {CUR}" if bet > 0 else "🎮 No bet"

    if battle["pick1"] and battle["pick2"]:
        # Both picked — reveal!
        p1_pick  = battle["pick1"]
        p2_pick  = battle["pick2"]
        p1e      = _RPS_EMOJI[p1_pick]
        p2e      = _RPS_EMOJI[p2_pick]
        p1_name  = get_name(battle["p1"])
        p2_name  = get_name(battle["p2"])
        if p1_pick == p2_pick:
            result = f"🤝 *Draw!* Dono ne `{p1_pick}` chuna!\nBet wapas ❄️"
        elif _RPS_WINS[p1_pick] == p2_pick:
            winner_id = battle["p1"]; loser_id = battle["p2"]
            result = f"🏆 *{p1_name}* JEETA! {p1e} beats {p2e}!"
            if bet > 0:
                add_coins(winner_id, bet); add_coins(loser_id, -bet)
                tax = apply_tax(int(bet * 0.05))
                result += f"\n💰 +`{bet:,}` {CUR} | Tax: `{tax}`"
            add_skill_xp(winner_id, "gamble", 5)
        else:
            winner_id = battle["p2"]; loser_id = battle["p1"]
            result = f"🏆 *{p2_name}* JEETA! {p2e} beats {p1e}!"
            if bet > 0:
                add_coins(winner_id, bet); add_coins(loser_id, -bet)
                tax = apply_tax(int(bet * 0.05))
                result += f"\n💰 +`{bet:,}` {CUR} | Tax: `{tax}`"
            add_skill_xp(winner_id, "gamble", 5)

        reveal_text = (
            f"⚔️ *RPS Battle — Reveal!* 🎊\n\n"
            f"👤 {get_mention_id(battle['p1'])}: {p1e} `{p1_pick}`\n"
            f"👤 {get_mention_id(battle['p2'])}: {p2e} `{p2_pick}`\n\n"
            f"{bet_line}\n\n{result}\n\n❄️"
        )
        try:
            await q.message.edit_text(reveal_text, parse_mode=ParseMode.MARKDOWN)
        except: pass
        del rps_battles[battle_id]
    else:
        wait_text = (
            f"⚔️ *Secret RPS Battle!* ✂️🪨📄\n\n"
            f"{p1_status}\n{p2_status}\n\n"
            f"{bet_line}\n\n"
            f"_Waiting for dono ke picks..._ ❄️"
        )
        try:
            await q.message.edit_text(wait_text, parse_mode=ParseMode.MARKDOWN, reply_markup=_rps_keyboard(battle_id))
        except: pass

# ═══════════════════════════════════════════════════════════════════
# SOCIAL COMMANDS
# ═══════════════════════════════════════════════════════════════════

async def cmd_kiss(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"kiss",f"💋 {get_mention(update.effective_user)} ne {get_mention(t)} ko kiss kiya! 🌸❄️")

async def cmd_hug(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"hug",f"🤗 {get_mention(update.effective_user)} ne {get_mention(t)} ko hug kiya! ❄️💕")

async def cmd_slap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"slap",f"👋 {get_mention(update.effective_user)} ne {get_mention(t)} ko thappad! 😂❄️")

async def cmd_punch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"punch",f"👊 {get_mention(update.effective_user)} ne {get_mention(t)} ko punch! 💥❄️")

async def cmd_pat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"pat",f"🫶 {get_mention(update.effective_user)} ne {get_mention(t)} ko pat kiya! ❄️")

async def cmd_love(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"wave",f"💕 {get_mention(update.effective_user)} ne {get_mention(t)} ko love send kiya! ❤️❄️")

async def cmd_baka(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"baka",f"😤 {get_mention(update.effective_user)} ne {get_mention(t)} ko BAKA bola! 💢❄️")

async def cmd_bonk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"bonk",f"🔨 {get_mention(update.effective_user)} ne {get_mention(t)} ko BONK kiya! 💥❄️")

async def cmd_cuddle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"cuddle",f"🥰 {get_mention(update.effective_user)} ne {get_mention(t)} ko cuddle kiya! 💕❄️")

async def cmd_bite(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"bite",f"😈 {get_mention(update.effective_user)} ne {get_mention(t)} ko bite kiya! 🩸❄️")

async def cmd_lick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo")
    await _gif_cmd(update,"lick",f"👅 {get_mention(update.effective_user)} ne {get_mention(t)} ko lick kiya! 😂❄️")

async def cmd_wave(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    await _gif_cmd(update,"wave",f"👋 {get_mention(update.effective_user)} waves at {get_mention(t)}! 🌸❄️")

async def cmd_waifu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    buf = await fetch_gif("waifu")
    if buf: await update.message.reply_photo(buf, caption="❄️ Waifu moment~ 🌸")
    else: await update.message.reply_text("❄️ Abhi nahi aa paaya 🌙")

async def cmd_ship(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo /ship se...")
    pct = ship_percent(user.first_name, t.first_name)
    verdict = ("Made for each other 💍❄️" if pct>=80 else "Acchi chemistry 💕" if pct>=60 else
               "Thoda effort aur 🌸" if pct>=40 else "Mushkil hai ❄️" if pct>=20 else "Nahi hoga yaar 💀")
    await update.message.reply_text(
        f"💕 *Ship Meter*\n\n{get_mention(user)} ❤️ {get_mention(t)}\n\n{ship_bar(pct)}\n*{pct}%* — {verdict}",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_roast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    await update.message.reply_text(
        f"🔥 *Roast!*\n\n{get_mention(t)},\n{pick(ROASTS)}\n\n❄️ No hard feelings~", parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# ANIME SEARCH
# ═══════════════════════════════════════════════════════════════════

async def cmd_anime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("❄️ /anime <name>\nExample: /anime naruto")
    query = " ".join(ctx.args)
    try:
        async with aiohttp.ClientSession() as s:
            gql = """
            query ($search: String) {
              Media(search: $search, type: ANIME) {
                title { romaji english }
                description(asHtml: false)
                episodes averageScore status
                genres siteUrl
              }
            }"""
            async with s.post("https://graphql.anilist.co",
                              json={"query": gql, "variables": {"search": query}},
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
        media = data["data"]["Media"]
        title = media["title"]["english"] or media["title"]["romaji"]
        desc = (media["description"] or "No description")[:200].replace("<br>","").replace("<i>","").replace("</i>","")
        genres = ", ".join(media["genres"][:4])
        score = media["averageScore"] or "N/A"
        eps = media["episodes"] or "?"
        status = media["status"] or "?"
        await update.message.reply_text(
            f"🎌 *{title}*\n\n📖 {desc}...\n\n"
            f"⭐ Score: `{score}/100`\n📺 Episodes: `{eps}`\n📊 Status: `{status}`\n🏷️ Genres: _{genres}_\n"
            f"🔗 {media['siteUrl']}",
            parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❄️ Nahi mila '{query}' 😔 Try again!")

async def cmd_manga(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("❄️ /manga <name>")
    query = " ".join(ctx.args)
    try:
        async with aiohttp.ClientSession() as s:
            gql = """
            query ($search: String) {
              Media(search: $search, type: MANGA) {
                title { romaji english }
                description(asHtml: false)
                chapters volumes averageScore status
                genres siteUrl
              }
            }"""
            async with s.post("https://graphql.anilist.co",
                              json={"query": gql, "variables": {"search": query}},
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
        media = data["data"]["Media"]
        title = media["title"]["english"] or media["title"]["romaji"]
        desc = (media["description"] or "No description")[:200].replace("<br>","").replace("<i>","").replace("</i>","")
        genres = ", ".join(media["genres"][:4])
        await update.message.reply_text(
            f"📚 *{title}* (Manga)\n\n📖 {desc}...\n\n"
            f"⭐ Score: `{media['averageScore'] or 'N/A'}/100`\n"
            f"📄 Chapters: `{media['chapters'] or '?'}`\n🔗 {media['siteUrl']}",
            parse_mode=ParseMode.MARKDOWN)
    except:
        await update.message.reply_text(f"❄️ Manga nahi mila '{query}' 😔")

# ═══════════════════════════════════════════════════════════════════
# FUN COMMANDS
# ═══════════════════════════════════════════════════════════════════

async def cmd_truth(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"😇 *Truth:*\n\n{pick(TRUTHS)}\n\n❄️ Sach bolna zaroori hai...", parse_mode=ParseMode.MARKDOWN)

async def cmd_dare(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"😈 *Dare:*\n\n{pick(DARES)}\n\n❄️ Himmat hai? Karo!", parse_mode=ParseMode.MARKDOWN)

async def cmd_roll(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sides = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() and int(ctx.args[0]) > 1 else 6
    n = rand(1, sides)
    await update.message.reply_text(
        f"{'🎯' if n==sides else '🎲'} *Dice (d{sides}):* `{n}`\n❄️ {'Lucky max!' if n==sides else 'Roll again...' if n==1 else 'Theek hai.'}",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_flip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🪙 *Coin:* `{pick(['Heads 🪙','Tails 🔘'])}`\n❄️ Fate decide karta hai...", parse_mode=ParseMode.MARKDOWN)

async def cmd_8ball(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: return await update.message.reply_text("❄️ /8ball <sawaal>")
    await update.message.reply_text(
        f"🎱 *Magic 8-Ball*\n\n❓ _{' '.join(ctx.args)}_\n\n❄️ {pick(BALL_ANSWERS)}", parse_mode=ParseMode.MARKDOWN)

async def cmd_quote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"✨ *Yuki's Quote*\n\n{pick(QUOTES)}", parse_mode=ParseMode.MARKDOWN)

async def cmd_joke(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"😂 *Joke:*\n\n{pick(JOKES)}\n❄️ hehe", parse_mode=ParseMode.MARKDOWN)

async def cmd_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("❄️ /calc <expression>", parse_mode=ParseMode.MARKDOWN)
    expr = " ".join(ctx.args)
    try:
        safe = expr.replace("^", "**")
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in safe): raise ValueError
        result = eval(safe, {"__builtins__": {}})
        await update.message.reply_text(f"🧮 `{expr}` = *{result}* ❄️", parse_mode=ParseMode.MARKDOWN)
    except:
        await update.message.reply_text("❄️ Invalid expression 😬", parse_mode=ParseMode.MARKDOWN)

async def cmd_choose(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("❄️ /choose option1 | option2 | option3")
    full = " ".join(ctx.args)
    sep = "|" if "|" in full else "or" if " or " in full else None
    if sep:
        options = [o.strip() for o in full.split(sep) if o.strip()]
    else:
        options = ctx.args
    if len(options) < 2:
        return await update.message.reply_text("❄️ Kam se kam 2 options do!\nExample: `/choose pizza | burger | sushi`", parse_mode=ParseMode.MARKDOWN)
    chosen = pick(options)
    await update.message.reply_text(
        f"🎯 *Yuki ka choice:*\n\n➜ *{chosen}* ✨\n\n❄️ Final answer — argue mat karo 😌",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_say(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args:
        return await update.message.reply_text("❄️ /say <message>")
    msg_text = " ".join(ctx.args)
    try:
        await update.message.delete()
    except: pass
    await update.effective_chat.send_message(f"❄️ {msg_text}")

async def cmd_toss(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    result = pick(["Heads 🪙", "Tails 🔘"])
    await update.message.reply_text(
        f"🪙 *Toss!*\n\n`{result}`\n❄️ {pick(['Fate decide ho gaya!', 'Ab argue mat karo 😌', 'Jo bhi tha... yahi sach hai ❄️'])}",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    start = time.time()
    msg = await update.message.reply_text("🏓 Pinging...")
    ms = int((time.time() - start) * 1000)
    await msg.edit_text(
        f"🏓 *Pong!*\n\n⚡ Response: `{ms}ms`\n❄️ {'Fast!' if ms < 200 else 'Thoda slow... 😬'}",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_weather(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("❄️ /weather <city>\nExample: `/weather Delhi`", parse_mode=ParseMode.MARKDOWN)
    city = "+".join(ctx.args)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://wttr.in/{city}?format=j1",
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return await update.message.reply_text(f"❄️ '{' '.join(ctx.args)}' nahi mila 😔")
                data = await r.json()
        cur = data["current_condition"][0]
        area = data["nearest_area"][0]
        area_name = area["areaName"][0]["value"]
        country   = area["country"][0]["value"]
        temp_c = cur["temp_C"]
        feels = cur["FeelsLikeC"]
        desc  = cur["weatherDesc"][0]["value"]
        humid = cur["humidity"]
        wind  = cur["windspeedKmph"]
        weather_emoji = "☀️" if "sun" in desc.lower() or "clear" in desc.lower() else \
                        "🌧️" if "rain" in desc.lower() else \
                        "⛈️" if "thunder" in desc.lower() else \
                        "❄️" if "snow" in desc.lower() else \
                        "☁️" if "cloud" in desc.lower() or "overcast" in desc.lower() else "🌤️"
        await update.message.reply_text(
            f"{weather_emoji} *{area_name}, {country}*\n\n"
            f"🌡️ Temp: `{temp_c}°C` (Feels like `{feels}°C`)\n"
            f"📝 Condition: _{desc}_\n"
            f"💧 Humidity: `{humid}%`\n"
            f"💨 Wind: `{wind} km/h`\n\n"
            f"❄️ Yuki weather report~",
            parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❄️ Weather nahi aaya 😔 Try again!\n`{e}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_setflood(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global FLOOD_LIMIT, FLOOD_WINDOW
    if not await check_admin(update, ctx, update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if not ctx.args or not ctx.args[0].isdigit():
        return await update.message.reply_text(
            f"❄️ *Anti-Flood Settings*\n\n"
            f"Current: `{FLOOD_LIMIT}` messages in `{FLOOD_WINDOW}s`\n\n"
            f"Usage: `/setflood <messages> [seconds]`\n"
            f"Example: `/setflood 5 10` = 5 msg in 10s\n"
            f"`/setflood 0` = disable flood protection",
            parse_mode=ParseMode.MARKDOWN)
    FLOOD_LIMIT = int(ctx.args[0])
    if len(ctx.args) > 1 and ctx.args[1].isdigit():
        FLOOD_WINDOW = int(ctx.args[1])
    if FLOOD_LIMIT == 0:
        await update.message.reply_text("✅ Anti-flood *disabled* ❄️", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(
            f"✅ Anti-flood set: `{FLOOD_LIMIT}` messages in `{FLOOD_WINDOW}s` → mute 5min ❄️",
            parse_mode=ParseMode.MARKDOWN)

async def cmd_fight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    attacker = update.effective_user; store_name(attacker)
    if not update.message.reply_to_message:
        return await update.message.reply_text("❄️ Reply karo jisse fight karni hai!")
    target = update.message.reply_to_message.from_user; store_name(target)
    if target.id == attacker.id: return await update.message.reply_text("Khud se fight? Thakaa hua lagta hai 💀")
    moves = [
        f"🥊 {attacker.first_name} ne uppercut maara!",
        f"🦵 {attacker.first_name} ne flying kick maari!",
        f"💥 {target.first_name} ne counter-attack kiya!",
        f"🌪️ {attacker.first_name} ne tornado punch maara!",
        f"⭐ {target.first_name} ne dodge kiya!",
        f"🔥 Epic clash! Dono girne wale the!",
    ]
    winner = pick([attacker, target])
    loser  = target if winner.id == attacker.id else attacker
    prize  = rand(50, 300)
    add_coins(winner.id, prize)
    add_coins(loser.id, -(prize//2))
    add_xp(winner.id, 10)
    commentary = pick(moves) + "\n" + pick(moves)
    await update.message.reply_text(
        f"⚔️ *Street Fight!*\n\n{commentary}\n\n"
        f"🏆 *{get_mention(winner)} JEETA!*\n"
        f"💀 {get_mention(loser)} haara\n"
        f"💰 Winner: +{prize} | Loser: -{prize//2}\n❄️",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# ADMIN COMMANDS
# ═══════════════════════════════════════════════════════════════════

async def cmd_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    t = update.message.reply_to_message.from_user
    if await check_admin(update,ctx,t.id):
        return await update.message.reply_text(f"😤 {t.first_name} bhi admin hai! Allowed nahi ❄️")
    reason = " ".join(ctx.args) if ctx.args else "No reason"
    try:
        await ctx.bot.ban_chat_member(update.effective_chat.id, t.id)
        await update.message.reply_text(pick([
            f"🔨 *{t.first_name} banned!*\nReason: {reason}\n❄️ Theek hua.",
            f"👋 *Bye {t.first_name}!*\nReason: {reason}\n❄️ Yuki ne approve kiya.",
        ]), parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    t = update.message.reply_to_message.from_user
    try:
        await ctx.bot.unban_chat_member(update.effective_chat.id, t.id)
        await update.message.reply_text(f"✅ *{t.first_name} unbanned!* ❄️ Ek mauka aur...", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    t = update.message.reply_to_message.from_user
    if await check_admin(update,ctx,t.id):
        return await update.message.reply_text(f"😤 {t.first_name} admin hai! ❄️")
    try:
        await ctx.bot.ban_chat_member(update.effective_chat.id, t.id)
        await ctx.bot.unban_chat_member(update.effective_chat.id, t.id)
        await update.message.reply_text(f"👢 *{t.first_name} kicked!* ❄️", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_tban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message or not ctx.args:
        return await update.message.reply_text("❄️ Reply + time: /tban 1h\nFormats: 30m, 2h, 1d")
    t = update.message.reply_to_message.from_user
    if await check_admin(update,ctx,t.id): return await update.message.reply_text(f"😤 Admin pe nahi ❄️")
    secs = parse_time_arg(ctx.args[0])
    if not secs: return await update.message.reply_text("❄️ Valid time do: 30m / 2h / 1d")
    until = datetime.now() + timedelta(seconds=secs)
    try:
        await ctx.bot.ban_chat_member(update.effective_chat.id, t.id, until_date=until)
        await update.message.reply_text(
            f"⏳ *{t.first_name} temp-banned!*\n🕐 Duration: {ctx.args[0]}\n❄️ {until.strftime('%d %b %H:%M')} tak",
            parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    t = update.message.reply_to_message.from_user
    if await check_admin(update,ctx,t.id): return await update.message.reply_text(f"😤 Admin pe nahi ❄️")
    try:
        await ctx.bot.restrict_chat_member(update.effective_chat.id, t.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text(f"🔇 *{t.first_name} muted!* ❄️", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_unmute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    t = update.message.reply_to_message.from_user
    try:
        perms = _make_permissions(**_OPEN_ALL)
        await ctx.bot.restrict_chat_member(update.effective_chat.id, t.id, perms)
        await update.message.reply_text(f"🔊 *{t.first_name} unmuted!* ❄️", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_tmute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message or not ctx.args:
        return await update.message.reply_text("❄️ Reply + time: /tmute 30m")
    t = update.message.reply_to_message.from_user
    if await check_admin(update,ctx,t.id): return await update.message.reply_text(f"😤 Admin pe nahi ❄️")
    secs = parse_time_arg(ctx.args[0])
    if not secs: return await update.message.reply_text("❄️ Valid time do: 30m / 2h / 1d")
    until = datetime.now() + timedelta(seconds=secs)
    try:
        await ctx.bot.restrict_chat_member(update.effective_chat.id, t.id,
                                           ChatPermissions(can_send_messages=False), until_date=until)
        await update.message.reply_text(
            f"⏳ *{t.first_name} temp-muted!*\n🕐 Duration: {ctx.args[0]}\n❄️",
            parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    t = update.message.reply_to_message.from_user
    _ensure_user(t.id)
    _exec("UPDATE users SET warnings=warnings+1 WHERE uid=?", (t.id,))
    row = _fetch("SELECT warnings FROM users WHERE uid=?", (t.id,))
    warns = row["warnings"] if row else 1
    reason = " ".join(ctx.args) if ctx.args else "No reason"
    text = f"⚠️ *Warning {warns}/3*\n\n{get_mention(t)}\nReason: {reason}\n❄️ Sudhar jao..."
    if warns >= 3:
        try:
            await ctx.bot.ban_chat_member(update.effective_chat.id, t.id)
            text += "\n\n🔨 3 warnings — AUTO BANNED! ❄️"
            _exec("UPDATE users SET warnings=0 WHERE uid=?", (t.id,))
        except: pass
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_unwarn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    t = update.message.reply_to_message.from_user
    _ensure_user(t.id)
    _exec("UPDATE users SET warnings=MAX(0,warnings-1) WHERE uid=?", (t.id,))
    row = _fetch("SELECT warnings FROM users WHERE uid=?", (t.id,))
    warns = row["warnings"] if row else 0
    await update.message.reply_text(
        f"✅ {get_mention(t)} ki warning hatayi ❄️\nAb: {warns}/3", parse_mode=ParseMode.MARKDOWN)

async def cmd_pin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("Reply karo ❄️")
    try:
        await ctx.bot.pin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        await update.message.reply_text(pick(["📌 Pinned ❄️","📌 Done ❄️ Sab dekh sako ab"]))
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_unpin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    try:
        await ctx.bot.unpin_chat_message(update.effective_chat.id)
        await update.message.reply_text("📌 Unpinned ❄️")
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_purge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("❄️ Reply karo jis message se delete karna hai")
    from_id = update.message.reply_to_message.message_id
    to_id   = update.message.message_id
    deleted = 0
    for mid in range(from_id, to_id + 1):
        try: await ctx.bot.delete_message(update.effective_chat.id, mid); deleted += 1
        except: pass
    note = await update.message.reply_text(f"🗑️ *Purge Done!* ✅ {deleted} messages ❄️", parse_mode=ParseMode.MARKDOWN)
    await asyncio.sleep(4)
    try: await note.delete()
    except: pass

async def cmd_promote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("❄️ Reply karo")
    t = update.message.reply_to_message.from_user
    title = " ".join(ctx.args) if ctx.args else "Admin"
    try:
        await ctx.bot.promote_chat_member(update.effective_chat.id, t.id,
            can_delete_messages=True, can_restrict_members=True,
            can_pin_messages=True, can_invite_users=True, can_manage_chat=True)
        try: await ctx.bot.set_chat_administrator_custom_title(update.effective_chat.id, t.id, title[:16])
        except: pass
        await update.message.reply_text(f"⭐ *{t.first_name} promoted!*\nTitle: _{title}_ ❄️", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_demote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id): return await update.message.reply_text("❄️ Admin only")
    if not update.message.reply_to_message: return await update.message.reply_text("❄️ Reply karo")
    t = update.message.reply_to_message.from_user
    try:
        await ctx.bot.promote_chat_member(update.effective_chat.id, t.id,
            can_delete_messages=False, can_restrict_members=False,
            can_pin_messages=False, can_invite_users=False, can_manage_chat=False)
        await update.message.reply_text(f"📉 *{t.first_name} demoted!* ❄️ Hmph.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private": return await update.message.reply_text("❄️ Group mein use karo")
    try:
        admins = await ctx.bot.get_chat_administrators(update.effective_chat.id)
        text = "👮 *Group Admins*\n\n"
        for a in admins:
            u = a.user
            title = a.custom_title or ("👑 Owner" if a.status == "creator" else "🛡️ Admin")
            text += f"{title}: [{u.first_name}](tg://user?id={u.id})\n"
        await update.message.reply_text(text + "\n❄️ Inhe respect karo!", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def cmd_tagall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update,ctx,update.effective_user.id) and not is_king(update.effective_user.id):
        return await update.message.reply_text("❄️ Admin only")
    if update.effective_chat.type == "private": return await update.message.reply_text("❄️ Group mein use karo")
    msg_text = " ".join(ctx.args) if ctx.args else "Sab ka dhyan yahan! ❄️"
    try:
        admins = await ctx.bot.get_chat_administrators(update.effective_chat.id)
        members_text = f"📢 *{msg_text}*\n\n"
        for a in admins:
            if not a.user.is_bot: members_text += f"[{a.user.first_name}](tg://user?id={a.user.id}) "
        members_text += "\n❄️ Yuki ne bulaya hai!"
        await update.message.reply_text(members_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e: await update.message.reply_text(f"Error: {e}")

# ═══════════════════════════════════════════════════════════════════
# UTIL COMMANDS
# ═══════════════════════════════════════════════════════════════════

async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user
    chat = msg.chat
    await msg.reply_text(
        f"🆔 *ID Info*\n\n"
        f"👤 *User:* `{user.first_name}`\n"
        f"🔢 *User ID:* `{user.id}`\n"
        f"👤 *Username:* @{user.username or 'none'}\n\n"
        f"💬 *Chat:* `{chat.title or 'Private'}`\n"
        f"🔢 *Chat ID:* `{chat.id}`\n"
        f"📝 *Type:* `{chat.type}`",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_ginfo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private": return await update.message.reply_text("❄️ Group mein use karo...")
    try: count = await ctx.bot.get_chat_member_count(chat.id)
    except: count = "?"
    desc = chat.description or "Koi description nahi"
    await update.message.reply_text(
        f"📊 *Group Info*\n\n"
        f"📛 *Name:* `{chat.title}`\n"
        f"🔢 *ID:* `{chat.id}`\n"
        f"👥 *Members:* `{count}`\n"
        f"📝 *Type:* `{chat.type}`\n"
        f"📖 *About:* _{desc[:100]}_\n\n"
        f"❄️ Powered by Yuki Bot",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_alive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    status = "💀 Dead" if is_dead(user.id) else "💚 Alive"
    shield_txt = f"🛡️ {secs_hhmm(shield_left(user.id))} left" if has_shield(user.id) else "❌ No Shield"
    await update.message.reply_text(
        f"❄️ *{user.first_name}'s Status*\n\n{status}\n{shield_txt}\n💰 Coins: {get_coins(user.id):,}",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    total_users   = _fetch("SELECT COUNT(*) as c FROM users")["c"]
    total_coins   = _fetch("SELECT SUM(coins) as c FROM users")["c"] or 0
    total_kills   = _fetch("SELECT SUM(kills) as c FROM users")["c"] or 0
    total_couples = _fetch("SELECT COUNT(*) as c FROM users WHERE couple_id IS NOT NULL")["c"] // 2
    total_firs    = _fetch("SELECT COUNT(*) as c FROM fir_cases WHERE status='open'")["c"]
    await update.message.reply_text(
        f"📈 *Yuki Bot Stats*\n\n"
        f"👥 Players: `{total_users}`\n"
        f"💰 Total Coins: `{total_coins:,}`\n"
        f"⚔️ Total Kills: `{total_kills}`\n"
        f"💑 Active Couples: `{total_couples}`\n"
        f"📋 Open FIRs: `{total_firs}`\n\n"
        f"💾 Data: SQLite ✅ (crash-safe)\n"
        f"❄️ Powered by Yuki Bot",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# HELP COMMAND — full updated list
# ═══════════════════════════════════════════════════════════════════

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pages = {
        "main": (
            "❄️ *Yuki Bot — Command List*\n\n"
            "🎮 `/help game` — Game commands\n"
            "💰 `/help economy` — Coins & economy\n"
            "💬 `/help social` — GIFs & fun\n"
            "🎲 `/help fun` — Mini games & tools\n"
            "📋 `/help group` — Group management\n"
            "👑 `/help admin` — Admin tools\n"
            "🌟 `/help new` — New features\n\n"
            "❄️ Ya seedha `/help all` se full list dekho"
        ),
        "game": (
            "🎮 *Game Commands*\n\n"
            "`/kill` — Reply karke kill karo (+coins)\n"
            "`/rob` — Coins churaao\n"
            "`/shield [1/2/3]` — Shield lagao (days)\n"
            "`/revive` — Wapas zinda ho (500c)\n"
            "`/duel <bet>` — 1v1 duel karo 💰\n"
            "`/fight` — Reply karke street fight ⚔️\n"
            "`/bounty <coins>` — Kisi pe bounty lagao\n"
            "`/rps` — Rock Paper Scissors 🪨\n"
            "`/alive` — Apna status dekho\n"
            "`/king` — King system 👑\n\n"
            "`/hangman` — Word game 🔤\n"
            "`/trivia` — Quiz game 🧠\n"
            "`/hint` — Trivia hint\n"
        ),
        "economy": (
            "💰 *Economy Commands*\n\n"
            "`/daily` — Daily reward + streak bonus 📅\n"
            "`/gamble <coins/all>` — Gamble karo 🎰\n"
            "`/cf <h/t> <coins>` — Coin flip bet 🪙\n"
            "`/give <coins>` — Reply karke do 🎁\n"
            "`/lottery` — Lucky ticket (200c) 🎟️\n"
            "`/store` — 55+ items ki dukaan 🛍️\n"
            "`/buy <id>` — Item kharido\n"
            "`/inventory` — Apna saman dekho 🎒\n"
            "`/profile` — Full profile + coins 📊\n"
            "`/streak` — Daily streak info 🔥\n"
            "`/leaderboard` — Top 10 rich players 🏆\n"
            "`/mvp` — Top killers ⚔️\n"
        ),
        "social": (
            "💬 *Social / GIF Commands*\n\n"
            "`/kiss` — 💋 Kiss karo\n"
            "`/hug` — 🤗 Hug karo\n"
            "`/slap` — 👋 Thappad maaro\n"
            "`/punch` — 👊 Punch maaro\n"
            "`/pat` — 🫶 Pat karo\n"
            "`/love` — ❤️ Love do\n"
            "`/baka` — 😤 BAKA bolo\n"
            "`/bonk` — 🔨 Bonk karo\n"
            "`/cuddle` — 🤍 Cuddle karo\n"
            "`/bite` — 😬 Bite karo\n"
            "`/lick` — 👅 Lick karo\n"
            "`/wave` — 👋 Wave karo\n"
            "`/waifu` — Random waifu 🌸\n"
            "`/roast` — Reply karke roast 🔥\n"
            "`/marry` — Propose 💍\n"
            "`/divorce` — Alag ho jao 💔\n"
            "`/couple` — Couple info 💑\n"
            "`/ship` — Ship % dekho 💕\n"
        ),
        "fun": (
            "🎲 *Fun & Tools*\n\n"
            "`/truth` — Saach bolo 😇\n"
            "`/dare` — Dare karo 😈\n"
            "`/8ball <sawaal>` — Magic 8-ball 🎱\n"
            "`/joke` — Random joke 😂\n"
            "`/quote` — Yuki ki quote ✨\n"
            "`/roll [sides]` — Dice roll 🎲\n"
            "`/flip` — Coin toss 🪙\n"
            "`/toss` — Heads ya Tails?\n"
            "`/choose a | b | c` — Yuki decide karti hai 🎯\n"
            "`/calc <expr>` — Calculator 🧮\n"
            "`/ping` — Bot latency 🏓\n"
            "`/weather <city>` — Live weather 🌤️\n"
            "`/anime <name>` — Anime search 🎌\n"
            "`/manga <name>` — Manga search 📖\n"
            "`/afk [reason]` — AFK set karo 😴\n"
        ),
        "group": (
            "📋 *Group Features*\n\n"
            "`/fir <reason>` — FIR file karo 📝\n"
            "`/cases` — Active cases dekho\n"
            "`/closefir <id> [mute/kick/warn/fine]` — Case close + saza\n\n"
            "`/notes` — Saved notes list 📒\n"
            "`/save <name> <text>` — Note save karo\n"
            "`/get <name>` — Note nikalo\n"
            "`/delnote <name>` — Note delete karo\n\n"
            "`/filter <kw> <reply>` — Auto-reply filter\n"
            "`/filters` — Active filters list\n"
            "`/stopfilter <kw>` — Filter hatao\n\n"
            "`/setwelcome <text>` — Custom welcome 👋\n"
            "`/setgoodbye <text>` — Custom goodbye 👋\n"
            "`/resetwelcome` — Default welcome\n"
            "`/setrules <text>` — Rules set karo 📋\n"
            "`/rules` — Rules dekho\n"
            "`/report` — Admin ko report 🚨\n"
            "`/ginfo` — Group info 📊\n"
            "`/id` — User/Chat ID 🆔\n"
            "`/admins` — Admin list 👮\n"
        ),
        "admin": (
            "👑 *Admin Tools*\n\n"
            "`/ban` — Ban karo 🔨\n"
            "`/unban` — Unban karo ✅\n"
            "`/kick` — Kick karo 👢\n"
            "`/mute` — Mute karo 🔇\n"
            "`/unmute` — Unmute karo 🔊\n"
            "`/tban <time>` — Temp ban ⏳\n"
            "`/tmute <time>` — Temp mute ⏳\n"
            "`/warn` — Warning do ⚠️\n"
            "`/unwarn` — Warning hatao\n"
            "`/pin` — Message pin 📌\n"
            "`/unpin` — Unpin 📌\n"
            "`/purge` — Messages delete 🗑️\n"
            "`/promote <title>` — Admin banao ⭐\n"
            "`/demote` — Admin hatao 📉\n"
            "`/tagall <msg>` — Sab ko tag karo 📢\n"
            "`/slowmode <sec>` — Slow mode ⏱️\n"
            "`/lock / /unlock` — Chat lock 🔒\n"
            "`/say <text>` — Bot se bolwao 🗣️\n"
            "`/setflood [n] [sec]` — Flood limit set karo 🚨\n"
            "`/antilink on/off` — Link delete karo 🔗\n"
        ),
        "new": (
            "🌟 *New Features*\n\n"
            "🚨 *Anti-Flood*\n"
            "`/setflood 6 5` — 6 msg in 5s se flood\n"
            "Auto 5-min mute hota hai ❄️\n\n"
            "🔗 *Anti-Link*\n"
            "`/antilink on` — Links auto-delete\n"
            "`/antilink off` — Band karo\n\n"
            "⚖️ *FIR Punishment*\n"
            "`/closefir 3 mute` — 1hr mute\n"
            "`/closefir 3 kick` — Kick bahar\n"
            "`/closefir 3 warn` — Warning\n"
            "`/closefir 3 fine` — 500c fine\n\n"
            "🎯 *Choose Command*\n"
            "`/choose pizza | burger | sushi`\n\n"
            "⚔️ *Street Fight*\n"
            "`/fight` — Reply karke fight karo\n\n"
            "🌤️ *Weather*\n"
            "`/weather Delhi` — Live weather\n\n"
            "🏓 *Ping* — `/ping` — Bot latency\n\n"
            "🎭 *Sticker Reply*\n"
            "Bot ko sticker bhejo ya reply karo — cute response dega!\n\n"
            "🤖 *AI Gaali Response*\n"
            "Gaali doge toh AI se LIVE varied reply — kabhi gaali back, kabhi sweet 😈"
        ),
    }

    arg = ctx.args[0].lower() if ctx.args else "main"
    content = pages.get(arg, pages["main"])

    if arg == "all":
        # Send all pages one by one
        for key in ["game","economy","social","fun","group","admin","new"]:
            await update.message.reply_text(pages[key], parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text(content, parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# STICKER HANDLER
# ═══════════════════════════════════════════════════════════════════

STICKER_REPLIES = [
    "awww yeh toh cute hai 🥺❄️",
    "HAHAHA yeh wala 😭💀 main save kar rahi hoon",
    "omg yaar 😩💕 itna cute kyun hai yeh?!",
    "uff~ mujhe bhi aisa sticker chahiye 🌸",
    "hehe 🙈 yeh mera favorite hai actually",
    "yaar tujhe acche stickers milte kahan hain 😭✨",
    "BHAI 💀 yeh kahan se laya?!",
    "oof~ iss sticker ne dil jeet liya 🥺💗",
    "cute~~ 😊❄️ tujhe bhi aisa hi lagta hai na?",
    "hmmm interesting choice 😌❄️",
    "ab main bhi sticker se reply karti hoon 😤 ... bas text hi kaafi hai ❄️",
    "*sticker dekh ke muskurati hai* 🌸",
    "sach mein yaar 😭 yeh sticker toh heart le gaya",
    "❄️ ... theek hai, yeh acceptable hai 😌",
    "okay okay I see you 👀❄️ cute sticker hai",
]

async def on_sticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.sticker: return
    user = msg.from_user
    if not user or user.is_bot: return
    store_name(user)

    is_private      = msg.chat.type == "private"
    is_reply_to_bot = (msg.reply_to_message and msg.reply_to_message.from_user and
                       msg.reply_to_message.from_user.id == BOT_ID)
    mentioned = BOT_USERNAME and f"@{BOT_USERNAME}".lower() in (msg.caption or "").lower()
    should_reply = is_private or is_reply_to_bot or mentioned

    if not should_reply: return

    await msg.reply_text(pick(STICKER_REPLIES))

# ═══════════════════════════════════════════════════════════════════
# WELCOME / GOODBYE EVENTS
# ═══════════════════════════════════════════════════════════════════

async def on_new_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.new_chat_members: return
    for member in update.message.new_chat_members:
        if member.is_bot: continue
        store_name(member)
        mention = f"[{member.first_name}](tg://user?id={member.id})"
        custom_welcome = get_gsetting(update.effective_chat.id, "welcome")
        if custom_welcome:
            text = custom_welcome.replace("{name}", member.first_name) \
                                 .replace("{mention}", mention) \
                                 .replace("{group}", update.effective_chat.title or "Group")
        else:
            is_admin = await check_admin(update, ctx, member.id)
            lvl = get_level(member.id)
            lvl_name = LEVEL_NAMES[lvl]
            coins = get_coins(member.id)
            group = update.effective_chat.title or "group"
            if is_co_owner(member.id):
                text = pick([
                    f"👑 *Co-Owner aa gaye!*\n\n{mention} — [{lvl_name}]\nWelcome back, sahib! ❄️",
                    f"🌟 *{mention}* — hamare Co-Owner!\n❄️ {group} mein khush amdeed!",
                ])
            elif is_admin:
                text = pick(ADMIN_GREETS) + f"\n\n{mention} ko welcome hai! ❄️"
            else:
                welcomes = [
                    f"❄️ *Ara ara~* ✨\n\n{mention} aa gaye {group} mein!\nMain hoon Yuki — sassy, mysterious, always watching~ 👀\n🏅 Level `{lvl}` — *{lvl_name}*\n\n`/start /daily /kill /rob` se shuru karo!",
                    f"🌸 *Naya snowflake!* ⛄\n\n{mention}, welcome!\nYuki ka duniya mein aaya... hai tum lucky? 🤔❄️\n✨ Level `{lvl}` — *{lvl_name}*\n💡 `/start` karo — rules jaano!",
                    f"🌙 *Hmm...* {mention} join kiya\n\nInteresting choice~ ❄️\n🎭 Main Yuki hoon — anime girl, bot, aur tumhara sabse bada competitor!\n⚔️ Level `{lvl}` | {CUR_S} `{coins:,}` {CUR}\n💀 `/kill /rob /duel` se apna naam banao",
                    f"✨ *Oh?* {mention}!\n\n{group} mein aaye ho... Yuki ki territory mein 😌❄️\n🏅 *{lvl_name}* level pe ho abhi\n🎮 `/daily` se shuru karo — free {CUR} milenge!",
                    f"🌺 *{mention} ka swagat hai!* 🎊\n\n❄️ {group} mein aapka padharo~\nMain Yuki hoon — thodi tsundere, bahut powerful 😤\n✨ Level `{lvl}` ho abhi, `9` tak pahunchna hai!\n⚔️ `/start` karo pehle, bhai/behen!",
                    f"💫 *Naya warrior!* ⚔️\n\n{mention} join ho gaya/gayi!\n❄️ Yuki bot mein khush aaye — yahan sab battle karte hain, rob karte hain, jeete hain!\n🏅 Level `{lvl}` — *{lvl_name}*\n🎯 Target: Level 9 *Eternal Frost* ✨",
                    f"🧊 *Ah, ek aur snowflake~* ❄️\n\n{mention} aa gaya/aayi!\nMain Yuki hoon — 雪 = snow. Yaad raho naam.\n🌙 Level `{lvl}` | {CUR_S} `/daily` karo!\n⚔️ Group mein survive karo ya freeze ho jao 😌",
                ]
                text = pick(welcomes)
        await safe_send(lambda: update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN))

async def on_left_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.left_chat_member: return
    member = update.message.left_chat_member
    if member.is_bot: return
    custom_goodbye = get_gsetting(update.effective_chat.id, "goodbye")
    mention = f"[{member.first_name}](tg://user?id={member.id})"
    if custom_goodbye:
        text = custom_goodbye.replace("{name}", member.first_name) \
                             .replace("{mention}", mention) \
                             .replace("{group}", update.effective_chat.title or "Group")
    else:
        text = pick([
            f"👋 {mention} chale gaye... ❄️ Bye!",
            f"😢 {mention} ne group chhod diya 🌙 Khayaal rakhna",
            f"❄️ {mention} gaye... Zindagi chaalti rehti hai 🌸",
        ])
    await safe_send(lambda: update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN))

# ═══════════════════════════════════════════════════════════════════
# MAIN MESSAGE HANDLER
# ═══════════════════════════════════════════════════════════════════

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text: return
    user = msg.from_user
    if not user or user.is_bot: return
    store_name(user)
    text = msg.text.strip()
    uid  = user.id
    cid  = msg.chat.id

    # ─── Auto-clear AFK ───────────────────────────────────────────
    row = _fetch("SELECT afk_since FROM users WHERE uid=?", (uid,))
    if row and row["afk_since"] > 0:
        _exec("UPDATE users SET afk_since=0, afk_reason='' WHERE uid=?", (uid,))
        await safe_send(lambda: msg.reply_text(
            pick([f"🌸 {user.first_name} wapas aa gaye! AFK clear ❄️",
                  f"❄️ {user.first_name} is back! Welcome~"])))

    # ─── AFK check when replying to someone ───────────────────────
    if msg.reply_to_message:
        replied = msg.reply_to_message.from_user
        if replied:
            afk_row = _fetch("SELECT afk_since, afk_reason FROM users WHERE uid=?", (replied.id,))
            if afk_row and afk_row["afk_since"] > 0:
                elapsed = int(time.time() - afk_row["afk_since"])
                await msg.reply_text(
                    f"😴 *{replied.first_name} AFK hai*\nReason: _{afk_row['afk_reason']}_\n⏰ {secs_hhmm(elapsed)} pehle se ❄️",
                    parse_mode=ParseMode.MARKDOWN)

    # ─── Track active chat for bounty broadcasts ──────────────────
    if msg.chat.type in ("group", "supergroup"):
        track_active_chat(cid)

    # ─── Social XP for chatting (skill tracking only, NOT leveling) ─
    if len(text) > 3 and not text.startswith("/"):
        add_xp(uid, rand(1, 3))  # activity XP for social skill tracking
        add_skill_xp(uid, "social", 1)

    # ─── Hangman guess FIRST (before filters) ────────────────────
    if cid in active_hangman and len(text) == 1 and text.isalpha():
        await hangman_guess(update, ctx)
        return

    # ─── Trivia answer check ──────────────────────────────────────
    if cid in active_trivia and not text.startswith("/"):
        await trivia_answer_check(update, ctx)

    # ─── Keyword filters ──────────────────────────────────────────
    if msg.chat.type in ("group","supergroup"):
        lower = text.lower()
        filters_rows = _fetchall("SELECT keyword, response FROM filters_kw WHERE chat_id=?", (cid,))
        for fr in filters_rows:
            if fr["keyword"] in lower:
                await safe_send(lambda: msg.reply_text(fr["response"], parse_mode=ParseMode.MARKDOWN))
                return

    # ─── Anti-link check ──────────────────────────────────────────
    if msg.chat.type in ("group","supergroup") and cid in antilink_chats:
        if _LINK_RE.search(text):
            try:
                is_adm = await check_admin(update, ctx, uid)
                if not is_adm:
                    await msg.delete()
                    warn_msg = await msg.chat.send_message(
                        pick([
                            f"🔗 {user.first_name} link mat bhejo yahan! ❄️",
                            f"❌ {user.first_name} — no links allowed! ❄️",
                            f"🚫 Link deleted — {user.first_name} rules follow karo ❄️",
                        ])
                    )
                    await asyncio.sleep(5)
                    try: await warn_msg.delete()
                    except: pass
                    return
            except: pass

    # ─── Anti-flood check ─────────────────────────────────────────
    if await check_flood(update, ctx):
        return

    # ─── Gaali detection ──────────────────────────────────────────
    GAALI_WORDS = ["randi","bhosdike","madarchod","behenchod","maderchod","chutiya",
                   "harami","kamina","kutte","bhosdi","bc ","mc ","lodu","gaand",
                   "maa ki","baap ki","behen ki","teri maa","teri behen","teri gand"]
    is_private      = msg.chat.type == "private"
    is_reply_to_bot = (msg.reply_to_message and msg.reply_to_message.from_user and
                       msg.reply_to_message.from_user.id == BOT_ID)
    mentioned_handle = BOT_USERNAME and f"@{BOT_USERNAME}".lower() in text.lower()
    name_mentioned   = "yuki" in text.lower()
    should_reply     = is_private or is_reply_to_bot or mentioned_handle

    has_gaali = any(g in text.lower() for g in GAALI_WORDS)
    if has_gaali and should_reply:
        await ctx.bot.send_chat_action(msg.chat.id, ChatAction.TYPING)
        reply_txt = await yuki_gaali_reply(user.first_name or "tu", text)
        await msg.reply_text(reply_txt)
        return

    # ─── Gaali in group even without mention → random cold stare ──
    if has_gaali and msg.chat.type in ("group","supergroup") and not should_reply:
        if random.random() < 0.3:
            await msg.reply_text(pick([
                f"😐❄️ {user.first_name} zubaan sambhal...",
                f"oof {user.first_name} 😬 itni gaali?",
                f"*sirf ghurna* 😒❄️",
                f"{user.first_name} yeh kya zubaan hai bhai 😶‍🌫️",
            ]))
        return

    # ─── Name mention → short reply ───────────────────────────────
    if name_mentioned and not should_reply and msg.chat.type in ("group","supergroup"):
        await msg.reply_text(pick(YUKI_MENTIONS))
        return

    if not should_reply: return

    clean = text.replace(f"@{BOT_USERNAME}", "").strip() if BOT_USERNAME else text
    if not clean: return

    await ctx.bot.send_chat_action(msg.chat.id, ChatAction.TYPING)
    is_special = (SPECIAL_CHAT_ID != 0 and (uid == SPECIAL_CHAT_ID or cid == SPECIAL_CHAT_ID))
    reply = await yuki_reply(uid, user.first_name or "dost", clean, special=is_special)
    await msg.reply_text(reply)

# ═══════════════════════════════════════════════════════════════════
# AUTO-BOUNTY JOB  (runs every 3 hours via job_queue)
# ═══════════════════════════════════════════════════════════════════

async def auto_bounty_job(context):
    """Every 3 hours: pick a random active user, put a bounty on them."""
    # Pick any registered player with coins, not already a bounty target/dead.
    # The old >500 filter often returned no rows, so no bounty was created.
    rows = _fetchall(
        "SELECT uid FROM users WHERE coins > 0 AND is_bounty_target=0 "
        "AND deaths_until < ? ORDER BY RANDOM() LIMIT 1",
        (int(time.time()),)
    )
    if not rows:
        return
    target_uid = rows[0]["uid"]
    lvl = get_level(target_uid)
    # Bounty: 5,000 → 500,000 range, weighted by level and random spike
    base   = rand(5000, 100000)
    lvl_bonus = lvl * rand(1000, 15000)
    spike  = rand(1, 5)  # 1-in-5 chance of mega bounty
    bounty_amount = min(500000, base + lvl_bonus + (250000 if spike == 1 else 0))
    _exec("UPDATE users SET bounty=bounty+?, is_bounty_target=1 WHERE uid=?",
          (bounty_amount, target_uid))
    name = get_name(target_uid)
    is_mega = bounty_amount >= 200000
    msg_text = (
        f"{'🔥' if is_mega else '🚨'} *{'MEGA ' if is_mega else ''}AUTO BOUNTY ALERT!* {'🔥' if is_mega else '🚨'}\n\n"
        f"🎯 Target: *{name}*\n"
        f"💰 Bounty: *{bounty_amount:,} {CUR}* {CUR_S}\n"
        f"⚔️ Level: `{lvl}` — *{LEVEL_NAMES[lvl]}*\n\n"
        f"Kill karo → bounty collect karo hehe~!\n"
        f"⚡ _Bounty target sirf *30 minute* mein zinda ho jayega!_\n\n"
        f"❄️ `/kill` se target karo!"
    )
    # Broadcast to all active chats (seen in last 48h)
    cutoff = int(time.time()) - 172800
    active = _fetchall("SELECT chat_id FROM active_chats WHERE last_seen > ?", (cutoff,))
    for row in active:
        try:
            await context.bot.send_message(
                row["chat_id"], msg_text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

async def periodic_bounty_loop(application):
    """Fallback scheduler when PTB was installed without the job-queue extra."""
    await asyncio.sleep(120)
    while True:
        try:
            context = type("BountyContext", (), {"bot": application.bot})()
            await auto_bounty_job(context)
        except Exception as e:
            print(f"❌ Bounty scheduler error: {e}")
        await asyncio.sleep(10800)

# ═══════════════════════════════════════════════════════════════════
# XP LEVEL-UP CHECKER  (call after add_xp)
# ═══════════════════════════════════════════════════════════════════

async def check_levelup(update, uid, old_lvl):
    """Send level-up message if user leveled up."""
    new_lvl = get_level(uid)
    if new_lvl > old_lvl:
        bonus = new_lvl * 500
        add_coins(uid, bonus)
        reward_txt = f"+{bonus:,} {CUR} {CUR_S} bonus!"
        try:
            await update.message.reply_text(
                f"🎉 *LEVEL UP!* 🎊\n\n"
                f"❄️ {get_name(uid)}\n"
                f"🏅 Level `{old_lvl}` → Level `{new_lvl}`\n"
                f"✨ *{LEVEL_NAMES[new_lvl]}*\n\n"
                f"💰 {reward_txt}\n"
                f"❄️ Aage badhte raho!",
                parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════
# NEW GAME COMMANDS v3
# ═══════════════════════════════════════════════════════════════════

# ─── /nwat — playful slap fight ───────────────────────────────────
async def cmd_nwat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo /nwat se!")
    if t.id == user.id: return await update.message.reply_text("Khud ko nwat? 😐❄️")
    if t.id == BOT_ID: return await update.message.reply_text(pick([
        "Mujhe nwat? ❄️ Main freeze kar dungi tumhara haath!",
        "Try karo... *ice shield activate* 🧊❄️"]))
    nwat_lines = [
        f"👋 *NWAT!* {get_mention(user)} ne {get_mention(t)} ko ek zordaar thappad mara! 😤❄️",
        f"💥 *NWAAAAAT!* {get_mention(user)} ka haath gaya seedha {get_mention(t)} ke gaal pe! 😂",
        f"👋 {get_mention(user)} ne {get_mention(t)} ko itna nwat maara... bechara 5 second ghoomta raha 😵❄️",
        f"😤 *THAPPAD!* {get_mention(user)} ne {get_mention(t)} ko nwat diya! Gaali nahi dena tha na! ❄️",
        f"🌪️ {get_mention(user)} ka *nwat* itna zor ka tha ke {get_mention(t)} uda! 💨❄️",
    ]
    add_xp(user.id, 2)
    await update.message.reply_text(pick(nwat_lines), parse_mode=ParseMode.MARKDOWN)

# ─── /mwat — dramatic death punch ─────────────────────────────────
async def cmd_mwat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo /mwat se!")
    if t.id == user.id: return await update.message.reply_text("Khud pe mwat? Bhai therapy le lo 🫂❄️")
    if t.id == BOT_ID: return await update.message.reply_text(
        "Main ice se bani hoon, mwat mere through nikal jaata hai 😌❄️")
    mwat_lines = [
        f"☠️ *MWAT!* {get_mention(user)} ne {get_mention(t)} ko ekdum dramatic andaaz mein maar diya! 💀❄️",
        f"💀 *MWAAAAT!* {get_mention(t)} ko {get_mention(user)} ne ek hi mukke mein andar kar diya! 😵‍💫",
        f"⚡ {get_mention(user)} ka *mwat* ek bijli ki tarah gira {get_mention(t)} pe! Bechara 💀❄️",
        f"🥊 *MWAT MWAT MWAT!* {get_mention(user)} ne {get_mention(t)} pe punch baraaye! Khatam story 💀",
        f"☠️ {get_mention(t)} — *last seen after getting mwat-ted by {get_mention(user)}* 💀❄️",
    ]
    add_xp(user.id, 2)
    await update.message.reply_text(pick(mwat_lines), parse_mode=ParseMode.MARKDOWN)

# ─── /slots — slot machine ────────────────────────────────────────
async def cmd_slots(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    if not ctx.args: return await update.message.reply_text(
        f"❄️ `/slots <{CUR.lower()}>` ya `/slots all`\nMin: 50 {CUR}")
    bet_str = ctx.args[0].lower()
    bal = get_coins(user.id)
    bet = bal if bet_str == "all" else (int(bet_str) if bet_str.isdigit() else 0)
    if bet < 50: return await update.message.reply_text(f"Min 50 {CUR} ❄️")
    if bal < bet: return await update.message.reply_text(f"Itne {CUR} nahi hain! 💸")
    slots_items = ["🍒","🍋","🍇","⭐","💎","❄️","🎰","🔔","🍀","🌸"]
    r = [random.choice(slots_items) for _ in range(3)]
    msg_txt = f"🎰 *SLOTS!*\n\n`[ {r[0]} | {r[1]} | {r[2]} ]`\n\n"
    if r[0] == r[1] == r[2] == "💎":
        win = bet * 10; add_coins(user.id, win - bet); apply_tax(win)
        msg_txt += f"💎💎💎 *DIAMOND JACKPOT!* 💎💎💎\n+`{win-bet:,}` {CUR}! WOAH! ❄️"
        add_xp(user.id, 50)
    elif r[0] == r[1] == r[2] == "❄️":
        win = bet * 7; add_coins(user.id, win - bet); apply_tax(win)
        msg_txt += f"❄️❄️❄️ *YUKI JACKPOT!* ❄️❄️❄️\n+`{win-bet:,}` {CUR}! Yuki ka ashirvaad! 🌸"
        add_xp(user.id, 30)
    elif r[0] == r[1] == r[2]:
        win = bet * 5; add_coins(user.id, win - bet); apply_tax(win)
        msg_txt += f"✨ *Jackpot!* Teeno same!\n+`{win-bet:,}` {CUR}! ❄️"
        add_xp(user.id, 20)
    elif r[0] == r[1] or r[1] == r[2] or r[0] == r[2]:
        win = int(bet * 1.5); add_coins(user.id, win - bet); apply_tax(win)
        msg_txt += f"🎊 *2 Match!*\n+`{win-bet:,}` {CUR} ❄️"
        add_xp(user.id, 5)
    else:
        add_coins(user.id, -bet); apply_tax(bet)
        msg_txt += f"😢 Kuch nahi... `-{bet:,}` {CUR} 💸\n❄️ Phir se try karo~"
    msg_txt += f"\n\n💰 Balance: `{get_coins(user.id):,}` {CUR}"
    await update.message.reply_text(msg_txt, parse_mode=ParseMode.MARKDOWN)

# ─── /dice — dice battle ──────────────────────────────────────────
DICE_GAMES: dict = {}
async def cmd_dice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    if not ctx.args: return await update.message.reply_text(
        f"❄️ `/dice <{CUR.lower()}>` — kisi ko reply karke challenge karo!")
    bet_str = ctx.args[0]
    bet = get_coins(user.id) if bet_str.lower() == "all" else (int(bet_str) if bet_str.isdigit() else 0)
    if bet < 50: return await update.message.reply_text(f"Min 50 {CUR} ❄️")
    if get_coins(user.id) < bet: return await update.message.reply_text(f"Itne {CUR} nahi hain!")
    if not update.message.reply_to_message:
        return await update.message.reply_text("❄️ Kisi ko reply karo dice challenge ke liye!")
    opp = update.message.reply_to_message.from_user; store_name(opp)
    if opp.id == user.id: return await update.message.reply_text("Khud se dice? ❄️")
    if get_coins(opp.id) < bet:
        return await update.message.reply_text(f"❄️ {get_name(opp.id)} ke paas {bet:,} {CUR} nahi hain!")
    # Play immediately
    my_roll = rand(1, 6); opp_roll = rand(1, 6)
    dice_face = ["", "1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣"]
    txt = (f"🎲 *Dice Battle!*\n\n"
           f"{get_mention(user)} → {dice_face[my_roll]} (`{my_roll}`)\n"
           f"{get_mention(opp)} → {dice_face[opp_roll]} (`{opp_roll}`)\n\n")
    if my_roll > opp_roll:
        add_coins(user.id, bet); add_coins(opp.id, -bet); apply_tax(bet)
        txt += f"🏆 {get_mention(user)} jeeta! +`{bet:,}` {CUR} ❄️"; add_xp(user.id, 10)
    elif opp_roll > my_roll:
        add_coins(opp.id, bet); add_coins(user.id, -bet); apply_tax(bet)
        txt += f"🏆 {get_mention(opp)} jeeta! +`{bet:,}` {CUR} ❄️"; add_xp(opp.id, 10)
    else:
        txt += f"🤝 Draw! Koi coin nahi gaya ❄️"
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)

# ─── /guess — number guessing game ───────────────────────────────
GUESS_GAMES: dict = {}  # chat_id → {number, attempts, uid}
async def cmd_guess(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    cid = update.effective_chat.id
    if not ctx.args:
        # Start a new game
        if cid in GUESS_GAMES:
            g = GUESS_GAMES[cid]
            return await update.message.reply_text(
                f"🎯 Pehle se ek game chal raha hai!\n"
                f"1 se 100 ke beech guess karo... {g['attempts']} attempts baki hain 🔢❄️")
        num = rand(1, 100)
        GUESS_GAMES[cid] = {"number": num, "attempts": 7, "uid": user.id}
        return await update.message.reply_text(
            f"🎯 *Number Guess!*\n\n"
            f"Maine 1 se 100 ke beech ek number socha hai 🧊\n"
            f"7 chances hain! Number type karo (reply nahi, seedha likho)\n"
            f"❄️ Hint: `/guess stop` se band karo", parse_mode=ParseMode.MARKDOWN)
    if ctx.args[0].lower() == "stop":
        if cid in GUESS_GAMES:
            num = GUESS_GAMES.pop(cid)["number"]
            return await update.message.reply_text(f"🎯 Game band! Number tha: `{num}` ❄️",
                                                    parse_mode=ParseMode.MARKDOWN)
        return await update.message.reply_text("Koi game nahi chal raha ❄️")
    if ctx.args[0].isdigit() and cid in GUESS_GAMES:
        g = GUESS_GAMES[cid]; guess = int(ctx.args[0])
        g["attempts"] -= 1
        if guess == g["number"]:
            win = 300; add_coins(user.id, win); add_xp(user.id, 20)
            del GUESS_GAMES[cid]
            return await update.message.reply_text(
                f"✅ *Sahi!* `{guess}` ❄️\n+`{win}` {CUR} bonus! 🎉", parse_mode=ParseMode.MARKDOWN)
        hint = "⬆️ Zyada" if guess < g["number"] else "⬇️ Kam"
        if g["attempts"] <= 0:
            del GUESS_GAMES[cid]
            return await update.message.reply_text(
                f"💀 Attempts khatam! Number tha: `{g['number']}` ❄️", parse_mode=ParseMode.MARKDOWN)
        return await update.message.reply_text(
            f"{hint} — {g['attempts']} chances baki ❄️", parse_mode=ParseMode.MARKDOWN)
    return await update.message.reply_text("❄️ `/guess` — game start karo!", parse_mode=ParseMode.MARKDOWN)

# ─── /rate — rate someone ─────────────────────────────────────────
async def cmd_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else user
    rating = rand(1, 10)
    comments = {
        1:  "😬 Bhai... kya bolu. Mehnat karo.",
        2:  "💀 Thoda aur try karo... thoda.",
        3:  "😅 Theek hai, theek hai. Average se neeche.",
        4:  "🙂 Chal, average ke qareeb ho.",
        5:  "😐 Ekdum average. Na zyada na kam.",
        6:  "👍 Thode se upar ho! Achha hai.",
        7:  "✨ Acchhe ho! Keep going ❄️",
        8:  "🌟 Bahut acche! Almost perfect!",
        9:  "💎 Kaafi impressive ho! ❄️",
        10: "❄️ 10/10 — Perfect! Yuki approve karti hai! 🌸",
    }
    bar = "⭐" * rating + "☆" * (10 - rating)
    await update.message.reply_text(
        f"⭐ *Rating*\n\n{get_mention(t)}\n\n`{bar}`\n*Score: {rating}/10*\n\n_{comments[rating]}_",
        parse_mode=ParseMode.MARKDOWN)

# ─── /flex — flex your stats ──────────────────────────────────────
async def cmd_flex(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    uid = user.id
    coins = get_coins(uid); kills = get_kills(uid); xp = get_xp(uid); lvl = get_level(uid)
    flex_msgs = [
        f"💪 *{user.first_name} FLEX!*\n\n{CUR_S} `{coins:,}` {CUR} in bank!\n⚔️ `{kills}` kills!\n✨ Level `{lvl}` — *{LEVEL_NAMES[lvl]}*\n\n❄️ Dekha? Abhi aur badhna hai!",
        f"😎 *{user.first_name} ka power level:*\n\n💰 `{coins:,}` {CUR}\n🗡️ `{kills}` kills\n⚡ `{xp:,}` XP\n\n❄️ Impressive hai... thoda.",
        f"🌟 *{user.first_name} bola: 'Dekho mujhe!'*\n\n🏅 *{LEVEL_NAMES[lvl]}*\n💎 `{coins:,}` {CUR}\n⚔️ `{kills}` kills\n\n❄️ Sahi hai sahi hai...",
    ]
    await update.message.reply_text(pick(flex_msgs), parse_mode=ParseMode.MARKDOWN)

# ─── /clap — sarcastic clap ───────────────────────────────────────
async def cmd_clap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    name = get_mention(t) if t else (update.effective_user.first_name)
    clap_msgs = [
        f"👏 Waah waah {name}... *bahut khub* 👏\n❄️ *slow clap continues*",
        f"👏👏👏 Kya baat hai {name}! Itna toh socha hi nahi tha! 😐❄️",
        f"🙄 *clap clap* Wah {name} wah. Genius ho tum. Clearly. 👏❄️",
        f"👏 {name} ne kuch aisa kiya ke... *clapping intensifies sarcastically* ❄️",
    ]
    await update.message.reply_text(pick(clap_msgs), parse_mode=ParseMode.MARKDOWN)

# ─── /scenario — random fun scenario ─────────────────────────────
SCENARIOS = [
    "🌪️ {name} ek baar so gaya/gayi aur sapne mein Yuki ne unhe ek frozen world mein bhej diya! Ab wahan se niklo! ❄️",
    "😱 {name} ne galti se group ka admin password delete kar diya! Sab bhaag rahe hain! ❄️",
    "🧊 {name} ek secret society ka member ban gaya/gayi jahan sab log barf mein khel hain... welcome ❄️",
    "🎭 {name} ko ek NPC ki bhoomika mili ek RPG game mein... aur players unhe kill karte rehe! 💀",
    "🌙 Raat ko 3 baje {name} ko message aaya: 'Yuki tumhe bula rahi hai ❄️' — kya karte ho?",
    "🍜 {name} ne ek magic noodle khaya... ab unhe har cheez mein anime dikh raha hai! 🎌",
    "💤 {name} boring lecture mein so gaya/gayi aur sapne mein boss fight aaya! ⚔️❄️",
    "🎪 {name} ek talent show mein phoosi gayi/gayi... unka talent tha — 'nothing' 😐❄️",
    "🦊 {name} ek fox spirit se cursed ho gaya/gayi! Ab har sentence ke baad 'kon kon' bolte hain 🦊❄️",
    "📱 {name} ka phone Yuki ne le liya. Woh sab read kar rahi hai. *nervous* ❄️",
]
async def cmd_scenario(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else user
    s = pick(SCENARIOS).format(name=get_mention(t))
    await update.message.reply_text(f"📖 *Random Scenario!*\n\n{s}", parse_mode=ParseMode.MARKDOWN)

# ─── /poke — poke someone ─────────────────────────────────────────
async def cmd_poke(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    t = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not t: return await update.message.reply_text("❄️ Kisi ko reply karo /poke se!")
    poke_lines = [
        f"👉 {get_mention(user)} ne {get_mention(t)} ko poke kiya! *poke poke* ❄️",
        f"☝️ Hey {get_mention(t)}, {get_mention(user)} tumhara dhyan chahta/chahti hai! ❄️",
        f"👈 *poke* {get_mention(t)} uthao nazar! {get_mention(user)} bula raha/rahi hai ❄️",
    ]
    await update.message.reply_text(pick(poke_lines), parse_mode=ParseMode.MARKDOWN)

# ─── /xp — see your XP and level ─────────────────────────────────
async def cmd_xp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    store_name(user); uid = user.id
    kills_cur = get_kills(uid)
    lvl       = get_level(uid)
    nxt       = kills_for_next(uid)
    next_txt  = f"{nxt:,} kills" if nxt else "MAX ✨"
    prev      = KILL_THRESHOLDS[lvl]
    if nxt:
        prog = int(((kills_cur - prev) / (nxt - prev)) * 20)
        bar = "█" * max(0, prog) + "░" * max(0, 20 - prog)
    else:
        bar = "█" * 20
    # Show top skills summary too
    skill_lines = ""
    for sk, info in list(SKILLS.items())[:3]:
        sl = get_skill_level(uid, sk)
        skill_lines += f"  {info['emoji']} {info['name']}: Lv.`{sl}`\n"
    await update.message.reply_text(
        f"⚔️ *{user.first_name} ka Level*\n\n"
        f"🏅 Level `{lvl}` — *{LEVEL_NAMES[lvl]}*\n"
        f"⚔️ Kills: `{kills_cur:,}` / `{next_txt}`\n"
        f"`[{bar}]`\n\n"
        f"📊 *Level Thresholds:*\n"
        f"  Lv.1 → `200` kills | Lv.2 → `500`\n"
        f"  Lv.3 → `1,000` | Lv.4 → `2,000`\n"
        f"  Lv.5 → `4,000` | Lv.6 → `7,000`\n"
        f"  Lv.9 → `35,000` kills ✨\n\n"
        f"⚡ *Top Skills:*\n{skill_lines}"
        f"\n🏆 Level up hone pe {CUR_S} {CUR} bonus milta hai!",
        parse_mode=ParseMode.MARKDOWN)

# ─── /memory — save/view personal memories ────────────────────────
async def cmd_memory(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user); uid = user.id
    if not ctx.args:
        # Show memories list
        mems = _fetchall("SELECT id, label, ts FROM memories WHERE uid=? ORDER BY ts DESC LIMIT 10", (uid,))
        if not mems:
            return await update.message.reply_text(
                f"🧠 *Memory Bank — {user.first_name}*\n\nKoi memory save nahi hai!\n"
                f"❄️ `/memory save <label>` — kisi message ko reply karke save karo\n"
                f"❄️ `/memory view <id>` — memory dekho\n"
                f"❄️ `/memory del <id>` — delete karo",
                parse_mode=ParseMode.MARKDOWN)
        txt = f"🧠 *{user.first_name}'s Memories*\n\n"
        for m in mems:
            dt = datetime.fromtimestamp(m["ts"]).strftime("%d/%m")
            txt += f"`#{m['id']}` — {m['label']} _{dt}_\n"
        txt += f"\n❄️ `/memory view <id>` se dekho"
        return await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)
    sub = ctx.args[0].lower()
    if sub == "save":
        if not update.message.reply_to_message:
            return await update.message.reply_text("❄️ Kisi message ko reply karo `/memory save <label>` se!")
        label = " ".join(ctx.args[1:]) or "untitled"
        content = update.message.reply_to_message.text or update.message.reply_to_message.caption or "[media]"
        _exec("INSERT INTO memories (uid, label, content, ts) VALUES (?,?,?,?)",
              (uid, label[:50], content[:500], int(time.time())))
        return await update.message.reply_text(f"🧠 Memory save ho gayi! Label: *{label}* ❄️",
                                                parse_mode=ParseMode.MARKDOWN)
    if sub == "view" and len(ctx.args) > 1 and ctx.args[1].isdigit():
        mid = int(ctx.args[1])
        row = _fetch("SELECT label, content, ts FROM memories WHERE id=? AND uid=?", (mid, uid))
        if not row: return await update.message.reply_text("❄️ Memory nahi mili ya aapki nahi hai!")
        dt = datetime.fromtimestamp(row["ts"]).strftime("%d/%m/%Y %H:%M")
        return await update.message.reply_text(
            f"🧠 *Memory #{mid}* — _{row['label']}_\n📅 {dt}\n\n{row['content']}",
            parse_mode=ParseMode.MARKDOWN)
    if sub == "del" and len(ctx.args) > 1 and ctx.args[1].isdigit():
        mid = int(ctx.args[1])
        _exec("DELETE FROM memories WHERE id=? AND uid=?", (mid, uid))
        return await update.message.reply_text(f"🗑️ Memory #{mid} delete ho gayi ❄️")
    await update.message.reply_text(
        "❄️ Commands:\n`/memory` — list\n`/memory save <label>` — save\n`/memory view <id>` — view\n`/memory del <id>` — delete",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# NEW FUN COMMANDS (v5)
# ═══════════════════════════════════════════════════════════════════

_GOOD_MORNINGS = [
    "🌸 *Goood morning~* ☀️\nAaj ka din bohot achha hoga hehe~ ❄️ utha utha utha!!",
    "☀️ *Good morning!* 🌻\nSona chhod!! Din shuru karo — Yuki aa gayi hehe~ ❄️",
    "🌅 Uthoo uthoo uthoo!! 😭 Din nikal aaya\nGood morning jaan hehe~ ❄️✨",
    "☕ *Good morniiing~* 🌸\nNaashta kiya? Nahi toh roo dungi main 😭 hehe~",
]
_GOOD_NIGHTS = [
    "🌙 *Good night~* ⭐\nAchhe sapne aayein hehe~ ❄️ Soja ab theek se!",
    "😴 *Shubh raatri~* 🌸\nKal milte hain — Yuki wait karegi hehe~ ❄️💕",
    "🌙 Jao jao so jao 😭 bahut raat ho gayi!\n*Good night* hehe~ ❄️✨",
    "⭐ *Good night* jaan~\nSapnon mein bhi Yuki yaad aayegi hehe~ ❄️🌸",
]
_COMPLIMENTS = [
    "Tum toh ekdum super duper amazing ho hehe~ 🌸❄️",
    "Sachchi? Tum itne acche lagte ho na — mujhe toh acha lag jata hai 🥺✨",
    "Ohhh tum toh bilkul BEST ho!! hehe~ 💕❄️ main sach bol rahi hun!",
    "Tumhara smile toh ekdum cute hai na hehe~ 🙈🌸",
    "Tum ho toh Yuki bahut khush rehti hai hehe~ ❄️💗",
    "Arey tum toh ek number insaan ho!! Sachchi!! 🥺✨ hehe~",
]
_VIBES = [
    "🌸 *Aaj ki vibe:* Sab kuch sahi rahega, fikar mat karo hehe~ ❄️",
    "✨ *Aaj ki vibe:* Bilkul cozy blanket wali feeling — ghar pe raho hehe~ 🌙",
    "💕 *Aaj ki vibe:* Kisi ko cute message bhejo — unka din ban jayega hehe~ ❄️🌸",
    "🎵 *Aaj ki vibe:* Favorite song suno aur nacho!! hehe~ 😭💀",
    "☀️ *Aaj ki vibe:* Aaj kuch naya try karo — Yuki support mein hai hehe~ ❄️✨",
    "🍦 *Aaj ki vibe:* Ice cream khao aur relax karo!! Life short hai hehe~ 🥺",
    "⚡ *Aaj ki vibe:* Aaj ka din aapka hai — koi rok nahi sakta hehe~ 💪❄️",
]
_SONGS = [
    "🎵 *la la la~ ❄️*\n_Yuki gaa rahi hai aur sharmaa bhi rahi hai hehe~_ 🙈🌸",
    "🎶 *hmm hmm hmm~*\n_Tune nahi pata mujhe par dil se gaa rahi hun hehe~_ 😭💕",
    "🎵 *do re mi fa so la ti do~* ❄️\n_Yuki opera mode ON hehe~ 😂🌸_",
    "🎶 *♪ snow falling softly ♪*\n*♪ Yuki singing to you ♪* hehe~ ❄️💗",
]

async def cmd_goodmorning(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    name = target.first_name if target else user.first_name
    msg = pick(_GOOD_MORNINGS).replace("{name}", name)
    await update.message.reply_text(f"@{user.username or user.first_name} 👋\n\n{msg}" if target else msg,
                                    parse_mode=ParseMode.MARKDOWN)

async def cmd_goodnight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    name = target.first_name if target else user.first_name
    msg = pick(_GOOD_NIGHTS).replace("{name}", name)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_compliment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else user
    store_name(target)
    c = pick(_COMPLIMENTS)
    await update.message.reply_text(
        f"💌 *{get_name(target.id)}* ke liye Yuki ka compliment:\n\n{c}",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_vibe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(pick(_VIBES), parse_mode=ParseMode.MARKDOWN)

async def cmd_sing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(pick(_SONGS), parse_mode=ParseMode.MARKDOWN)

async def cmd_lovemeter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; store_name(user)
    msg  = update.message
    target = msg.reply_to_message.from_user if msg.reply_to_message else None
    if not target or target.id == user.id:
        return await msg.reply_text(
            "💕 *Love Meter*\n\nKisi ko reply karo `/lovemeter` se hehe~\n_Dono ki compatibility check karein!_ 🌸❄️",
            parse_mode=ParseMode.MARKDOWN)
    store_name(target)
    # Deterministic but fun: seed with both IDs so same pair always gives same result
    seed_val = (min(user.id, target.id) * 1000003 + max(user.id, target.id)) % 101
    pct = seed_val  # 0–100

    # Build heart bar
    filled   = pct // 10
    empty    = 10 - filled
    bar      = "❤️" * filled + "🖤" * empty

    if pct >= 90:
        verdict = "🔥 *SOULMATES!* Yeh toh match made in heaven hai! 😍❄️"
        mood    = "hehe~ main toh blush kar gayi dekh ke 🙈💕"
    elif pct >= 75:
        verdict = "💕 *Super Compatible!* Yeh dono toh BEST pair hain! 🌸"
        mood    = "awwww itna cute hehe~ 🥺"
    elif pct >= 55:
        verdict = "💗 *Good Match!* Thodi aur koshish karo hehe~ ❄️"
        mood    = "nice nice hehe~ 💕"
    elif pct >= 35:
        verdict = "💛 *Average..* Dono mein spark chahiye! ✨"
        mood    = "hmm... kuch toh hai na hehe~ 😶"
    elif pct >= 15:
        verdict = "💔 *Low Compatibility* Mushkil hai yaar 😭"
        mood    = "arre roo mat hehe~ koi aur milega 🥺"
    else:
        verdict = "🖤 *Zero Spark!* Yeh dono... bilkul nahi! 💀❄️"
        mood    = "hehe~ sorry sorry 😭 Yuki bhi kuch nahi kar sakti~"

    await msg.reply_text(
        f"💕 *Love Meter* 💕\n\n"
        f"👤 {get_mention(user)}\n"
        f"💘 + 👤 {get_mention(target)}\n\n"
        f"{bar}\n"
        f"*{pct}%* compatibility ❄️\n\n"
        f"{verdict}\n\n"
        f"_Yuki says: {mood}_",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_setspecial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """King command: set SPECIAL_CHAT_ID at runtime"""
    global SPECIAL_CHAT_ID
    if not is_king(update.effective_user.id):
        return await update.message.reply_text("👑 King only ❄️")
    if ctx.args and ctx.args[0].lstrip('-').isdigit():
        SPECIAL_CHAT_ID = int(ctx.args[0])
        await update.message.reply_text(
            f"💖 Special chat set: `{SPECIAL_CHAT_ID}` ❄️\nWoh chat ab extra special treatment paayega hehe~",
            parse_mode=ParseMode.MARKDOWN)
    elif ctx.args and ctx.args[0].lower() in ("off", "0", "none"):
        SPECIAL_CHAT_ID = 0
        await update.message.reply_text("💔 Special chat disabled ❄️")
    else:
        status = f"`{SPECIAL_CHAT_ID}`" if SPECIAL_CHAT_ID else "disabled"
        await update.message.reply_text(
            f"💖 *Special Chat*\n\nStatus: {status}\n\n"
            f"Set: `/setspecial <chat_id>`\nDisable: `/setspecial off`",
            parse_mode=ParseMode.MARKDOWN)

# ─── /addxp — king command ─────────────────────────────────────────
async def cmd_addxp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_king(update.effective_user.id): return await update.message.reply_text("👑 King only ❄️")
    if not update.message.reply_to_message or not ctx.args:
        return await update.message.reply_text("Reply + amount: /addxp <n>")
    t = update.message.reply_to_message.from_user; store_name(t)
    amount = int(ctx.args[0]) if ctx.args[0].lstrip('-').isdigit() else 0
    add_xp(t.id, amount)
    await update.message.reply_text(
        f"👑 Done! {get_mention(t)} → +{amount} XP ❄️\nTotal XP: {get_xp(t.id):,} | Level: {get_level(t.id)}",
        parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    global BOT_USERNAME, BOT_ID

    if not TOKEN:
        print(
            "Telegram bot token not configured. "
            "Set TELEGRAM_BOT_TOKEN (or BOT_TOKEN) in the hosting panel "
            "before starting the bot."
        )
        return
    app = Application.builder().token(TOKEN).build()

    cmds = [
        ("start", cmd_start), ("forget", cmd_forget),
        ("profile", cmd_profile), ("balance", cmd_balance), ("coins", cmd_balance),
        ("streak", cmd_streak),
        ("premium", cmd_premium), ("premiumstatus", cmd_premium),
        ("premiumgrant", cmd_premiumgrant), ("ludo", cmd_ludo),
        ("kill", cmd_kill), ("revive", cmd_revive), ("rob", cmd_rob),
        ("shield", cmd_shield), ("daily", cmd_daily),
        ("gamble", cmd_gamble), ("give", cmd_give), ("cf", cmd_cf),
        ("leaderboard", cmd_leaderboard), ("mvp", cmd_mvp), ("king", cmd_king),
        ("top", cmd_leaderboard), ("alive", cmd_alive),
        ("store", cmd_store), ("buy", cmd_buy), ("inventory", cmd_inventory),
        ("duel", cmd_duel), ("lottery", cmd_lottery), ("bounty", cmd_bounty),
        ("rps", cmd_rps), ("hangman", cmd_hangman), ("trivia", cmd_trivia), ("hint", cmd_hint),
        ("marry", cmd_marry), ("divorce", cmd_divorce), ("couple", cmd_couple),
        ("fir", cmd_fir), ("cases", cmd_cases), ("closefir", cmd_close_fir),
        ("afk", cmd_afk), ("fight", cmd_fight),
        ("choose", cmd_choose), ("say", cmd_say), ("toss", cmd_toss),
        ("ping", cmd_ping), ("weather", cmd_weather), ("setflood", cmd_setflood),
        ("royal", cmd_royal), ("punish", cmd_punish), ("pardon", cmd_pardon),
        ("addcoin", cmd_addcoins), ("addcoins", cmd_addcoins), ("rmcoins", cmd_rmcoins),
        ("broadcast", cmd_broadcast), ("addxp", cmd_addxp),
        ("kiss", cmd_kiss), ("hug", cmd_hug), ("slap", cmd_slap),
        ("punch", cmd_punch), ("pat", cmd_pat), ("love", cmd_love),
        ("baka", cmd_baka), ("bonk", cmd_bonk), ("cuddle", cmd_cuddle),
        ("bite", cmd_bite), ("lick", cmd_lick), ("wave", cmd_wave),
        ("waifu", cmd_waifu), ("ship", cmd_ship), ("roast", cmd_roast),
        ("truth", cmd_truth), ("dare", cmd_dare), ("roll", cmd_roll),
        ("flip", cmd_flip), (["8ball","ball"], cmd_8ball),
        ("quote", cmd_quote), ("joke", cmd_joke), ("calc", cmd_calc),
        ("anime", cmd_anime), ("manga", cmd_manga),
        ("save", cmd_save), ("get", cmd_get), ("notes", cmd_notes), ("delnote", cmd_delnote),
        ("filter", cmd_filter), ("filters", cmd_filters),
        ("stopfilter", cmd_stopfilter), ("removefilter", cmd_removefilter),
        ("setwelcome", cmd_setwelcome), ("setgoodbye", cmd_setgoodbye), ("resetwelcome", cmd_resetwelcome),
        ("setrules", cmd_setrules), ("rules", cmd_rules),
        ("report", cmd_report), ("slowmode", cmd_slowmode),
        ("lock", cmd_lock), ("unlock", cmd_unlock),
        ("ban", cmd_ban), ("unban", cmd_unban), ("kick", cmd_kick),
        ("tban", cmd_tban), ("mute", cmd_mute), ("unmute", cmd_unmute), ("tmute", cmd_tmute),
        ("warn", cmd_warn), ("unwarn", cmd_unwarn), ("pin", cmd_pin), ("unpin", cmd_unpin),
        ("id", cmd_id), ("ginfo", cmd_ginfo), ("admins", cmd_admins),
        ("tagall", cmd_tagall), ("purge", cmd_purge),
        ("promote", cmd_promote), ("demote", cmd_demote),
        ("stats", cmd_stats),
        ("antilink", cmd_antilink),
        ("help", cmd_help),
        # ─── New v3 commands ───────────────────────────────────────
        ("nwat", cmd_nwat), ("mwat", cmd_mwat),
        ("slots", cmd_slots), ("dice", cmd_dice),
        ("guess", cmd_guess),
        ("rate", cmd_rate), ("flex", cmd_flex),
        ("clap", cmd_clap), ("scenario", cmd_scenario),
        ("poke", cmd_poke), ("xp", cmd_xp),
        ("memory", cmd_memory),
        # v4.0 features
        ("owner", cmd_owner),
        ("skills", cmd_skills), ("skill", cmd_skills),
        ("bank", cmd_bank),
        ("deposit", cmd_deposit),
        ("withdraw", cmd_withdraw),
        ("rpsbattle", cmd_rpsbattle), ("rpsb", cmd_rpsbattle),
        # ─── New v5 commands ───────────────────────────────────────
        ("gm", cmd_goodmorning), ("goodmorning", cmd_goodmorning),
        ("gn", cmd_goodnight), ("goodnight", cmd_goodnight),
        ("compliment", cmd_compliment), ("vibe", cmd_vibe),
        ("sing", cmd_sing), ("setspecial", cmd_setspecial),
        ("lovemeter", cmd_lovemeter), ("love", cmd_lovemeter),
    ]
    for entry in cmds:
        app.add_handler(CommandHandler(entry[0], entry[1]))

    app.add_handler(CallbackQueryHandler(duel_callback,          pattern=r"^duel_"))
    app.add_handler(CallbackQueryHandler(marry_callback,         pattern=r"^marry_"))
    app.add_handler(CallbackQueryHandler(help_callback,          pattern=r"^help_"))
    app.add_handler(CallbackQueryHandler(rps_callback,           pattern=r"^rps_"))
    app.add_handler(CallbackQueryHandler(filter_remove_callback, pattern=r"^rmfilter_"))
    app.add_handler(CallbackQueryHandler(premium_payment_callback, pattern=r"^premium_order_"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, cmd_web_app_data))
    app.add_handler(MessageHandler(filters.Sticker.ALL, on_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # ─── Auto-Bounty Job: every 3 hours ───────────────────────────
    if app.job_queue:
        app.job_queue.run_repeating(auto_bounty_job, interval=10800, first=120)
        print("✅ Auto-Bounty job scheduled (every 3 hours)")

    async def post_init(application):
        global BOT_USERNAME, BOT_ID
        try:
            me = await application.bot.get_me()
            BOT_USERNAME = me.username or ""
            BOT_ID = me.id
            print(f"✅ Yuki Bot Ultra v5.0 — @{BOT_USERNAME} (id={BOT_ID})")
            print(f"💾 Database: {DB_FILE}")
        except Exception as e:
            print(f"❌ post_init error: {e}")
        if not application.job_queue:
            # python-telegram-bot only exposes JobQueue when installed with
            # the optional job-queue dependency. Keep bounty working either way.
            application.bot_data["bounty_task"] = asyncio.create_task(
                periodic_bounty_loop(application)
            )
            print("✅ Auto-Bounty fallback scheduler scheduled (every 3 hours)")
        bot_cmds = [
            BotCommand("start","Yuki se milo ❄️"),
            BotCommand("profile","Apni profile 📊"),
            BotCommand("balance","Wallet balance 💰"),
            BotCommand("daily","Daily reward + streak 🎁"),
            BotCommand("premium","Premium plans and benefits 💎"),
            BotCommand("ludo","Premium Ludo room 🎲"),
            BotCommand("kill","Kisi ko kill karo ⚔️"),
            BotCommand("rob","Coins churaao 💰"),
            BotCommand("duel","1v1 duel karo ⚔️"),
            BotCommand("rps","Rock Paper Scissors ✊"),
            BotCommand("hangman","Word guessing game 🔤"),
            BotCommand("trivia","Quiz game 🧠"),
            BotCommand("gamble","Gamble karo 🎰"),
            BotCommand("store","Shop dekho 🛍️"),
            BotCommand("leaderboard","Top players 🏆"),
            BotCommand("anime","Anime search 🎌"),
            BotCommand("marry","Propose karo 💍"),
            BotCommand("kiss","Kiss karo 💋"),
            BotCommand("baka","BAKA bolo 😤"),
            BotCommand("truth","Truth ya dare 😇"),
            BotCommand("dare","Dare 😈"),
            BotCommand("quote","Yuki ki quote ✨"),
            BotCommand("report","Admin ko report 🚨"),
            BotCommand("notes","Saved notes dekho 📝"),
            BotCommand("filters","Active filters 🔍"),
            BotCommand("rules","Group rules 📋"),
            BotCommand("admins","Admin list 👮"),
            BotCommand("help","Full command list ❄️"),
            BotCommand("id","User/Chat ID 🆔"),
            BotCommand("ban","Ban [Admin] 🔨"),
            BotCommand("tban","Temp ban [Admin] ⏳"),
            BotCommand("mute","Mute [Admin] 🔇"),
            BotCommand("tmute","Temp mute [Admin] ⏳"),
            BotCommand("warn","Warn [Admin] ⚠️"),
            BotCommand("purge","Purge messages [Admin] 🗑️"),
            BotCommand("setwelcome","Custom welcome [Admin] 👋"),
            BotCommand("setrules","Set rules [Admin] 📋"),
            BotCommand("broadcast","Broadcast [King] 📢"),
            BotCommand("forget","Memory reset 🧠"),
            BotCommand("gm","Good morning 🌸"),
            BotCommand("gn","Good night 🌙"),
            BotCommand("compliment","Compliment do 💌"),
            BotCommand("vibe","Aaj ki vibe ✨"),
            BotCommand("sing","Yuki gaayegi 🎵"),
            BotCommand("lovemeter","Love compatibility 💕"),
            BotCommand("rpsbattle","2-player RPS ⚔️"),
        ]
        try:
            await application.bot.set_my_commands(bot_cmds)
        except Exception as e:
            print(f"Commands set error: {e}")

    app.post_init = post_init

    async def error_handler(update, context):
        print(f"❌ ERROR: {context.error}")
        import traceback; traceback.print_exc()

    app.add_error_handler(error_handler)

    print("❄️ Yuki Bot Ultra v5.0 polling shuru...")
    print(f"💾 Data will be saved to: {DB_FILE}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

main()
