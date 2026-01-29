import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup

SEARCH_URL = (
    "https://trouverunlogement.lescrous.fr/tools/42/search"
    "?occupationModes=alone&bounds=5.2694745_43.6259224_5.5063013_43.4461058"
)
STATE_FILE = "crous_aix_state.json"

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
TG_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"].strip()

# Matches listing URLs
ACCOM_RE = re.compile(r"/tools/42/accommodations/(\d+)")
# Matches the visible count like "1 logement trouvé"
COUNT_RE = re.compile(r"(\d+)\s+logement(?:s)?\s+trouvé", re.IGNORECASE)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CROUS-Monitor/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Connection": "close",
}

def tg_send(text: str) -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"initialized": False, "seen_ids": [], "last_count": None}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def fetch_html() -> str:
    # simple retry/backoff
    last = None
    for i in range(3):
        try:
            r = requests.get(SEARCH_URL, headers=HEADERS, timeout=25)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last

def parse_ids_and_count(html: str) -> tuple[set[str], int | None]:
    soup = BeautifulSoup(html, "html.parser")

    # Primary: extract from <a href="...">
    ids = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        m = ACCOM_RE.search(href)
        if m:
            ids.add(m.group(1))

    # Fallback: search in full HTML if structure changes
    for m in ACCOM_RE.finditer(html):
        ids.add(m.group(1))

    text = soup.get_text(" ", strip=True)
    m = COUNT_RE.search(text)
    count = int(m.group(1)) if m else None

    return ids, count

def main():
    html = fetch_html()
    ids_now, count_now = parse_ids_and_count(html)

    state = load_state()
    ids_old = set(state.get("seen_ids", []))
    count_old = state.get("last_count", None)
    initialized = bool(state.get("initialized", False))

    # First run: store baseline + send one confirmation message
    if not initialized:
        state["initialized"] = True
        state["seen_ids"] = sorted(ids_now, key=int) if ids_now else []
        state["last_count"] = count_now
        state["last_checked_epoch"] = int(time.time())
        save_state(state)

        msg = f"CROUS monitor initialized.\nCurrent listings: {count_now if count_now is not None else len(ids_now)}"
        tg_send(msg)
        return

    new_ids = sorted(ids_now - ids_old, key=int)
    removed_ids = sorted(ids_old - ids_now, key=int)

    parts = []

    if count_now is not None and count_old is not None and count_now != count_old:
        parts.append(f"Result count changed: {count_old} → {count_now}")

    if new_ids:
        links = "\n".join(
            f"https://trouverunlogement.lescrous.fr/tools/42/accommodations/{i}" for i in new_ids
        )
        parts.append(f"New listing(s): {len(new_ids)}\n{links}")

    if removed_ids:
        parts.append(f"Listing(s) disappeared: {len(removed_ids)} (IDs: {', '.join(removed_ids)})")

    if parts:
        tg_send("CROUS update (Aix bounds)\n\n" + "\n\n".join(parts))

    state["seen_ids"] = sorted(ids_now, key=int) if ids_now else []
    state["last_count"] = count_now
    state["last_checked_epoch"] = int(time.time())
    save_state(state)

if __name__ == "__main__":
    main()
