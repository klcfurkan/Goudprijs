#!/usr/bin/env python3
"""Maakt dagelijkse prijskaarten (PNG) voor sociale media, per taal.

Gebruik:  python3 scripts/cards.py <uitvoermap>
Haalt live goudprijs (gold-api.com, reserve Binance PAXG), ECB-wisselkoersen (Frankfurter)
en 30 dagen koershistorie (Binance PAXG) op, bouwt per taal een HTML-kaart en maakt er met
headless Chrome een PNG van (1080x1350, Instagram-formaat). Schrijft ook cards.json met de cijfers.
"""
import json, os, subprocess, sys, urllib.request, datetime, html

OZ = 31.1034768
OUT = sys.argv[1] if len(sys.argv) > 1 else "cards"
CHROME = os.environ.get("CHROME", "google-chrome")
UA = {"User-Agent": "fairvio-cards/1.0"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def spot_usd():
    try:
        p = float(get("https://api.gold-api.com/price/XAU")["price"])
        if 500 < p < 50000: return p, "gold-api.com"
    except Exception: pass
    p = float(get("https://data-api.binance.vision/api/v3/ticker/price?symbol=PAXGUSDT")["price"])
    return p, "Binance PAXG"

def fx():
    for u in ("https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD,GBP,TRY",
              "https://api.frankfurter.app/latest?from=EUR&to=USD,GBP,TRY"):
        try:
            r = get(u)["rates"]; return {"EUR": 1.0, "USD": r["USD"], "GBP": r["GBP"], "TRY": r["TRY"]}
        except Exception: pass
    e = float(get("https://data-api.binance.vision/api/v3/ticker/price?symbol=EURUSDT")["price"])
    t = float(get("https://data-api.binance.vision/api/v3/ticker/price?symbol=USDTTRY")["price"])
    g = float(get("https://data-api.binance.vision/api/v3/ticker/price?symbol=GBPUSDT")["price"])
    return {"EUR": 1.0, "USD": e, "GBP": e / g, "TRY": e * t}

def klines(sym, iv, lim):
    k = get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval={iv}&limit={lim}")
    return [(x[0], float(x[4])) for x in k]

def fmt(v, cur, lang, dec=2):
    s = f"{v:,.{dec}f}"
    if lang in ("nl", "de", "tr"): s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    sym = {"EUR": "€", "USD": "$", "GBP": "£", "TRY": "₺"}[cur]
    if lang == "de": return f"{s} {sym}"
    if lang == "nl": return f"{sym} {s}"
    return f"{sym}{s}"

def pct(v, lang):
    s = f"{abs(v):.2f}"
    if lang in ("nl", "de", "tr"): s = s.replace(".", ",")
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    return f"{sign}%{s}" if lang == "tr" else f"{sign}{s}%"

MONTHS = {
    "nl": ["januari","februari","maart","april","mei","juni","juli","augustus","september","oktober","november","december"],
    "de": ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"],
    "en": ["January","February","March","April","May","June","July","August","September","October","November","December"],
    "tr": ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran","Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"],
}
TXT = {
    "nl": dict(title="Goudprijs vandaag", gram="per gram, 24 karaat", oz="per troy ounce", kg="per kilo", d24="24 uur", d30="30 dagen",
               extra="14 karaat per gram", foot="Informatie, geen advies"),
    "de": dict(title="Goldpreis heute", gram="pro Gramm, 24 Karat", oz="pro Feinunze", kg="pro Kilo", d24="24 Std.", d30="30 Tage",
               extra="Krügerrand 1 oz", foot="Information, keine Beratung"),
    "en": dict(title="Gold price today", gram="per gram, 24 carat", oz="per troy ounce", kg="per kilo", d24="24 hours", d30="30 days",
               extra="Price in US dollars per ounce", foot="Information, not advice"),
    "tr": dict(title="Bugün altın", gram="gram, 24 ayar", oz="ons", kg="kilogram", d24="24 saat", d30="30 gün",
               extra="Çeyrek altın", foot="Bilgidir, tavsiye değildir"),
}

def date_str(d, lang):
    m = MONTHS[lang][d.month - 1]
    return f"{d.day} {m} {d.year}" if lang != "en" else f"{d.day} {m} {d.year}"

def spark(points, w=880, h=200):
    vals = [p[1] for p in points]; lo, hi = min(vals), max(vals); span = (hi - lo) or hi * 0.01
    xs = [i * w / (len(vals) - 1) for i in range(len(vals))]
    ys = [h - 10 - (v - lo) / span * (h - 20) for v in vals]
    d = " ".join(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    area = d + f" L{w},{h} L0,{h} Z"
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e8b830" stop-opacity=".45"/><stop offset="1" stop-color="#e8b830" stop-opacity="0"/></linearGradient></defs><path d="{area}" fill="url(#g)"/><path d="{d}" fill="none" stroke="#e8b830" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/></svg>'

def card(lang, data):
    T = TXT[lang]; cur = "USD" if lang == "en" else "EUR"
    g = data["gram"][cur]; ch24, ch30 = data["ch24"], data["ch30"]
    big = fmt(g, cur, lang)
    if lang == "nl": extra = fmt(g * 0.585, "EUR", lang)
    elif lang == "de": extra = fmt(g * OZ, "EUR", lang)
    elif lang == "tr": extra = fmt(g * 1.754 * 0.916, "EUR", lang) + " · " + fmt(data["gram"]["TRY"] * 1.754 * 0.916, "TRY", lang, 0)
    else: extra = fmt(data["gram"]["USD"] * OZ, "USD", lang)
    col = lambda v: "#31d17f" if v >= 0 else "#ff6b85"
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@500;600;700;800&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0}} html,body{{width:1080px;height:1350px}}
body{{background:#0e0f12;color:#f3f4f6;font-family:Inter,system-ui,sans-serif;padding:80px 100px;display:flex;flex-direction:column;
background-image:radial-gradient(rgba(255,255,255,.05) 2px,transparent 2.4px);background-size:40px 40px}}
.top{{display:flex;justify-content:space-between;align-items:center}}
.brand{{display:flex;align-items:center;gap:20px;font-weight:800;font-size:48px;letter-spacing:-.01em}}
.date{{font-size:30px;color:#9ca3af;font-weight:500}}
h1{{font-size:76px;font-weight:800;margin-top:90px;letter-spacing:-.02em}}
.big{{font-family:"JetBrains Mono",monospace;font-size:150px;font-weight:600;color:#e8b830;margin-top:30px;letter-spacing:-.03em;white-space:nowrap}}
.sub{{font-size:34px;color:#9ca3af;margin-top:6px}}
.chg{{display:flex;gap:28px;margin-top:50px}}
.pill{{border:2px solid #2a2d34;border-radius:999px;padding:16px 30px;font-size:34px;font-weight:600;background:#16181d}}
.pill span{{color:#9ca3af;font-weight:500;margin-right:12px}}
.chart{{margin-top:60px}}
.row{{display:flex;justify-content:space-between;margin-top:46px;font-size:34px;color:#d1d5db}}
.row b{{font-family:"JetBrains Mono",monospace;color:#f3f4f6;font-weight:600}}
.foot{{margin-top:auto;display:flex;justify-content:space-between;font-size:28px;color:#6b7280}}
</style></head><body>
<div class="top"><div class="brand"><svg width="78" height="78" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#16181d" stroke="#2a2d34"/><path d="M10 40 L20 22 H50 L56 40 Z" fill="none" stroke="#fff" stroke-width="2.6" stroke-linejoin="round"/><path d="M10 40 V46 H56 V40" fill="none" stroke="#fff" stroke-width="2.6" stroke-linejoin="round"/><path d="M17 36 L26 32 L32 34.5 L40 27 L47 29" fill="none" stroke="#e8b830" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="47" cy="29" r="3.2" fill="#e8b830"/></svg>Fairvio</div>
<div class="date">{html.escape(date_str(data["date"], lang))}</div></div>
<h1>{html.escape(T["title"])}</h1>
<div class="big">{html.escape(big)}</div>
<div class="sub">{html.escape(T["gram"])}</div>
<div class="chg"><div class="pill" style="color:{col(ch24)}"><span>{T["d24"]}</span>{pct(ch24, lang)}</div><div class="pill" style="color:{col(ch30)}"><span>{T["d30"]}</span>{pct(ch30, lang)}</div></div>
<div class="chart">{spark(data["hist"])}</div>
<div class="row"><span>{html.escape(T["extra"])}</span><b>{html.escape(extra)}</b></div>
<div class="row"><span>{html.escape(T["oz"])}</span><b>{html.escape(fmt(g * OZ, cur, lang))}</b></div>
<div class="foot"><span>fairvio.com</span><span>{html.escape(T["foot"])}</span></div>
</body></html>"""

def main():
    os.makedirs(OUT, exist_ok=True)
    usd, src = spot_usd(); rates = fx()
    per_usd = {c: rates[c] / rates["USD"] for c in rates}
    gram = {c: usd / OZ * per_usd[c] for c in rates}
    day = klines("PAXGUSDT", "15m", 96); month = klines("PAXGUSDT", "4h", 180)
    ch24 = (usd / day[0][1] - 1) * 100; ch30 = (usd / month[0][1] - 1) * 100
    hist = month + [(month[-1][0], usd)]
    now = datetime.datetime.now(datetime.timezone.utc)
    data = {"date": now, "gram": gram, "ch24": ch24, "ch30": ch30, "hist": hist}
    for lang in ("nl", "de", "tr", "en"):
        hp = os.path.abspath(os.path.join(OUT, f"card-{lang}.html"))
        open(hp, "w", encoding="utf-8").write(card(lang, data))
        png = os.path.abspath(os.path.join(OUT, f"card-{lang}.png"))
        subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        "--virtual-time-budget=4000", f"--screenshot={png}", "--window-size=1080,1350", "file://" + hp],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    json.dump({"updated": now.isoformat(), "source": src, "usd_oz": usd, "rates": rates,
               "gram": gram, "ch24": ch24, "ch30": ch30}, open(os.path.join(OUT, "cards.json"), "w"), indent=1)
    print("ok", {k: round(v, 2) for k, v in gram.items()}, round(ch24, 2), round(ch30, 2))

if __name__ == "__main__":
    main()
