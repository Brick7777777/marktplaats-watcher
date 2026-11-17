"""
Page watcher
Checks web pages (for example a shop's home page) and sends you a message as
soon as one of your keywords appears on it, like "black friday".
You normally only edit pages.json.
Alerts go to the same ntfy / Telegram as the Marktplaats watcher.
"""
import html
import json
import re
import urllib.request

from watcher import notify, load_json

PAGES_FILE = "pages.json"
STATE_FILE = "pages_seen.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "nl-NL,nl;q=0.9",
}


def fetch_page(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def visible_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def snippet(text, keyword):
    i = text.lower().find(keyword)
    if i < 0:
        return None
    start, end = max(0, i - 60), min(len(text), i + len(keyword) + 80)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def main():
    pages = load_json(PAGES_FILE, [])
    state = load_json(STATE_FILE, {})

    for page in pages:
        url = (page.get("url") or "").strip()
        if not url:
            continue
        name = page.get("name") or url
        keywords = [str(k).lower() for k in page.get("keywords") or []]
        print(f"Checking page: {name}")
        try:
            raw = fetch_page(url)
        except Exception as e:  # one broken page shouldn't stop the rest
            print(f"  Could not fetch page: {e}")
            continue

        text = visible_text(raw)
        # Also look at banner image descriptions (alt/title), but not at the
        # site's hidden code, which often mentions "black friday" too early.
        no_code = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
        labels = re.findall(r'(?i)\b(?:alt|title|aria-label)\s*=\s*"([^"]*)"', no_code)
        haystack = (text + " " + " ".join(html.unescape(l) for l in labels)).lower()
        found = [k for k in keywords if k in haystack]
        already = set(state.get(url, []))

        for k in found:
            if k in already:
                continue
            context = snippet(text, k) or "Gevonden op de pagina (bijvoorbeeld in een banner)."
            print(f"  FOUND: '{k}'")
            notify(f"🔔 {name}: '{k}' staat op de site", context, url)

        # Remember what is on the page now. If a word disappears and later
        # comes back, you get a new alert.
        state[url] = found
        print(f"  Keywords on page now: {found or 'none'}")

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


if __name__ == "__main__":
    main()
