#!/usr/bin/env python3
"""Build a Russian IPTV playlist with a matching, trimmed XMLTV guide.

Inputs (downloaded):
  - iptv-org Russian playlist and its channel database (names and alternative names)
  - iptvx.one XMLTV guide (all channels, ~200 MB unpacked)

Outputs in the output directory:
  - playlist.m3u  every channel of the iptv-org playlist; matched ones get tvg-id of the guide
  - epg.xml.gz    the guide cut down to the matched channels and to a window around now

Usage: build.py [output_dir]
"""
import gzip
import io
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLAYLIST_URL = "https://iptv-org.github.io/iptv/countries/ru.m3u"
CHANNELS_URL = "https://iptv-org.github.io/api/channels.json"
# epg_noarch has programme descriptions; epg_lite carries titles only.
EPG_URL = "https://iptvx.one/epg/epg_noarch.xml.gz"
# iptvx puts U+250A before episode numbers ("СашаТаня ┊ 36"); Kodi's font has no glyph for it.
SEPARATORS = str.maketrans({"┊": "·"})
PAST = timedelta(days=1)
FUTURE = timedelta(days=8)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ru-iptv-epg/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def norm(name: str) -> str:
    return re.sub(r"[\s\-_.!«»\"'’]+", "", name.lower()).replace("ё", "е")


def is_cyrillic(name: str) -> bool:
    return bool(re.search(r"[а-яА-ЯёЁ]", name))


def parse_time(value: str) -> datetime:
    # XMLTV: 20261102150000 +0300
    stamp, _, offset = value.partition(" ")
    dt = datetime.strptime(stamp[:14], "%Y%m%d%H%M%S")
    if offset:
        sign = 1 if offset[0] == "+" else -1
        dt -= sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))
    return dt.replace(tzinfo=timezone.utc)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    out.mkdir(parents=True, exist_ok=True)

    playlist = fetch(PLAYLIST_URL).decode("utf-8").splitlines()
    channels = {c["id"]: c for c in json.loads(fetch(CHANNELS_URL))}
    epg_raw = gzip.decompress(fetch(EPG_URL))

    # Guide index: normalised display name -> guide channel id. First name wins.
    guide_channels = {}
    index = {}
    exact = {}
    for _, el in ET.iterparse(io.BytesIO(epg_raw), events=("end",)):
        if el.tag == "channel":
            cid = el.get("id")
            guide_channels[cid] = el
            for dn in el.findall("display-name"):
                if dn.text:
                    index.setdefault(norm(dn.text), cid)
                    exact.setdefault(dn.text.strip().lower(), cid)
        elif el.tag == "programme":
            break  # channels come first in this guide

    def match(extinf: str) -> tuple[str | None, int]:
        m = re.search(r'tvg-id="([^"@]*)(?:@([^"]*))?"', extinf)
        base, feed = (m.group(1), m.group(2) or "") if m else ("", "")
        title = extinf.rsplit(",", 1)[1]
        clean = re.sub(r"\s*(\(\d+[pi]\)|\[[^\]]*\])", "", title).strip()
        shift = re.search(r"\+(\d{1,2})$", clean)
        hours = int(shift.group(1)) if shift else 0
        clean = re.sub(r"\s*\+\d{1,2}$", "", clean)
        c = channels.get(base, {})
        alts = c.get("alt_names", [])
        suffix = " hd" if feed.upper() == "HD" else ""
        # 1. The channel's own name, exactly (an iptv-org alt name can be wrong: 1HD -> Музыка Первого).
        for n in filter(None, [c.get("name", ""), clean]):
            for v in ([n + suffix] if suffix else []) + [n]:
                cid = exact.get(v.strip().lower())
                if cid:
                    return cid, hours
        # 2. Loose matching, Cyrillic names first: loose Latin names collide with foreign channels
        # (NTV and the German n-tv both normalise to "ntv").
        names = [n for n in alts if is_cyrillic(n)] + [c.get("name", ""), clean] + [
            n for n in alts if not is_cyrillic(n)
        ]
        for n in filter(None, names):
            for v in ([n + suffix] if suffix else []) + [n]:
                cid = index.get(norm(v))
                if cid:
                    return cid, hours
        return None, hours

    lines = ['#EXTM3U x-tvg-url="https://raw.githubusercontent.com/davidarny/ru-iptv-epg/data/epg.xml.gz"']
    used = set()
    total = matched = 0
    i = 0
    while i < len(playlist):
        line = playlist[i]
        if line.startswith("#EXTINF"):
            total += 1
            block = [line]
            j = i + 1
            while j < len(playlist) and playlist[j].startswith("#") and not playlist[j].startswith("#EXTINF"):
                block.append(playlist[j])
                j += 1
            url = playlist[j] if j < len(playlist) else ""
            cid, hours = match(line)
            extinf = re.sub(r'\s*tvg-id="[^"]*"', "", line)
            # imgur answers blocked regions (the UK among them) with a "Content not viewable in your region" picture
            # instead of the logo: use the guide's icon when there is one, otherwise no logo.
            if re.search(r'tvg-logo="https?://(i\.)?imgur\.com/', extinf):
                icon = guide_channels[cid].find("icon") if cid else None
                logo = icon.get("src") if icon is not None else ""
                extinf = re.sub(r'tvg-logo="[^"]*"', f'tvg-logo="{logo}"', extinf)
            if cid:
                matched += 1
                used.add(cid)
                attrs = f' tvg-id="{cid}"' + (f' tvg-shift="{hours}"' if hours else "")
                extinf = extinf.replace("#EXTINF:-1", "#EXTINF:-1" + attrs, 1)
                # Russian display name from the guide, keeping the HD and +N marks of the original.
                ru = next((d.text for d in guide_channels[cid].findall("display-name")
                           if d.text and is_cyrillic(d.text)), None)
                if ru:
                    title = extinf.rsplit(",", 1)[1]
                    marks = ""
                    if re.search(r"\bHD\b", title) and not re.search(r"\bHD\b", ru):
                        marks += " HD"
                    if hours:
                        marks += f" +{hours}"
                    extinf = extinf.rsplit(",", 1)[0] + "," + ru + marks
            lines += [extinf, *block[1:], url]
            i = j + 1
        else:
            i += 1

    now = datetime.now(timezone.utc)
    lo, hi = now - PAST, now + FUTURE
    tv = ET.Element("tv", {"generator-info-name": "ru-iptv-epg", "source-info-name": "iptvx.one"})
    for cid in sorted(used):
        tv.append(guide_channels[cid])
    programmes = 0
    for _, el in ET.iterparse(io.BytesIO(epg_raw), events=("end",)):
        if el.tag != "programme":
            continue
        if el.get("channel") in used:
            try:
                keep = parse_time(el.get("stop")) >= lo and parse_time(el.get("start")) <= hi
            except (TypeError, ValueError):
                keep = False
            if keep:
                for child in el:
                    if child.text:
                        child.text = child.text.translate(SEPARATORS)
                tv.append(el)
                programmes += 1
                continue
        el.clear()

    (out / "playlist.m3u").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with gzip.open(out / "epg.xml.gz", "wb", compresslevel=9) as f:
        ET.ElementTree(tv).write(f, encoding="utf-8", xml_declaration=True)
    print(f"channels {total}, with guide {matched}, guide channels {len(used)}, programmes {programmes}")


if __name__ == "__main__":
    main()
