import json
import logging
import os
import random
from pathlib import Path

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
HERE = Path(__file__).parent
Q = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
DB_FILE = HERE / "progress.json"
LET = "АБВГ"
DB = json.loads(DB_FILE.read_text(encoding="utf-8")) if DB_FILE.exists() else {}


def user(uid):
    u = DB.setdefault(str(uid), {})
    for k, v in (("done", []), ("wrong", []), ("queue", []), ("pos", 0),
                 ("ok", 0), ("bad", []), ("answered", False)):
        u.setdefault(k, v)
    return u


def save():
    DB_FILE.write_text(json.dumps(DB), encoding="utf-8")


def menu_kb(u):
    return Markup([
        [Btn("▶️ По порядку", callback_data="m:all"), Btn("🔀 Вперемешку", callback_data="m:shuf")],
        [Btn("🆕 Непройденные", callback_data="m:new"),
         Btn(f"❗ Ошибки ({len(u['wrong'])})", callback_data="m:wrong")],
    ])


def menu_text(u):
    return (f"Тест по финансам и финансовым кризисам\n"
            f"Вопросов: {len(Q)}\nПройдено: {len(set(u['done']))}\nОшибок в списке: {len(u['wrong'])}\n\n"
            f"Выберите режим. Диапазон: /range 1 30")


def render(qid, pos, total, mark=None):
    q = Q[qid]
    lines = [f"Вопрос {qid + 1}  ({pos + 1} из {total})", "", q["q"], ""]
    for k, t in enumerate(q["o"]):
        pre = f"{LET[k]})"
        if mark is not None:
            if k == q["a"]:
                pre = f"✅ {LET[k]})"
            elif k == mark:
                pre = f"❌ {LET[k]})"
        lines.append(f"{pre} {t}\n")
    return "\n".join(lines)


def q_kb(qid):
    return Markup([[Btn(LET[k], callback_data=f"a:{qid}:{k}") for k in range(4)],
                   [Btn("⏹ Завершить", callback_data="stop")]])


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    await update.message.reply_text(menu_text(u), reply_markup=menu_kb(u))


async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    await update.message.reply_text(menu_text(u), reply_markup=menu_kb(u))


async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    DB.pop(str(update.effective_user.id), None)
    save()
    await update.message.reply_text("Прогресс сброшен. /start")


def begin(u, ids):
    u.update(queue=ids, pos=0, ok=0, bad=[], answered=False)
    save()


async def range_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    try:
        a, b = int(ctx.args[0]), int(ctx.args[1])
        ids = list(range(max(1, a) - 1, min(len(Q), b)))
        assert ids
    except Exception:
        await update.message.reply_text("Формат: /range 1 30")
        return
    begin(u, ids)
    await update.message.reply_text(render(ids[0], 0, len(ids)), reply_markup=q_kb(ids[0]))


async def finish(query, u):
    t = u["ok"] + len(u["bad"])
    pct = round(u["ok"] / t * 100) if t else 0
    txt = f"Результат: {pct}%\nВерно {u['ok']} из {t}"
    if u["bad"]:
        txt += "\n\nОшибки, вопросы №: " + ", ".join(str(i + 1) for i in u["bad"])
    u["queue"] = []
    save()
    await query.edit_message_text(txt, reply_markup=menu_kb(u))


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = user(query.from_user.id)
    d = query.data

    if d.startswith("m:"):
        mode = d[2:]
        ids = list(range(len(Q)))
        if mode == "shuf":
            random.shuffle(ids)
        elif mode == "new":
            ids = [i for i in ids if i not in set(u["done"])]
        elif mode == "wrong":
            ids = list(u["wrong"])
            random.shuffle(ids)
        if not ids:
            await query.answer("В этом режиме нет вопросов", show_alert=True)
            return
        begin(u, ids)
        await query.edit_message_text(render(ids[0], 0, len(ids)), reply_markup=q_kb(ids[0]))

    elif d.startswith("a:"):
        _, qid, k = d.split(":")
        qid, k = int(qid), int(k)
        if not u["queue"] or u["queue"][u["pos"]] != qid or u["answered"]:
            return
        u["answered"] = True
        if qid not in u["done"]:
            u["done"].append(qid)
        if k == Q[qid]["a"]:
            u["ok"] += 1
            if qid in u["wrong"]:
                u["wrong"].remove(qid)
        else:
            u["bad"].append(qid)
            if qid not in u["wrong"]:
                u["wrong"].append(qid)
        save()
        last = u["pos"] == len(u["queue"]) - 1
        kb = Markup([[Btn("Результаты" if last else "Дальше ▶️", callback_data="next")]])
        await query.edit_message_text(render(qid, u["pos"], len(u["queue"]), mark=k), reply_markup=kb)

    elif d == "next":
        if not u["queue"]:
            return
        u["pos"] += 1
        u["answered"] = False
        if u["pos"] >= len(u["queue"]):
            await finish(query, u)
            return
        save()
        qid = u["queue"][u["pos"]]
        await query.edit_message_text(render(qid, u["pos"], len(u["queue"])), reply_markup=q_kb(qid))

    elif d == "stop":
        if u["queue"]:
            await finish(query, u)


def main():
    token = os.environ.get("BOT_TOKEN")
    tf = HERE / "token.txt"
    if not token and tf.exists():
        token = tf.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("Нет токена: создайте файл token.txt рядом с bot.py и вставьте туда токен от BotFather")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("range", range_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.run_polling()


if __name__ == "__main__":
    main()
