import requests
import json
import smtplib
import os
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ── Konfiguracja przedmiotów ──────────────────────────────────────────────────
ITEMS = [
    {
        "name": "Pad Xbox",
        "query": "pad xbox",
        "max_price": 60,
        "category_id": "1144",  # Akcesoria gamingowe
    },
    {
        "name": "DualSense PS5",
        "query": "dualsense",
        "max_price": 100,
        "category_id": "1144",
    },
    {
        "name": "JBL Flip 6",
        "query": "jbl flip 6",
        "max_price": 160,
        "category_id": "1636",  # Audio / głośniki
    },
]

# ── Plik z już wysłanymi alertami (żeby nie spamować) ─────────────────────────
SEEN_FILE = "seen_offers.json"


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


# ── OLX API ───────────────────────────────────────────────────────────────────
def search_olx(query, max_price, category_id):
    """
    Przeszukuje OLX przez oficjalne API.
    Filtry: cena <= max_price, tylko z wysyłką, tylko prywatne, stan=używany
    """
    url = "https://www.olx.pl/api/v1/offers/"
    params = {
        "query": query,
        "category_id": category_id,
        "filter_refiners": "spell_checker",
        "suggest_filters": "true",
        "offset": 0,
        "limit": 40,
        "sort_by": "created_at:desc",
        # Tylko używane
        "filter_enum_state[0]": "used",
        # Tylko z wysyłką
        "filter_enum_shipping[0]": "yes",
        # Cena max
        "filter_float_price:to": max_price,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except Exception as e:
        print(f"[BŁĄD] Zapytanie OLX dla '{query}': {e}")
        return []


def filter_offers(offers, item_name):
    """
    Dodatkowe filtrowanie po stronie klienta:
    - pomijamy firmy (tylko prywatne)
    - pomijamy jeśli tytuł/opis wygląda jak serwis/sklep
    """
    SERWIS_KEYWORDS = ["serwis", "naprawa", "remont", "części", "part", "repair",
                       "sklep", "hurtownia", "nowy", "nowe", "fabrycznie"]
    result = []
    for offer in offers:
        # Tylko osoby prywatne
        user_type = offer.get("user", {}).get("account_type", "")
        if user_type == "business":
            continue

        title = offer.get("title", "").lower()
        description = offer.get("description", "").lower()

        # Pomijamy serwisy
        skip = False
        for kw in SERWIS_KEYWORDS:
            if kw in title:
                skip = True
                break
        if skip:
            continue

        result.append(offer)

    return result


def parse_offer(offer):
    """Wyciąga najważniejsze dane z oferty OLX."""
    price_data = offer.get("params", [])
    price = None
    for param in price_data:
        if param.get("key") == "price":
            price = param.get("value", {}).get("converted_value") or \
                    param.get("value", {}).get("value")
            break

    photos = offer.get("photos", [])
    photo_url = photos[0].get("link", "").replace("{width}", "400").replace("{height}", "300") \
        if photos else ""

    location = offer.get("location", {})
    city = location.get("city", {}).get("name", "?")

    return {
        "id": offer.get("id"),
        "title": offer.get("title", ""),
        "price": price,
        "url": offer.get("url", ""),
        "photo": photo_url,
        "city": city,
        "created": offer.get("created_time", ""),
    }


# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(found_items):
    sender = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["ALERT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🎮 OLX Alert — {len(found_items)} nowych okazji!"
    msg["From"] = sender
    msg["To"] = recipient

    # Budujemy HTML maila
    rows = ""
    for item_name, offer in found_items:
        rows += f"""
        <tr>
          <td style="padding:12px; border-bottom:1px solid #eee;">
            <strong>{item_name}</strong><br>
            <a href="{offer['url']}" style="font-size:16px; color:#1a73e8;">{offer['title']}</a><br>
            <span style="font-size:22px; font-weight:bold; color:#e53935;">{offer['price']} zł</span><br>
            <small style="color:#888;">📍 {offer['city']} &nbsp;|&nbsp; 🕐 {offer['created'][:16].replace('T',' ')}</small>
          </td>
          {"<td style='padding:12px;'><img src='" + offer['photo'] + "' width='160' style='border-radius:8px;'></td>" if offer['photo'] else "<td></td>"}
        </tr>
        """

    html = f"""
    <html><body style="font-family:Arial,sans-serif; max-width:600px; margin:auto;">
      <h2 style="color:#333;">🎮 Nowe okazje na OLX</h2>
      <p style="color:#666;">Znaleziono {len(found_items)} ofert poniżej progu cenowego — {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
      <table width="100%" cellpadding="0" cellspacing="0">
        {rows}
      </table>
      <p style="color:#aaa; font-size:12px; margin-top:20px;">
        Progi: Pad Xbox ≤60 zł | DualSense ≤100 zł | JBL Flip 6 ≤160 zł
      </p>
    </body></html>
    """

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    print(f"[OK] Wysłano email z {len(found_items)} okazjami.")


# ── Główna logika ─────────────────────────────────────────────────────────────
def main():
    seen = load_seen()
    found_items = []

    for item in ITEMS:
        print(f"[SZUKAM] {item['name']} (max {item['max_price']} zł)...")
        offers = search_olx(item["query"], item["max_price"], item["category_id"])
        offers = filter_offers(offers, item["name"])

        for raw_offer in offers:
            parsed = parse_offer(raw_offer)

            if parsed["id"] is None or parsed["price"] is None:
                continue

            # Unikalny klucz żeby nie wysyłać tego samego 2x
            offer_key = str(parsed["id"])
            if offer_key in seen:
                continue

            print(f"  ✅ OKAZJA: {parsed['title']} — {parsed['price']} zł — {parsed['url']}")
            found_items.append((item["name"], parsed))
            seen.add(offer_key)

    if found_items:
        send_email(found_items)
    else:
        print("[INFO] Brak nowych okazji.")

    save_seen(seen)


if __name__ == "__main__":
    main()
