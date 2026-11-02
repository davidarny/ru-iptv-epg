# ru-iptv-epg

Russian IPTV playlist with a matching TV guide, rebuilt daily by GitHub Actions for Kodi (PVR IPTV Simple Client).

- Playlist: <https://raw.githubusercontent.com/davidarny/ru-iptv-epg/data/playlist.m3u>
- Guide: <https://raw.githubusercontent.com/davidarny/ru-iptv-epg/data/epg.xml.gz>

`build.py` takes the [iptv-org](https://github.com/iptv-org/iptv) Russian playlist, matches each channel to the
[iptvx.one](https://iptvx.one) guide through the names and alternative names in the iptv-org channel database,
writes the guide id (and `tvg-shift` for `+N` time-shifted feeds) into the playlist, and cuts the guide down to the
matched channels, from a day back to eight days ahead. The streams are whatever iptv-org lists; nothing is hosted here.

Run locally: `python3 build.py dist`.
