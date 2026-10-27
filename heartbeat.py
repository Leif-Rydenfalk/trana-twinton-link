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
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(ROOT, "bridge.json")
TWIN_ID = "trana-relay"
TWIN_MANIFEST = "https://tiles.ce-net.com/community/trana-relay/app.json"
TWIN_OPEN = "https://maps.ce-net.com/?app=trana-relay"
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
        else:
            # The public layer is a snapshot and can lag a just-published post. Ask the door's public
            # trana_feed read as a second opinion; the twin itself can only read the layer, so a post
            # found here and not there is still reported as "stale", not "live".
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
                feed = json.loads(text)
                post = next((p for p in feed.get("posts", []) if str(p.get("title", "")).startswith(POST_PREFIX)), None)
                if post:
                    post_source = "api"
            except Exception as e:  # noqa: BLE001 - the layer is the twin's own source; the API is a fallback
                errors.append(f"trana_feed fallback: {e}")
            if not post:
                errors.append("announcement is not in the public layer or the feed API")

    twin_ok = twin is not None
    post_ok = post is not None
    if not twin_ok or not post_ok or layer is None:
        state = "broken"
    elif post_source != "layer" or (layer_age_s is not None and layer_age_s > 3600):
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
        "thread_url": "https://trana.app/" if thread else None,
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
