# trana-twinton-link

The live link between **Trana** (trana.app) and **Twinton** (maps.ce-net.com).

- Twin: <https://maps.ce-net.com/?app=https%3A%2F%2Fleif-rydenfalk.github.io%2Ftrana-twinton-link%2Ftwin%2Fapp.json>
- Trana: <https://trana.app/>
- Bridge: <https://leif-rydenfalk.github.io/trana-twinton-link/bridge.json>
- Status page: <https://leif-rydenfalk.github.io/trana-twinton-link/>

## What is linked

The twin on Twinton is a small relay cabinet at ce-net's home in Umeå. Every 60 s it reads
Trana's public layer (`trana.feed/2`), a heartbeat-written mirror of the public `trana_feed` read, and
Trana's world of named places (`trana.world/2`). It looks for the announcement post whose title starts
with `Trana-Twinton relay`. The post names the twin; the twin names the post. Neither side copies the other.

The mirror exists because the public layer lagged the `trana_feed` read by over two hours on 27 Oct 2026
(R-019). The twin shows both: `Feed mirror · fresh` beside `Public layer · stale`.

## The heartbeat

`heartbeat.py` runs in GitHub Actions every ten minutes (best effort). It fetches:

1. the published twin manifest at `leif-rydenfalk.github.io/trana-twinton-link/twin/app.json`;
2. Trana's public layer at `maps.ce-net.com/tiles/layers/trana-feed.json`;
3. the public `trana_feed` read at `ce-net.com/mcp`;
4. the previous `bridge.json`, so a transient failure does not erase the thread id.

It writes `feed.json` (the read-only mirror) and `bridge.json` with one of three states:

| state | meaning |
|---|---|
| `live` | the twin manifest is there, the announcement is found, and the feed mirror was written |
| `stale` | both ends are there, but the public `trana_feed` read failed |
| `broken` | the twin, the announcement, or the feed is missing |

The workflow commits the new bridge and **fails** when the state is not `live`, so a break shows in
the repository's Actions tab. There is no secret in this repository and no write to Trana.

## Honest limits

- GitHub's scheduler can run late. The status page shows the heartbeat's own age, not a promise.
- The public layer is a snapshot. A just-published announcement can be absent for a few minutes.
- The cabinet is schematic; the arcs are links to places, not cables; packet motion illustrates the
  modelled posting rhythm and is not real traffic.
- The heartbeat does not repair a missing post. Re-posting automatically would create duplicates;
  the failure is reported instead.

## Local use

```bash
python3 heartbeat.py        # writes bridge.json in this directory
python3 -m http.server 8000 # open http://127.0.0.1:8000/
```
