"""Minimal Jellyfin REST client (standard library only)."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import net, __version__, branding


def _safe(text):
    """Header-safe ASCII (Jellyfin's auth header can't carry quotes, commas or non-ASCII)."""
    return "".join(c for c in str(text) if c.isascii() and c not in '",=\r\n').strip() or "Barnes TV"

ITEM_FIELDS = "Path,Genres,Overview,PremiereDate,OfficialRating,ProductionYear,ParentId,Chapters"
PLAYABLE = {"Movie", "Episode", "MusicVideo", "Video"}


class JellyfinError(Exception):
    pass


class Jellyfin:
    def __init__(self, url, api_key, user_id="", timeout=30):
        self.url = (url or "").rstrip("/")
        self.key = api_key or ""
        self._user_id = user_id or ""
        self.timeout = timeout

    # ---------- plumbing ----------
    @property
    def auth_header(self):
        return (f'MediaBrowser Client="{_safe(branding.short())} Broadcast", Device="{_safe(branding.short())} Broadcast Server", '
                f'DeviceId="jellyfin-broadcast", Version="{__version__}", Token="{self.key}"')

    def _request(self, path, params=None, method="GET"):
        if not self.url:
            raise JellyfinError("Jellyfin URL is not set")
        q = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
        url = f"{self.url}{path}"
        if q:
            url += "?" + urllib.parse.urlencode(q, doseq=False)
        req = urllib.request.Request(url, method=method, headers={
            "Authorization": self.auth_header, "Accept": "application/json"})
        try:
            with net.urlopen(req, timeout=self.timeout) as r:
                body = r.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            raise JellyfinError(f"{e.code} {e.reason} for {path}") from e
        except urllib.error.URLError as e:
            raise JellyfinError(f"Cannot reach Jellyfin at {self.url}: {e.reason}") from e

    def get(self, path, **params):
        return self._request(path, params)

    # ---------- server / users ----------
    def system_info(self):
        return self.get("/System/Info")

    def users(self):
        return self.get("/Users") or []

    @property
    def user_id(self):
        if not self._user_id:
            users = self.users()
            admin = [u for u in users if (u.get("Policy") or {}).get("IsAdministrator")]
            pick = (admin or users or [None])[0]
            if not pick:
                raise JellyfinError("No Jellyfin users found")
            self._user_id = pick["Id"]
        return self._user_id

    # ---------- browsing ----------
    def items(self, **params):
        """Paged /Items query; returns every matching item."""
        params.setdefault("userId", self.user_id)
        params.setdefault("Fields", ITEM_FIELDS)
        params.setdefault("EnableUserData", "false")
        params.setdefault("EnableImageTypes", "Primary,Thumb,Backdrop")
        params.setdefault("ImageTypeLimit", 1)
        out, start, page = [], 0, 1000
        while True:
            res = self.get("/Items", StartIndex=start, Limit=page, **params) or {}
            batch = res.get("Items", [])
            out += batch
            start += len(batch)
            if not batch or start >= res.get("TotalRecordCount", 0):
                return out

    def libraries(self):
        try:
            views = self.get("/UserViews", userId=self.user_id) or {}
        except JellyfinError:
            views = self.get(f"/Users/{self.user_id}/Views") or {}
        return [{"id": v["Id"], "name": v["Name"], "kind": v.get("CollectionType", "")}
                for v in views.get("Items", []) if v.get("CollectionType") in (None, "", "movies", "tvshows",
                                                                                "musicvideos", "homevideos", "mixed",
                                                                                "boxsets")]

    def _named(self, path, **params):
        res = self.get(path, userId=self.user_id, Recursive="true", **params) or {}
        return [{"id": i.get("Id", i["Name"]), "name": i["Name"]} for i in res.get("Items", [])]

    def genres(self):
        return self._named("/Genres", IncludeItemTypes="Movie,Series,MusicVideo")

    def studios(self):
        return self._named("/Studios", IncludeItemTypes="Movie,Series")

    def tags(self):
        res = self.get("/Items/Filters", userId=self.user_id, IncludeItemTypes="Movie,Series,Episode,MusicVideo") or {}
        return [{"id": t, "name": t} for t in res.get("Tags", [])]

    def collections(self):
        return [{"id": i["Id"], "name": i["Name"]} for i in
                self.items(IncludeItemTypes="BoxSet", Recursive="true", Fields="", EnableImageTypes="")]

    def playlists(self):
        return [{"id": i["Id"], "name": i["Name"]} for i in
                self.items(IncludeItemTypes="Playlist", Recursive="true", Fields="", EnableImageTypes="")]

    def series(self, search=""):
        return [{"id": i["Id"], "name": i["Name"] + (f" ({i['ProductionYear']})" if i.get("ProductionYear") else "")}
                for i in self.items(IncludeItemTypes="Series", Recursive="true", SearchTerm=search or None,
                                    Fields="", EnableImageTypes="", SortBy="SortName")]

    def list_sources(self, kind, search=""):
        fn = {"library": self.libraries, "genre": self.genres, "studio": self.studios, "tag": self.tags,
              "collection": self.collections, "playlist": self.playlists}.get(kind)
        if kind == "series":
            return self.series(search)
        if not fn:
            raise JellyfinError(f"Unknown source type {kind}")
        res = fn()
        if search:
            res = [r for r in res if search.lower() in r["name"].lower()]
        return sorted(res, key=lambda r: r["name"].lower())

    # ---------- resolving sources into playable items ----------
    def episodes_of(self, series_id):
        return self.items(ParentId=series_id, Recursive="true", IncludeItemTypes="Episode",
                          SortBy="ParentIndexNumber,IndexNumber,SortName")

    def _expand(self, items, depth=0):
        out = []
        for it in items:
            t = it.get("Type")
            if t in PLAYABLE:
                out.append(it)
            elif t in ("Series", "Season"):
                out += self.episodes_of(it["Id"])
            elif t in ("BoxSet", "Folder", "CollectionFolder", "Playlist") and depth < 3:
                out += self._expand(self.items(ParentId=it["Id"]), depth + 1)
        return out

    def resolve_source(self, src, item_types):
        kind, sid, name = src.get("type"), src.get("id"), src.get("name")
        types = ",".join(item_types or ["Movie", "Episode"])
        if kind == "library":
            return self.items(ParentId=sid, Recursive="true", IncludeItemTypes=types)
        if kind == "series":
            return self.episodes_of(sid)
        if kind == "collection":
            return self._expand(self.items(ParentId=sid))
        if kind == "playlist":
            res = self.get(f"/Playlists/{sid}/Items", userId=self.user_id, Fields=ITEM_FIELDS) or {}
            return self._expand(res.get("Items", []))
        if kind in ("genre", "tag", "studio"):
            key = {"genre": "Genres", "tag": "Tags", "studio": "Studios"}[kind]
            top = self.items(Recursive="true", IncludeItemTypes="Movie,Series,MusicVideo,Video", **{key: name or sid})
            return self._expand(top)
        raise JellyfinError(f"Unknown source type {kind}")

    def item_details(self, item_id):
        try:
            return self.get(f"/Items/{item_id}", userId=self.user_id, Fields="MediaStreams,MediaSources,Path")
        except JellyfinError:
            return self.get(f"/Users/{self.user_id}/Items/{item_id}")

    # ---------- URLs ----------
    def stream_url(self, item_id):
        return f"{self.url}/Videos/{item_id}/stream?static=true"

    def subtitle_url(self, item_id, source_id, index, fmt="srt"):
        """A subtitle track as a text file (Jellyfin extracts / converts it; works for embedded and sidecar files)."""
        return f"{self.url}/Videos/{item_id}/{source_id or item_id}/Subtitles/{index}/Stream.{fmt}"

    def image_url(self, item_id, kind="Primary", max_height=360):
        return f"{self.url}/Items/{item_id}/Images/{kind}?maxHeight={max_height}&quality=85"

    def fetch_bytes(self, url, timeout=15):
        req = urllib.request.Request(url, headers={"Authorization": self.auth_header})
        with net.urlopen(req, timeout=timeout) as r:
            return r.read()


def normalize_item(it):
    """Reduce a Jellyfin item to what the scheduler needs."""
    dur = (it.get("RunTimeTicks") or 0) / 1e7
    is_ep = it.get("Type") == "Episode"
    return {
        "id": it["Id"],
        "type": it.get("Type"),
        "title": (it.get("SeriesName") if is_ep and it.get("SeriesName") else it.get("Name")) or "Untitled",
        "episode_title": it.get("Name") if is_ep else "",
        "series_id": it.get("SeriesId") or "",
        "season": it.get("ParentIndexNumber"),
        "episode": it.get("IndexNumber"),
        "year": it.get("ProductionYear"),
        "overview": (it.get("Overview") or "")[:600],
        "genres": (it.get("Genres") or [])[:4],
        "rating": it.get("OfficialRating") or "",
        "duration": round(dur, 3),
        "premiere": (it.get("PremiereDate") or "")[:10],
        "image_id": it["Id"] if (it.get("ImageTags") or {}).get("Primary") else (it.get("SeriesId") or it["Id"]),
        "path": it.get("Path") or "",
        "location": it.get("LocationType") or "",
        "chapters": sorted({round((c.get("StartPositionTicks") or 0) / 1e7, 1) for c in it.get("Chapters") or []
                            if 30 < (c.get("StartPositionTicks") or 0) / 1e7 < dur - 30}),
    }


def map_path(path, mappings):
    for m in mappings or []:
        src, dst = m.get("from") or "", m.get("to") or ""
        if src and path.lower().startswith(src.lower()):
            rest = path[len(src):].lstrip("/\\")
            sep = "\\" if os.name == "nt" else "/"
            return dst.rstrip("/\\") + sep + rest.replace("/" if sep == "\\" else "\\", sep)
    return path
