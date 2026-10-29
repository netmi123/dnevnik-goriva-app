"""Weekly fuel-price robot for Dnevnik goriva.

Runs on GitHub Actions (see .github/workflows/cene.yml). It:
  1. finds this week's regulated prices (evrodizel, BMB 95) in the Friday news post on nafta.hr,
  2. reads the premium prices per pump from the nafta.hr price table,
  3. checks that every number looks sane before using it,
  4. writes cene.json in the same shape as the price block built into the app,
  5. reports to Telegram what changed, or what went wrong.

Nothing doubtful is ever written: a missing or odd price keeps last week's value and is reported instead.

Environment:
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID  where reports go (without them the report is only printed)
  RUN_KIND   glavni | ponovo | poslednji | rucno | proba
             (Friday run, Saturday retry, Sunday last try, manual run, read-only test)
  CENE_FILE  path of the price file (default: cene.json next to the repository root)
  CENE_TEST_DIR  folder with saved pages, used instead of the internet (for testing)
"""

import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

TZ = ZoneInfo("Europe/Belgrade")
TABLE_URL = "https://nafta.hr/sr/cene-goriva-srbija/"
NEWS_API = "https://nafta.hr/wp-json/wp/v2/posts"
UA = "Mozilla/5.0 (DnevnikGoriva cene robot; +https://github.com/netmi123/dnevnik-goriva-app)"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENE_FILE = os.environ.get("CENE_FILE") or os.path.join(ROOT, "cene.json")
RUN_KIND = os.environ.get("RUN_KIND", "rucno")

# Table headings on nafta.hr -> which premium fuel key of the app they feed.
TABLE_KEYS = {
    "eurodizel premium": "dizel_p",
    "bmb 95 premium benzin": "bmb_p95",
    "bmb 100 benzin": "bmb_p100",
}
# Company names in the table -> pump ids in the app.
COMPANIES = {"nis": "nis", "mol": "mol", "omv": "omv", "eko": "eko", "avia": "avia",
             "euro-petrol": "europetrol", "europetrol": "europetrol", "euro petrol": "europetrol"}
# Petrol premiums are listed differently by different sources (e.g. Euro Petrol's Expert BMB),
# so if one is missing from its own table the other petrol-premium table is tried.
PETROL_ALT = {"bmb_p95": "bmb_p100", "bmb_p100": "bmb_p95"}
BASE_FOR = {"dizel_p": "eurodizel", "bmb_p95": "bmb95", "bmb_p100": "bmb95"}

MIN_PRICE, MAX_PRICE = 120, 400       # dinars per liter that are believable at all
MAX_WEEKLY_JUMP = 0.12                # more than 12 % in one week is held back for a human look

MONTHS = ["januar", "februar", "mart", "april", "maj", "jun", "jul", "avgust", "septembar", "oktobar", "novembar", "decembar"]


# ---------------------------------------------------------------- helpers

def today():
    fake = os.environ.get("CENE_NOW")  # for testing, e.g. 2026-10-30T17:20
    return dt.datetime.fromisoformat(fake).replace(tzinfo=TZ) if fake else dt.datetime.now(TZ)


def this_friday(now):
    """The Friday whose prices are in force now (prices change on Friday at 15:00)."""
    d = now.date()
    back = (d.weekday() - 4) % 7
    fri = d - dt.timedelta(days=back)
    if back == 0 and now.hour < 15:
        fri -= dt.timedelta(days=7)
    return fri


def fmt_day(d):
    return f"{d.day}.{d.month}."


def fmt_price(p):
    if p is None:
        return "–"
    return str(int(p)) if float(p).is_integer() else f"{p:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def to_num(s):
    s = s.strip().replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    return round(float(s), 2)


def fetch(url, kind):
    test_dir = os.environ.get("CENE_TEST_DIR")
    if test_dir:
        path = os.path.join(test_dir, kind)
        with open(path, encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "sr,hr;q=0.8,en;q=0.5"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def believable(p):
    return p is not None and MIN_PRICE <= p <= MAX_PRICE


def jump_ok(new, old):
    return not old or abs(new - old) / old <= MAX_WEEKLY_JUMP


# ---------------------------------------------------------------- regulated prices (Friday news post)

NUM = r"(\d{3}(?:[.,]\d{1,2})?)"
RE_DIESEL = re.compile(r"(?:evro|euro)\s*-?\s*dizel(?!\s*premi)[^\d]{0,60}?" + NUM + r"\s*(?:RSD|din)", re.I)
RE_PETROL = re.compile(r"BMB\s*-?\s*95(?!\s*premi)[^\d]{0,60}?" + NUM + r"\s*(?:RSD|din)", re.I)
SKIP_TITLES = re.compile(r"najav|prognoz|očekuj|ocekuj|mogl|regij|region", re.I)


def post_text(p):
    raw = (p.get("title", {}).get("rendered", "") + "\n" + p.get("content", {}).get("rendered", ""))
    txt = BeautifulSoup(raw, "html.parser").get_text("\n")
    return html.unescape(txt)


def regulated_from_news(friday):
    """Returns ({eurodizel, bmb95, izvor}, problem). Looks only at posts from this Friday on."""
    after = dt.datetime.combine(friday, dt.time(0, 0)).isoformat()
    posts = []
    for extra in ({}, {"lang": "sr"}):
        q = {"search": "Srbiji", "per_page": "20", "after": after,
             "_fields": "date,link,title,content", "orderby": "date", "order": "desc", **extra}
        try:
            data = json.loads(fetch(NEWS_API + "?" + urllib.parse.urlencode(q), "news.json"))
        except Exception as e:  # noqa: BLE001 - any network/format error is reported, not fatal
            return None, f"vesti sa nafta.hr nisu dostupne ({type(e).__name__})"
        if isinstance(data, list):
            posts.extend(data)
        if posts:
            break

    found = []
    for p in posts:
        title = html.unescape(BeautifulSoup(p.get("title", {}).get("rendered", ""), "html.parser").get_text())
        if SKIP_TITLES.search(title) or not re.search(r"srbij", title, re.I):
            continue
        day = dt.date.fromisoformat(str(p.get("date", ""))[:10])
        if not (friday <= day <= friday + dt.timedelta(days=2)):
            continue
        txt = post_text(p)
        d, b = RE_DIESEL.search(txt), RE_PETROL.search(txt)
        if not (d and b):
            continue
        found.append({"eurodizel": to_num(d.group(1)), "bmb95": to_num(b.group(1)), "izvor": p.get("link", "")})

    if not found:
        return None, None
    first = found[0]
    for other in found[1:]:
        if (other["eurodizel"], other["bmb95"]) != (first["eurodizel"], first["bmb95"]):
            return None, (f"dve vesti daju različite cene ({fmt_price(first['eurodizel'])}/{fmt_price(first['bmb95'])} "
                          f"i {fmt_price(other['eurodizel'])}/{fmt_price(other['bmb95'])})")
    return first, None


# ---------------------------------------------------------------- premium prices (price table)

def premium_from_table():
    """Returns (period_start_date, {key: {pump: price}}, problem)."""
    try:
        page = fetch(TABLE_URL, "tabela.html")
    except Exception as e:  # noqa: BLE001
        return None, None, f"tabela cena na nafta.hr nije dostupna ({type(e).__name__})"
    soup = BeautifulSoup(page, "html.parser")
    text = soup.get_text(" ")

    start = None
    m = re.search(r"je\s+(\d{1,2})\.(\d{1,2})\.(\d{4})\.?\s+održal", text)
    if m:
        start = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    else:
        m = re.search(r"važiti\s+do\s+(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
        if m:
            start = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) - dt.timedelta(days=7)
    if not start:
        return None, None, "u tabeli nisam našao za koju nedelju su cene"

    tables = {}
    for h in soup.find_all(["h2", "h3"]):
        name = re.sub(r"\s+", " ", h.get_text(" ")).strip().lower()
        key = TABLE_KEYS.get(name)
        if not key:
            continue
        table = h.find_next("table")
        if not table:
            continue
        nxt = table.find_previous(["h2", "h3"])
        if nxt is not h:
            continue  # the table belongs to a later heading
        rows = {}
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ").strip() for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            pump = COMPANIES.get(cells[0].strip().lower())
            if not pump:
                continue
            m = re.search(r"(\d{2,3}(?:[.,]\d{1,2})?)\s*RSD", " ".join(cells[1:]))
            if m:
                rows[pump] = to_num(m.group(1))
        tables[key] = rows

    if not tables:
        return start, None, "tabela je promenila izgled, nijedno premium gorivo nije pročitano"
    return start, tables, None


# ---------------------------------------------------------------- Telegram

TELEGRAM_FAILED = []

def telegram(text):
    print("---- poruka ----\n" + text + "\n----------------")
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if os.environ.get("CENE_TEST_DIR"):
        return
    if not token or not chat:
        print("::error::Nedostaje GitHub tajna " + ("TELEGRAM_TOKEN" if not token else "TELEGRAM_CHAT_ID"))
        TELEGRAM_FAILED.append(-1)
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=30).read()
        print("Telegram poruka poslata.")
    except urllib.error.HTTPError as e:
        why = e.read().decode("utf-8", "replace")[:200]
        # a GitHub annotation, so the reason shows on the run page; the token itself never appears here
        print(f"::error::Telegram nije primio poruku: HTTP {e.code} {why}")
        TELEGRAM_FAILED.append(e.code)
    except Exception as e:  # noqa: BLE001
        print(f"::error::Telegram nije dostupan: {type(e).__name__}")
        TELEGRAM_FAILED.append(0)


# ---------------------------------------------------------------- test run

def proba(friday):
    """Reads both sources and reports what it understood, without writing anything."""
    lines = [f"🧪 Proba robota (ništa ne upisujem). Tekuća nedelja: od petka {fmt_day(friday)}"]
    reg, prob = regulated_from_news(friday)
    if reg:
        lines.append(f"Vest: evrodizel {fmt_price(reg['eurodizel'])}, BMB 95 {fmt_price(reg['bmb95'])} din.")
    else:
        lines.append("Vest za ovu nedelju: " + (prob or "nisam našao"))
    start, tables, prob = premium_from_table()
    if tables:
        n = sum(len(v) for v in tables.values())
        when = fmt_day(start) if start else "?"
        lines.append(f"Tabela: {n} premium cena, za nedelju od {when}" + (" ✅" if start == friday else " (kasni)"))
        for key, name in (("dizel_p", "Premium dizel"), ("bmb_p95", "BMB 95 premium"), ("bmb_p100", "BMB 100")):
            row = tables.get(key) or {}
            if row:
                lines.append(f"{name}: " + ", ".join(f"{p} {fmt_price(v)}" for p, v in sorted(row.items())))
    else:
        lines.append("Tabela: " + (prob or "prazna"))
    telegram("\n".join(lines))
    return 0


# ---------------------------------------------------------------- main

def main():
    now = today()
    friday = this_friday(now)
    with open(CENE_FILE, encoding="utf-8") as f:
        cene = json.load(f)

    if RUN_KIND == "proba":
        return proba(friday)

    reg_fresh = cene.get("vaziOd") == friday.isoformat()
    prem_fresh = cene.get("premiumOd") == friday.isoformat()
    last_try = RUN_KIND in ("poslednji", "rucno")

    if reg_fresh and prem_fresh:
        print("Sve je već ažurno za ovu nedelju.")
        if RUN_KIND == "rucno":
            telegram(f"✅ Cene za nedelju od petka {fmt_day(friday)} su već ažurne. Nema ništa novo.")
        return 0

    problems, notes, changed = [], [], []

    # 1. regulated prices
    if not reg_fresh:
        reg, prob = regulated_from_news(friday)
        if prob:
            problems.append(prob)
        if reg:
            bad = [k for k in ("eurodizel", "bmb95") if not believable(reg[k]) or not jump_ok(reg[k], cene.get(k))]
            if bad:
                problems.append("regulisane cene izgledaju čudno (" + ", ".join(
                    f"{'evrodizel' if k == 'eurodizel' else 'BMB 95'} {fmt_price(cene.get(k))} → {fmt_price(reg[k])}" for k in bad)
                    + "), nisam ih upisao")
            else:
                cene["prethodno"] = {"eurodizel": cene.get("eurodizel"), "bmb95": cene.get("bmb95")}
                cene["eurodizel"], cene["bmb95"] = reg["eurodizel"], reg["bmb95"]
                cene["vaziOd"] = friday.isoformat()
                cene["vaziDo"] = (friday + dt.timedelta(days=7)).isoformat()
                reg_fresh = True
                changed.append("regulisane")

    # 2. premium prices
    if not prem_fresh:
        start, tables, prob = premium_from_table()
        if prob:
            problems.append(prob)
        if tables and start == friday:
            missing, odd = [], []
            for pump_id, pump in cene.get("pumpe", {}).items():
                for key, fuel in pump.get("goriva", {}).items():
                    if key not in BASE_FOR:
                        continue
                    new = tables.get(key, {}).get(pump_id)
                    if new is None and key in PETROL_ALT:
                        new = tables.get(PETROL_ALT[key], {}).get(pump_id)
                    label = f"{pump.get('naziv', pump_id)} {fuel.get('naziv', key)}"
                    if new is None:
                        missing.append(label)
                        continue
                    base = cene.get(BASE_FOR[key])
                    if not believable(new) or not jump_ok(new, fuel.get("cena")) or (base and new < base - 1):
                        odd.append(f"{label} {fmt_price(fuel.get('cena'))} → {fmt_price(new)}")
                        continue
                    fuel["pre"] = fuel.get("cena")
                    fuel["cena"] = new
            # anything in the table that the app doesn't know yet
            known = {(p, k) for p, v in cene.get("pumpe", {}).items() for k in v.get("goriva", {})}
            new_ones = sorted({f"{p} ({k})" for k, rows in tables.items() for p in rows
                               if (p, k) not in known and (p, PETROL_ALT.get(k)) not in known})
            if missing:
                notes.append("Nisam našao u tabeli (ostala stara cena): " + ", ".join(missing))
            if odd:
                problems.append("premium cene koje izgledaju čudno, nisam ih upisao: " + "; ".join(odd))
            if new_ones:
                notes.append("U tabeli ima premium goriva koja aplikacija još nema: " + ", ".join(new_ones))
            cene["premiumOd"] = friday.isoformat()
            prem_fresh = True
            changed.append("premium")
        elif tables and start and start < friday:
            notes.append(f"Tabela premium cena još nije osvežena (ima cene od {fmt_day(start)}).")

    if changed:
        cene["provereno"] = now.date().isoformat()
        with open(CENE_FILE, "w", encoding="utf-8") as f:
            json.dump(cene, f, ensure_ascii=False, indent=1)
            f.write("\n")

    # 3. report
    if changed:
        lines = [f"⛽ Cene goriva od petka {fmt_day(friday)}"]
        if "regulisane" in changed:
            for k, name in (("eurodizel", "Evrodizel"), ("bmb95", "BMB 95")):
                old, new = cene["prethodno"].get(k), cene[k]
                diff = "bez promene" if old == new else f"bilo {fmt_price(old)}"
                lines.append(f"{name}: {fmt_price(new)} din ({diff})")
        if "premium" in changed:
            moved, same = [], 0
            for pump in cene.get("pumpe", {}).values():
                for fuel in pump.get("goriva", {}).values():
                    if fuel.get("pre") is not None and fuel.get("pre") != fuel.get("cena"):
                        moved.append(f"• {pump['naziv']} {fuel['naziv']}: {fmt_price(fuel['pre'])} → {fmt_price(fuel['cena'])}")
                    else:
                        same += 1
            lines.append("Premium promene:" if moved else "Premium: sve isto kao prošle nedelje.")
            lines += moved
            if moved and same:
                lines.append(f"Ostalih {same} bez promene.")
        if not reg_fresh:
            lines.append("⏳ Regulisane cene još nisu objavljene" + ("." if last_try else ", probam ponovo."))
        if not prem_fresh:
            lines.append("⏳ Premium cene još nisu osvežene" + (", ostaju prošlonedeljne." if last_try else ", probam ponovo."))
        lines += notes
        if problems:
            lines.append("⚠️ " + "\n⚠️ ".join(problems))
        telegram("\n".join(lines))
    elif problems or last_try:
        lines = [f"⚠️ Cene goriva za petak {fmt_day(friday)}: nisam uspeo sve da osvežim."]
        lines.append("Evrodizel i BMB 95: " + ("osveženi ✅" if reg_fresh else "NISU osveženi, ostale su stare cene"))
        lines.append("Premium po pumpama: " + ("osvežene ✅" if prem_fresh else "NISU osvežene, ostale su stare cene"))
        lines += problems + notes
        lines.append("Proveri ručno ili mi javi.")
        telegram("\n".join(lines))
    else:
        print("Ništa novo još, pokušaću u sledećem krugu.\n" + "\n".join(notes))
    return 0


if __name__ == "__main__":
    code = main()
    # prices are still saved, but a report that never arrived makes the run red, so it gets noticed
    sys.exit(code or (1 if TELEGRAM_FAILED else 0))
