"""Haalt belangrijk nieuws op dat de goudprijs kan raken en schrijft news.json.

Draait elke 30 minuten via GitHub Actions. Alleen de standaardbibliotheek.
"""
import json, re, sys, time, urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

SOURCES = [
    # (naam, url, taal, groep, officieel)
    ("NOS", "https://feeds.nos.nl/nosnieuwsbuitenland", "nl", "intl", False),
    ("NOS", "https://feeds.nos.nl/nosnieuwseconomie", "nl", "intl", False),
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml", "en", "intl", False),
    ("BBC", "https://feeds.bbci.co.uk/news/business/rss.xml", "en", "intl", False),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml", "en", "intl", True),
    ("ECB", "https://www.ecb.europa.eu/rss/press.html", "en", "intl", True),
    ("AA", "https://www.aa.com.tr/tr/rss/default?cat=guncel", "tr", "tr", False),
    ("AA", "https://www.aa.com.tr/tr/rss/default?cat=ekonomi", "tr", "tr", False),
    ("TRT Haber", "https://www.trthaber.com/manset_articles.rss", "tr", "tr", False),
    ("TRT Haber", "https://www.trthaber.com/ekonomi_articles.rss", "tr", "tr", False),
    ("BBC Türkçe", "https://feeds.bbci.co.uk/turkce/rss.xml", "tr", "tr", False),
    ("DW Türkçe", "https://rss.dw.com/rdf/rss-tur-all", "tr", "tr", False),
]

# categorie -> (gewicht, woorden die als heel woord tellen, Turkse stammen die mogen doorlopen)
CATS = {
    "gold": (5, ["gold", "goud", "goudprijs", "precious metals", "edelmetaal", "bullion"], ["altın", "külçe"]),
    "conflict": (3, ["war", "wars", "attack", "attacks", "airstrike", "airstrikes", "missile", "missiles", "invasion",
                     "military", "troops", "nuclear", "ceasefire", "iran", "israel", "gaza", "ukraine", "russia",
                     "hamas", "hezbollah", "houthi", "houthis", "rusland", "oekraïne", "israël", "oorlog", "aanval", "aanvallen", "raket", "raketten",
                     "leger", "bestand", "kernwapen", "bombardement", "invasie"],
                 ["savaş", "saldırı", "füze", "askeri", "ateşkes", "nükleer", "işgal", "çatışma", "bombard", "iran",
                  "israil", "gazze", "ukrayna", "rusya", "hamas"]),
    "rates": (3, ["fed", "federal reserve", "ecb", "central bank", "interest rate", "interest rates", "rate cut",
                  "rate hike", "powell", "lagarde", "monetary policy", "centrale bank", "rente", "renteverlaging",
                  "renteverhoging"],
              ["merkez bankası", "tcmb", "faiz", "politika faizi", "para politikası"]),
    "economy": (2, ["inflation", "recession", "gdp", "unemployment", "tariff", "tariffs", "trade war", "sanctions",
                    "oil price", "oil prices", "crisis", "default", "debt ceiling", "inflatie", "recessie",
                    "werkloosheid", "handelsoorlog", "sancties", "olieprijs", "importheffing", "importheffingen"],
                ["enflasyon", "resesyon", "işsizlik", "gümrük vergi", "yaptırım", "petrol", "kriz", "büyüme",
                 "ticaret savaş"]),
    "currency": (3, ["dollar", "currency", "currencies", "exchange rate", "wisselkoers", "yuan"],
                 ["dolar", "döviz", "kur ", "türk lirası", "euro"]),
}
PRIORITY = ["gold", "conflict", "rates", "economy", "currency"]

def compile_patterns():
    out = {}
    for cat, (w, words, stems) in CATS.items():
        pats = [re.compile(r"(?<![\w])" + re.escape(x) + r"(?![\w])") for x in words]
        pats += [re.compile(r"(?<![\w])" + re.escape(x)) for x in stems]
        out[cat] = (w, pats)
    return out
PATS = compile_patterns()

def norm(s):
    return s.replace("İ", "i").lower()

def classify(title, official):
    t = norm(title)
    hits = [c for c, (w, pats) in PATS.items() if any(p.search(t) for p in pats)]
    if not hits:
        return None, 0
    score = sum(CATS[c][0] for c in hits) + (2 if official else 0)
    cat = next(c for c in PRIORITY if c in hits)
    return cat, score

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GoudPrijsAnalytics/1.0)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()

def local(tag):
    return tag.rsplit("}", 1)[-1]

def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        title = link = date = None
        for c in el:
            n = local(c.tag)
            if n == "title":
                title = (c.text or "").strip()
            elif n == "link":
                link = (c.text or "").strip() or c.get("href")
            elif n in ("pubDate", "date", "updated", "published") and not date:
                date = c.text
        if title and link:
            items.append((title, link, parse_date(date)))
    return items

def main(out_path="news.json"):
    now = time.time()
    seen, items, errors = set(), [], []
    for name, url, lang, group, official in SOURCES:
        try:
            for title, link, ts in parse(fetch(url)):
                if not ts or now - ts > 72 * 3600 or ts - now > 3600:
                    continue
                cat, score = classify(title, official)
                if not cat or score < 3:
                    continue
                key = re.sub(r"\W+", "", norm(title))[:70]
                if key in seen:
                    continue
                seen.add(key)
                items.append({"t": title, "u": link, "s": name, "lang": lang, "g": group,
                              "ts": int(ts), "cat": cat, "score": score})
        except Exception as e:  # een kapotte bron mag de rest niet tegenhouden
            errors.append(f"{name} {url}: {e.__class__.__name__}")
    out = {"updated": int(now), "errors": errors, "items": []}
    for group in ("intl", "tr"):
        g = [i for i in items if i["g"] == group]
        g.sort(key=lambda i: (i["score"] >= 6, i["ts"]), reverse=True)
        out["items"] += sorted(g[:25], key=lambda i: i["ts"], reverse=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{len(out['items'])} items, {len(errors)} fouten")
    for e in errors:
        print("  ", e)

if __name__ == "__main__":
    main(*sys.argv[1:])
