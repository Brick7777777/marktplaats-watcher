"""
Marktplaats watcher
Checks your Marktplaats searches and sends a push notification to your
iPhone for every NEW ad: via ntfy, via Telegram, or both (whichever has its
secrets filled in on GitHub). You normally only edit searches.json.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

SEARCHES_FILE = "searches.json"
SEEN_FILE = "seen.json"
API_URL = "https://www.marktplaats.nl/lrp/api/search"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
MAX_REMEMBERED = 500  # per search, so the seen-list doesn't grow forever

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "nl-NL,nl;q=0.9",
}


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def fetch_listings(query):
    params = {
        "query": query,
        "limit": "50",
        "offset": "0",
        "sortBy": "SORT_INDEX",
        "sortOrder": "DECREASING",  # newest first
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return data.get("listings", [])


def price_euros(listing):
    cents = (listing.get("priceInfo") or {}).get("priceCents")
    return cents / 100 if cents else None


def price_text(listing):
    p = price_euros(listing)
    if p is None:
        return "Prijs onbekend / bieden"
    return f"€ {p:,.0f}".replace(",", ".")


def matches_price(listing, search):
    p = price_euros(listing)
    if p is None:
        return True  # keep 'bieden' ads, you can judge them yourself
    if search.get("min_price") and p < search["min_price"]:
        return False
    if search.get("max_price") and p > search["max_price"]:
        return False
    return True


def matches_words(listing, search):
    """Only keep ads whose title or description contains EVERY word of the
    search term, and none of the words in the optional 'exclude' list."""
    text = (str(listing.get("title", "")) + " " +
            str(listing.get("description", ""))).lower()
    if search.get("strict", True):
        for word in search["query"].lower().split():
            if word not in text:
                return False
    for word in search.get("exclude") or []:
        if str(word).lower() in text:
            return False
    return True


def ad_link(listing):
    path = listing.get("vipUrl") or ""
    if path.startswith("http"):
        return path
    return "https://www.marktplaats.nl" + path


def post_json(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=30).read()


def send_ntfy(title, message, click=None):
    payload = {"topic": NTFY_TOPIC, "title": title, "message": message, "priority": 4}
    if click:
        payload["click"] = click
    post_json("https://ntfy.sh", payload)


def send_telegram(title, message, click=None):
    text = f"{title}\n{message}" + (f"\n{click}" if click else "")
    post_json(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
              {"chat_id": TELEGRAM_CHAT_ID, "text": text})


def notify(title, message, click=None):
    sent = False
    # Each channel is tried on its own, so if one fails the other still works.
    if NTFY_TOPIC:
        try:
            send_ntfy(title, message, click)
            sent = True
        except Exception as e:
            print(f"  ntfy failed: {e}")
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            send_telegram(title, message, click)
            sent = True
        except Exception as e:
            print(f"  Telegram failed: {e}")
    if not sent:
        print("  (no notification sent:)", title, "-", message)


def main():
    searches = load_json(SEARCHES_FILE, [])
    seen = load_json(SEEN_FILE, {})
    failures = 0

    for search in searches:
        query = (search.get("query") or "").strip()
        if not query:
            continue
        print(f"Checking: {query}")
        try:
            listings = fetch_listings(query)
        except Exception as e:  # keep going with the other searches
            print(f"  Could not fetch results: {e}")
            failures += 1
            continue

        first_run = query not in seen
        known = set(seen.get(query, []))
        new_ids = []

        for listing in listings:
            item_id = listing.get("itemId")
            if not item_id or item_id in known:
                continue
            new_ids.append(item_id)
            if first_run or not matches_price(listing, search) \
                    or not matches_words(listing, search):
                continue
            title = listing.get("title", "Nieuwe advertentie")
            city = (listing.get("location") or {}).get("cityName", "")
            message = f"{price_text(listing)}" + (f" · {city}" if city else "")
            print(f"  NEW: {title} ({message})")
            notify(f"🆕 {title}", message, ad_link(listing))

        if first_run:
            notify("Watcher gestart ✅",
                   f"Ik let nu op nieuwe advertenties voor '{query}'.")
            print(f"  First run: remembered {len(new_ids)} existing ads, no alerts sent.")

        seen[query] = (new_ids + seen.get(query, []))[:MAX_REMEMBERED]

    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=1)

    if searches and failures == len(searches):
        print("All searches failed - Marktplaats may be blocking the request.")
        sys.exit(1)


if __name__ == "__main__":
    main()
