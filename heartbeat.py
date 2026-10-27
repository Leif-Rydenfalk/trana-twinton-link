#!/usr/bin/env python3
"""Heartbeat for the Trana-Twinton link.

Checks the two public ends and writes one small bridge file, bridge.json:
  - the twin manifest on tiles.ce-net.com (is the twin still published?)
  - the public Trana layer on maps.ce-net.com (is the announcement still in it, and how old is the layer?)
  - the previous bridge (runs, last state, thread) so a transient failure does not erase the link

The state is one of:
  live    both ends present and the layer is less than an hour old
  stale   both ends present, but the layer is older than an hour
  broken  the twin manifest, the layer, or the announcement is missing

No credentials. No writes to Trana. The twin reads this file; the GitHub Action commits it.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(ROOT, "bridge.json")
MIRROR = os.path.join(ROOT, "feed.json")
TWIN_ID = "trana-relay"
TWIN_MANIFEST = "https://leif-rydenfalk.github.io/trana-twinton-link/twin/app.json"
TWIN_OPEN = "https://maps.ce-net.com/?app=https%3A%2F%2Fleif-rydenfalk.github.io%2Ftrana-twinton-link%2Ftwin%2Fapp.json"
TRANA_LAYER = "https://maps.ce-net.com/tiles/layers/trana-feed.json"
TRANA_API = "https://ce-net.com/mcp"
TRANA_WORLD = "https://www.trana.app/data/world.json"
POST_PREFIX = "Trana-Twinton relay"
UA = "trana-twinton-link/1 (+https://github.com/Leif-Rydenfalk/trana-twinton-link)"
TIMEOUT = 30


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        if r.status != 200:
            raise RuntimeError(f"GET {url} -> {r.status}")
        return json.loads(r.read().decode("utf-8"))


def load_previous():
    try:
        with open(BRIDGE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main() -> int:
    now = int(time.time())
    prev = load_previous()
    errors = []
    twin = layer = None

    try:
        twin = get_json(TWIN_MANIFEST)
        if not isinstance(twin, dict) or twin.get("id") != TWIN_ID:
            errors.append(f"twin manifest id is {twin.get('id') if isinstance(twin, dict) else 'not an object'!r}")
            twin = None
    except Exception as e:  # noqa: BLE001 - the bridge must record every failure, not raise
        errors.append(f"twin manifest: {e}")

    try:
        layer = get_json(TRANA_LAYER)
        if not isinstance(layer, dict) or not isinstance(layer.get("posts"), list):
            errors.append("Trana layer has no posts list")
            layer = None
    except Exception as e:  # noqa: BLE001
        errors.append(f"Trana layer: {e}")

    # The public layer is a snapshot and can lag. Read the door's public trana_feed as well, and
    # publish it as feed.json: the twin reads that mirror when the layer is behind.
    api_feed = None
    api_error = None
    try:
        req = urllib.request.Request(
            TRANA_API,
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "trana_feed", "arguments": {"limit": 50}}}).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                     "User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            api = json.loads(r.read().decode("utf-8"))
        text = "".join(c.get("text", "") for c in api.get("result", {}).get("content", []))
        api_feed = json.loads(text)
        if not isinstance(api_feed.get("posts"), list):
            api_feed = None
            raise RuntimeError("trana_feed has no posts list")
    except Exception as e:  # noqa: BLE001
        api_error = str(e)
        errors.append(f"trana_feed: {e}")

    post = None
    layer_age_s = None
    post_source = None
    if layer:
        posts = [p for p in layer.get("posts", []) if isinstance(p, dict)]
        post = next((p for p in posts if str(p.get("title", "")).startswith(POST_PREFIX)), None)
        if layer.get("at_s"):
            layer_age_s = max(0, now - int(layer["at_s"]))
        if post:
            post_source = "layer"

    if api_feed:
        api_post = next((p for p in api_feed.get("posts", []) if str(p.get("title", "")).startswith(POST_PREFIX)), None)
        if api_post:
            post, post_source = api_post, "api"
        # publish the mirror even when the layer is the source: it is the twin's fast path
        mirror = {
            "schema": "trana.feed.mirror/1",
            "source": "https://ce-net.com/mcp trana_feed (public read)",
            "read_at": now,
            "at_s": now,
            "posts": api_feed.get("posts", []),
            "spaces": api_feed.get("spaces", []),
        }
        tmp_m = MIRROR + ".tmp"
        with open(tmp_m, "w", encoding="utf-8") as f:
            json.dump(mirror, f, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_m, MIRROR)

    if not post:
        errors.append("announcement is not in the public layer, the feed API or the mirror")

    twin_ok = twin is not None
    post_ok = post is not None
    feed_ok = api_feed is not None
    if not twin_ok or not post_ok:
        state = "broken"
    elif not feed_ok:
        state = "stale"
    else:
        state = "live"

    thread = (post or {}).get("thread") or prev.get("thread") or None
    title = (post or {}).get("title") or prev.get("title") or POST_PREFIX
    heartbeat = prev.get("heartbeat") or {}
    runs = int(heartbeat.get("runs") or 0) + 1
    last_state = heartbeat.get("last_state")
    changed_at = int(heartbeat.get("changed_at") or now) if last_state == state else now
    since = int(heartbeat.get("since") or now) if heartbeat.get("since") and last_state == state else now

    bridge = {
        "schema": "twinton.trana/1",
        "twin": TWIN_ID,
        "title": title,
        "twin_url": TWIN_OPEN,
        "thread": thread,
        "thread_url": ("https://trana.app/?t=" + urllib.parse.quote(thread, safe="")) if thread else None,
        "link": {
            "state": state,
            "checked_at": now,
            "twin_ok": twin_ok,
            "post_ok": post_ok,
            "layer_ok": layer is not None,
            "layer_age_s": layer_age_s,
            "post_title": (post or {}).get("title"),
            "post_source": post_source,
            "errors": errors,
        },
        "heartbeat": {
            "updated": now,
            "runs": runs,
            "last_state": state,
            "changed_at": changed_at,
            "since": since,
            "schedule": "every 10 min (GitHub Actions best effort)",
        },
        "sources": [
            {"id": "trana-layer", "url": TRANA_LAYER, "kind": "observed", "cadence_s": 300,
             "credit": "Trana public layer (trana.feed/2), read by the twin and by this heartbeat"},
            {"id": "trana-world", "url": TRANA_WORLD, "kind": "observed", "cadence_s": 3600,
             "credit": "Trana world of named places (trana.world/2)"},
            {"id": "twin-manifest", "url": TWIN_MANIFEST, "kind": "observed", "cadence_s": 60,
             "credit": f"Published Twinton twin {TWIN_ID}"},
        ],
        "streams": [
            {"id": "trana-post", "kind": "social", "url": "https://trana.app/", "state": "found" if post_ok else "missing"},
        ],
        "mirror": {
            "url": "https://leif-rydenfalk.github.io/trana-twinton-link/feed.json",
            "read_at": now if feed_ok else (prev.get("mirror") or {}).get("read_at"),
            "ok": feed_ok,
            "posts": len(api_feed.get("posts", [])) if api_feed else (prev.get("mirror") or {}).get("posts"),
        },
        "updated": now,
    }

    tmp = BRIDGE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bridge, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, BRIDGE)

    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp} state={state} twin_ok={twin_ok} post_ok={post_ok} "
          f"layer_age={layer_age_s}s errors={len(errors)}")
    for e in errors:
        print("  -", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
