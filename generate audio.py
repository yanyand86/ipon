#!/usr/bin/env python3
"""
Ipon audio generator.

Reads the chapter text straight out of index.html (so the words you edit in the
app are always the words that get spoken), turns each chapter into a natural
British neural voice MP3 with edge-tts, and writes audio/manifest.json so the
app knows which files exist. Unchanged chapters are skipped on re-runs.

Runs in the cloud via GitHub Actions — you never need Python on your phone.
"""

import asyncio
import hashlib
import json
import os
import re
import sys

import edge_tts

# ---- settings you can change -------------------------------------------------
# Pick any British neural voice. Female: en-GB-SoniaNeural, en-GB-LibbyNeural.
# Male: en-GB-RyanNeural, en-GB-ThomasNeural. Sonia is warm and natural.
VOICE = "en-GB-SoniaNeural"
RATE = "+0%"      # e.g. "-8%" to slow down, "+10%" to speed up
PITCH = "+0Hz"    # e.g. "-2Hz" for a slightly lower tone
SOURCE = "index.html"
OUT_DIR = "audio"
CACHE_FILE = os.path.join(OUT_DIR, ".voicecache.json")
# -----------------------------------------------------------------------------

# Matches each chapter object in the CHAPTERS array. Field order is fixed:
# id, tag, title, blurb, body(`...`), quiz
CHAPTER_RE = re.compile(
    r'id:"(?P<id>[^"]+)",\s*tag:"[^"]+",\s*title:"(?P<title>[^"]+)",'
    r'\s*blurb:"[^"]*",\s*body:`(?P<body>.*?)`,\s*quiz:',
    re.DOTALL,
)

CALLOUT_LEAD = {
    "key": "Key idea.",
    "ph": "Philippines corner.",
    "uk": "UK corner.",
    "warn": "Watch out.",
}


def parse_chapters(html):
    start = html.find("const CHAPTERS = [")
    if start == -1:
        sys.exit("Could not find CHAPTERS in index.html")
    block = html[start:]
    chapters = [m.groupdict() for m in CHAPTER_RE.finditer(block)]
    if not chapters:
        sys.exit("Parsed zero chapters — has the CHAPTERS format changed?")
    return chapters


def clean_for_speech(body):
    """Mirror the app's speakable-text logic, but keep whole paragraphs so the
    voice pauses naturally at blank lines."""
    lines = []
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if line.startswith("## "):
            line = line[3:]
        elif line.startswith("- "):
            line = line[2:]
        else:
            m = re.match(r"^>\s*(key|ph|uk|warn):\s*(.*)$", line)
            if m:
                line = CALLOUT_LEAD[m.group(1)] + " " + m.group(2)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)          # drop bold marks
        line = re.sub(r"\{(.+?)\}", r"\1", line)               # drop figure braces
        line = re.sub(r"₱\s?([\d,]+)", r"\1 pesos", line)      # ₱200,000 -> pesos
        line = line.replace("₱", "pesos ")
        line = re.sub(r"\bOFWs\b", "overseas Filipino workers", line)
        line = re.sub(r"\bOFW\b", "overseas Filipino worker", line)
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


async def synth(text, path):
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
    await communicate.save(path)


def main():
    html = open(SOURCE, encoding="utf-8").read()
    chapters = parse_chapters(html)
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = load_cache()
    manifest_chapters = []
    made, skipped = 0, 0

    for ch in chapters:
        spoken = f"{ch['title']}.\n\n{clean_for_speech(ch['body'])}"
        fname = f"chapter-{ch['id']}.mp3"
        fpath = os.path.join(OUT_DIR, fname)
        digest = hashlib.sha1(f"{VOICE}|{RATE}|{PITCH}|{spoken}".encode("utf-8")).hexdigest()

        if cache.get(ch["id"]) == digest and os.path.exists(fpath):
            print(f"= {ch['id']}: unchanged")
            skipped += 1
        else:
            print(f"~ {ch['id']}: generating with {VOICE} ...")
            asyncio.run(synth(spoken, fpath))
            cache[ch["id"]] = digest
            made += 1

        manifest_chapters.append({"id": ch["id"], "file": fname, "title": ch["title"]})

    save_cache(cache)
    manifest = {"voice": VOICE, "chapters": manifest_chapters}
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone. {made} generated, {skipped} unchanged, {len(chapters)} total.")


if __name__ == "__main__":
    main()
