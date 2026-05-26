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
            "&search[filter_enum_state][0]=used"
            "&search[order]=created_at:desc"
        ),
        "max_price": 60,
    },
    {
        "name": "DualSense PS5",
        "url": (
            "https://www.olx.pl/elektronika/gry-konsole/akcesoria-gamingowe/q-dualsense/"
            "?search[filter_float_price:to]=100"
            "&search[filter_enum_state][0]=used"
            "&search[order]=created_at:desc"
        ),
        "max_price": 100,
    },
    {
        "name": "JBL Flip 6",
        "url": (
            "https://www.olx.pl/elektronika/q-jbl-flip-6/"
            "?search[filter_float_price:to]=160"
            "&search[filter_enum_state][0]=used"
            "&search[order]=created_at:desc"
        ),
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

SERWIS_KEYWORDS = ["serwis", "naprawa", "części", "repair", "sklep", "hurtownia"]

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
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

def pobierz_oferty(url, max_price, debug=False):
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
            # DEBUG — wypisz typ i fragment pierwszego elementu
            print(f"  DEBUG typ ads[0]: {type(ads[0])}")
            print(f"  DEBUG ads[0]: {json.dumps(ads[0], ensure_ascii=False)[:600]}")
            break

    if not ads:
        print("  Nie udało się wyciągnąć listy ofert.")
        return []

    return []  # tymczasowo zwracamy pusta liste zeby zobaczyc tylko debug

def main():
    print(f"Start: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    # Sprawdzamy tylko pierwszy przedmiot dla debugowania
    item = ITEMS[0]
    print(f"[DEBUG] {item['name']}...")
    pobierz_oferty(item["url"], item["max_price"], debug=True)
    print("Gotowe.")

if __name__ == "__main__":
    main()
