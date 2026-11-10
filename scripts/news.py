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
    "rates": (3, ["fed", "federal reserve", "ecb", "central bank", "interest rate", "interest rates", "rate cut",
                  "rate hike", "powell", "lagarde", "monetary policy", "centrale bank", "rente", "renteverlaging",
                  "renteverhoging"],
              ["merkez bankası", "tcmb", "faiz", "politika faizi", "para politikası"]),
    "economy": (2, ["inflation", "recession", "gdp", "unemployment", "tariff", "tariffs", "trade war", "sanctions",
                    "oil price", "oil prices", "crisis", "default", "debt ceiling", "inflatie", "recessie",
                    "werkloosheid", "handelsoorlog", "sancties", "olieprijs", "importheffing", "importheffingen"],
                ["enflasyon", "resesyon", "işsizlik", "gümrük vergi", "yaptırım", "petrol", "kriz", "büyüme",
                 "ticaret savaş"]),
    "currency": (3, ["dollar", "euro", "currency", "currencies", "exchange rate", "wisselkoers", "yuan"],
                 ["dolar", "döviz", "türk lirası", "dolar/tl", "kur "]),
}
# oorlog en spanning: sterke woorden tellen altijd, zwakke ("aanval") alleen samen met een land of conflict
WAR_STRONG = (["war", "wars", "airstrike", "airstrikes", "missile", "missiles", "invasion", "nuclear", "ceasefire",
               "oorlog", "raket", "raketten", "kernwapen", "kernwapens", "bombardement", "invasie", "luchtaanval"],
              ["savaş", "füze", "ateşkes", "nükleer", "işgal", "bombard", "çatışma", "hava saldırı"])
WAR_WEAK = (["attack", "attacks", "military", "troops", "strike", "strikes", "blockade", "aanval", "aanvallen", "leger", "blokkade"],
            ["saldırı", "askeri", "asker", "abluka"])
GEO = (["iran", "israel", "israël", "gaza", "ukraine", "russia", "rusland", "oekraïne", "china", "taiwan", "nato",
        "hamas", "hezbollah", "houthi", "houthis", "north korea", "noord-korea", "venezuela", "hormuz", "us", "vs"],
       ["iran", "israil", "gazze", "ukrayna", "rusya", "çin", "tayvan", "nato", "hamas", "hizbullah", "husi",
        "kuzey kore", "abd", "venezuela", "hürmüz"])
PRIORITY = ["gold", "conflict", "rates", "economy", "currency"]

def _pats(words, stems):
    return ([re.compile(r"(?<![\w])" + re.escape(x) + r"(?![\w])") for x in words] +
            [re.compile(r"(?<![\w])" + re.escape(x)) for x in stems])
PATS = {c: (w, _pats(words, stems)) for c, (w, words, stems) in CATS.items()}
P_STRONG, P_WEAK, P_GEO = _pats(*WAR_STRONG), _pats(*WAR_WEAK), _pats(*GEO)

# zinnen die op goud of valuta lijken maar het niet zijn
NOISE = [
    re.compile(r"(\d[\d.,%]*|doların|dolar|liranın|seviyenin|seviyesinin|sınırın|beklentilerin|eşiğin)\s+altın(a|da|ı)?(?![\w])"),
    re.compile(r"(\d[\d.,]*|milyar|milyon|bin|trilyon)\s+dolar\w*"),
    re.compile(r"\$?\d[\d.,]*\s*(billion|million|trillion|bn|m|miljard|miljoen)?\s+dollars?"),
]

def norm(s):
    return s.replace("İ", "i").lower()

def clean(t):
    for p in NOISE:
        t = p.sub(" ", t)
    return t

def classify(title, official):
    t = clean(norm(title))
    hit = lambda pats: any(p.search(t) for p in pats)
    hits = {c: w for c, (w, pats) in PATS.items() if hit(pats)}
    geo = hit(P_GEO)
    if hit(P_STRONG) or (geo and hit(P_WEAK)):
        hits["conflict"] = 3
    if not hits:
        return None, 0
    score = sum(hits.values()) + (1 if geo else 0) + (2 if official else 0)
    return next(c for c in PRIORITY if c in hits), score

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
