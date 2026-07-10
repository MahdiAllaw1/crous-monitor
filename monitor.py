import json
import os
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup


# Each location is monitored separately.
SEARCHES = {
    "Grenoble": (
        "https://trouverunlogement.lescrous.fr/tools/47/search"
        "?occupationModes=alone"
        "&bounds=5.6776059_45.2140762_5.7531176_45.1541442"
        "&locationName=Grenoble"
    ),
    "Saint-Martin-d'Hères": (
        "https://trouverunlogement.lescrous.fr/tools/47/search"
        "?occupationModes=alone"
        "&bounds=5.7430295_45.197351_5.7862526_45.1591062"
        "&locationName=Saint-Martin-d%27H%C3%A8res+%2838400%29"
    ),
    "La Tronche": (
        "https://trouverunlogement.lescrous.fr/tools/47/search"
        "?occupationModes=alone"
        "&bounds=5.7256499_45.2347255_5.7627057_45.188761"
        "&locationName=La+Tronche+%2838700%29"
    ),
}

STATE_FILE = "crous_grenoble_state.json"

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
TG_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"].strip()

# Grenoble CROUS uses tools/47.
ACCOM_RE = re.compile(r"/tools/47/accommodations/(\d+)")

COUNT_RE = re.compile(
    r"(\d+)\s+logement(?:s)?\s+trouvé",
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Connection": "close",
}


def tg_send(text: str) -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=20,
    )
    response.raise_for_status()


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    temporary_file = STATE_FILE + ".tmp"

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            indent=2,
            ensure_ascii=False,
        )

    os.replace(temporary_file, STATE_FILE)


def fetch_html(search_url: str) -> str:
    last_error = None

    for attempt in range(3):
        try:
            response = requests.get(
                search_url,
                headers=HEADERS,
                timeout=25,
            )
            response.raise_for_status()

            return response.text

        except requests.RequestException as error:
            last_error = error
            time.sleep(2 * (attempt + 1))

    raise RuntimeError(
        f"Unable to retrieve CROUS page: {last_error}"
    )


def parse_ids_and_count(
    html: str,
) -> tuple[set[str], Optional[int]]:
    soup = BeautifulSoup(html, "html.parser")
    ids = set()

    # First method: inspect links.
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        match = ACCOM_RE.search(href)

        if match:
            ids.add(match.group(1))

    # Second method: inspect the entire HTML.
    for match in ACCOM_RE.finditer(html):
        ids.add(match.group(1))

    page_text = soup.get_text(" ", strip=True)
    count_match = COUNT_RE.search(page_text)

    count = (
        int(count_match.group(1))
        if count_match
        else None
    )

    return ids, count


def check_location(
    location_name: str,
    search_url: str,
    state: dict,
) -> list[str]:
    html = fetch_html(search_url)
    ids_now, count_now = parse_ids_and_count(html)

    location_state = state.get(
        location_name,
        {
            "initialized": False,
            "seen_ids": [],
            "last_count": None,
        },
    )

    initialized = bool(
        location_state.get("initialized", False)
    )

    ids_old = set(
        location_state.get("seen_ids", [])
    )

    count_old = location_state.get(
        "last_count",
        None,
    )

    messages = []

    if not initialized:
        visible_count = (
            count_now
            if count_now is not None
            else len(ids_now)
        )

        messages.append(
            f"✅ {location_name}: monitor initialized\n"
            f"Current listings: {visible_count}\n"
            f"{search_url}"
        )

    else:
        new_ids = sorted(
            ids_now - ids_old,
            key=int,
        )

        removed_ids = sorted(
            ids_old - ids_now,
            key=int,
        )

        location_parts = []

        if (
            count_now is not None
            and count_old is not None
            and count_now != count_old
        ):
            location_parts.append(
                f"Result count: {count_old} → {count_now}"
            )

        if new_ids:
            accommodation_links = "\n".join(
                (
                    "https://trouverunlogement.lescrous.fr"
                    f"/tools/47/accommodations/{listing_id}"
                )
                for listing_id in new_ids
            )

            location_parts.append(
                f"🚨 NEW LISTING(S): {len(new_ids)}\n"
                f"{accommodation_links}"
            )

        if removed_ids:
            location_parts.append(
                f"Listing(s) disappeared: {len(removed_ids)}\n"
                f"IDs: {', '.join(removed_ids)}"
            )

        if location_parts:
            messages.append(
                f"🏠 CROUS update: {location_name}\n\n"
                + "\n\n".join(location_parts)
                + f"\n\nSearch page:\n{search_url}"
            )

    state[location_name] = {
        "initialized": True,
        "seen_ids": (
            sorted(ids_now, key=int)
            if ids_now
            else []
        ),
        "last_count": count_now,
        "last_checked_epoch": int(time.time()),
    }

    return messages


def main() -> None:
    state = load_state()
    all_messages = []

    for location_name, search_url in SEARCHES.items():
        try:
            messages = check_location(
                location_name,
                search_url,
                state,
            )
            all_messages.extend(messages)

        except Exception as error:
            all_messages.append(
                f"❌ CROUS error for {location_name}\n"
                f"{type(error).__name__}: {error}"
            )

        # Tiny pause between CROUS requests.
        time.sleep(1)

    save_state(state)

    if all_messages:
        # Telegram has a message-size limit, so send separately.
        for message in all_messages:
            tg_send(message)


if __name__ == "__main__":
    main()
