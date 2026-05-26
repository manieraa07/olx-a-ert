import requests
from bs4 import BeautifulSoup
import json
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

ITEMS = [
    {
        "name": "Pad Xbox",
        "url": (
            "https://www.olx.pl/elektronika/gry-konsole/akcesoria-gamingowe/q-pad-xbox/"
            "?search[filter_float_price:to]=60"
            "&search[filter_float_price:from]=40"
            "&search[filter_enum_state][0]=used"
            "&search[order]=created_at:desc"
        ),
        "min_price": 40,
        "max_price": 60,
    },
    {
        "name": "DualSense PS5",
        "url": (
            "https://www.olx.pl/elektronika/gry-konsole/akcesoria-gamingowe/q-dualsense/"
            "?search[filter_float_price:to]=100"
            "&search[filter_float_price:from]=60"
            "&search[filter_enum_state][0]=used"
            "&search[order]=created_at:desc"
        ),
        "min_price": 60,
        "max_price": 100,
    },
    {
        "name": "JBL Flip 6",
        "url": (
            "https://www.olx.pl/elektronika/q-jbl-flip-6/"
            "?search[filter_float_price:to]=160"
            "&search[filter_float_price:from]=80"
            "&search[filter_enum_state][0]=used"
            "&search[order]=created_at:desc"
        ),
        "min_price": 80,
        "max_price": 160,
    },
]

SEEN_FILE = "seen_offers.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SERWIS_KEYWORDS = ["serwis", "naprawa", "części", "repair", "sklep", "hurtownia",
                   "etui", "nakładka", "uchwyt", "stacja ładująca", "ładowarka",
                   "analog", "grip", "trigger", "obudowa", "kabel"]

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # obsługa starego formatu (lista) i nowego (słownik)
            if isinstance(data, list):
                return {}
            return data
    return {}

def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)

def znajdz_ads_w_dict(data, depth=0):
    if depth > 12:
        return None
    if isinstance(data, dict):
        if "ads" in data and isinstance(data["ads"], list) and data["ads"]:
            pierwszy = data["ads"][0]
            if isinstance(pierwszy, dict) and "id" in pierwszy:
                return data["ads"]
        for val in data.values():
            wynik = znajdz_ads_w_dict(val, depth + 1)
            if wynik:
                return wynik
    elif isinstance(data, list):
        for item in data:
            wynik = znajdz_ads_w_dict(item, depth + 1)
            if wynik:
                return wynik
    return None

def wyciagnij_js_string(text, start_idx):
    assert text[start_idx] == '"'
    i = start_idx + 1
    n = len(text)
    out = []
    while i < n:
        ch = text[i]
        if ch == "\\":
            if i + 1 < n:
                out.append(text[i:i + 2])
                i += 2
                continue
            else:
                break
        if ch == '"':
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise ValueError("Nie znaleziono zamykającego cudzysłowu")

def formatuj_date(iso_str):
    """2026-04-26T12:12:46+02:00 -> 26.04.2026 12:12"""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except:
        return iso_str[:16].replace("T", " ")

def pobierz_oferty(url, min_price, max_price):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Błąd pobierania strony: {e}")
        return []

    print(f"  Pobrano stronę: {len(resp.text)} znaków")

    soup = BeautifulSoup(resp.text, "html.parser")
    script_tag = soup.find("script", {"id": "olx-init-config"})
    if not script_tag or not script_tag.string:
        print("  Brak tagu olx-init-config")
        return []

    raw = script_tag.string
    ads = None

    for nazwa in ["__PRERENDERED_STATE__", "__INIT_CONFIG__"]:
        m = re.search(r'window\.' + re.escape(nazwa) + r'\s*=\s*"', raw)
        if not m:
            continue
        try:
            escapowany, _ = wyciagnij_js_string(raw, m.end() - 1)
        except ValueError as e:
            print(f"  {nazwa}: błąd wycinania: {e}")
            continue
        try:
            json_str = escapowany.encode("utf-8").decode("unicode_escape")
            json_str = json_str.encode("latin-1", "ignore").decode("utf-8", "ignore")
        except Exception as e:
            print(f"  {nazwa}: błąd dekodowania: {e}")
            continue
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"  {nazwa}: JSONDecodeError: {e}")
            continue
        ads = znajdz_ads_w_dict(data)
        if ads:
            print(f"  Znaleziono ogłoszenia w {nazwa}: {len(ads)} szt.")
            break

    if not ads:
        print("  Nie udało się wyciągnąć listy ofert.")
        return []

    oferty = []
    for ad in ads:
        try:
            if not isinstance(ad, dict):
                continue
            if ad.get("isBusiness", False):
                continue

            tytul = ad.get("title", "")
            tytul_lower = tytul.lower()

            if any(kw in tytul_lower for kw in SERWIS_KEYWORDS):
                continue

            # Wysyłka
            delivery = ad.get("delivery", {})
            rock = delivery.get("rock", {}) if isinstance(delivery, dict) else {}
            if not rock.get("active", False):
                continue

            # Cena
            try:
                cena = float(ad["price"]["regularPrice"]["value"])
            except (KeyError, TypeError, ValueError):
                try:
                    display = ad["price"]["displayValue"]
                    cena = float(re.sub(r"[^\d,.]", "", display).replace(",", "."))
                except:
                    continue

            if cena < min_price or cena > max_price:
                continue

            photos = ad.get("photos", [])
            photo = photos[0] if photos else ""

            oferty.append({
                "id": str(ad.get("id", "")),
                "tytul": tytul,
                "cena": cena,
                "url": ad.get("url", ""),
                "photo": photo,
                "miasto": ad.get("location", {}).get("cityName", ""),
                "dodano": formatuj_date(ad.get("createdTime", "")),
            })

        except Exception as e:
            print(f"  Pomijam ofertę z błędem: {e}")
            continue

    return oferty

def wyslij_maila(found_items):
    sender = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["ALERT_EMAIL"]

    rows = ""
    for item_name, o in found_items:
        photo_td = (
            f'<td style="padding:12px;vertical-align:top;">'
            f'<img src="{o["photo"]}" width="150" style="border-radius:8px;"></td>'
            if o["photo"] else "<td></td>"
        )
        rows += f"""
        <tr>
          <td style="padding:14px;border-bottom:1px solid #eee;vertical-align:top;">
            <div style="font-size:11px;color:#888;margin-bottom:4px;">
              {item_name} &nbsp;·&nbsp; 📍 {o['miasto']} &nbsp;·&nbsp; 🕐 dodano {o['dodano']}
            </div>
            <a href="{o['url']}" style="font-size:15px;color:#1a73e8;text-decoration:none;">{o['tytul']}</a><br>
            <span style="font-size:24px;font-weight:bold;color:#e53935;">{int(o['cena'])} zł</span>
          </td>
          {photo_td}
        </tr>"""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:620px;margin:auto;color:#333;">
      <h2 style="margin-bottom:4px;">🎮 Nowe okazje na OLX</h2>
      <p style="color:#888;margin-top:0;">{datetime.now().strftime('%d.%m.%Y %H:%M')} — {len(found_items)} ofert poniżej progu</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #eee;">
        {rows}
      </table>
      <p style="color:#bbb;font-size:11px;margin-top:16px;">
        Progi: Pad Xbox 40–60 zł &nbsp;|&nbsp; DualSense 60–100 zł &nbsp;|&nbsp; JBL Flip 6 80–160 zł
      </p>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🎮 OLX Alert — {len(found_items)} nowych okazji!"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"[OK] Wysłano email z {len(found_items)} okazjami.")

def main():
    print(f"Start: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    seen = load_seen()
    found_items = []

    for item in ITEMS:
        print(f"[SZUKAM] {item['name']} ({item['min_price']}–{item['max_price']} zł)...")
        oferty = pobierz_oferty(item["url"], item["min_price"], item["max_price"])
        print(f"  Po filtrowaniu: {len(oferty)} ofert.")

        for o in oferty:
            if not o["id"]:
                continue
            if o["id"] in seen:
                continue
            print(f"  ✅ OKAZJA: {o['tytul']} — {int(o['cena'])} zł — {o['url']}")
            found_items.append((item["name"], o))
            seen[o["id"]] = {"tytul": o["tytul"], "cena": o["cena"]}

    if found_items:
        wyslij_maila(found_items)
    else:
        print("[INFO] Brak nowych okazji.")

    save_seen(seen)
    print("Gotowe.")

if __name__ == "__main__":
    main()
