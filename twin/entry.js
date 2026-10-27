// Trana-Twinton relay: a deliberately small digital twin of the LINK between two sites, not of a factory.
//
// Subject:  the public Trana layer (trana.feed/2) at maps.ce-net.com, and Trana's world of named places
//           (trana.world/2) at trana.app. Both are read-only and send CORS; the sandbox fetches only these.
// Model:    a posting-rhythm model over the intervals between the layer's posts (EMA), backtested on the
//           interval sequence; the panel shows the mean absolute error, not a claim of accuracy.
// Twin:     a schematic relay cabinet at ce-net's home in Umea (the `ce-net` subject in Trana's world).
//           The beacon is green while the layer is fresh, amber while it lags, red when it is stale or
//           unreachable. Activity bars are two-hour buckets from the same layer; arcs point at the places
//           Trana's subjects name. The cabinet is not a survey of a real building.
// Link:     the announcement post is found by title in the layer, so both sides point at each other:
//           the post names this twin; the twin looks the post up. If either side disappears, the panel says so.
//
// No network beyond the manifest's data URLs; no storage; no eval. Every call is ctx.

const LAT = 63.826, LON = 20.263;                 // Umea, where the ce-net subject is placed in Trana's world
const FEED = "https://maps.ce-net.com/tiles/layers/trana-feed.json";
const WORLD = "https://www.trana.app/data/world.json";
const BRIDGE = "https://leif-rydenfalk.github.io/trana-twinton-link/bridge.json";
const MIRROR = "https://leif-rydenfalk.github.io/trana-twinton-link/feed.json";
const TWIN_URL = "https://maps.ce-net.com/?app=https%3A%2F%2Fleif-rydenfalk.github.io%2Ftrana-twinton-link%2Ftwin%2Fapp.json";
const POST_PREFIX = "Trana-Twinton relay";         // the announcement's title starts with this
const CYAN = "#4fe3ff", AMBER = "#ffb547", GREEN = "#43e08a", RED = "#ff6b6b";
const READ_MS = 60_000;

export async function start(ctx) {
  ctx.base("density", false); ctx.base("flows", false); ctx.base("joined", false); ctx.base("lanes", false);
  const f = await ctx.local(LAT, LON);
  const box = (size, at, color, emissive, heading = 0) =>
    ctx.box({ frame: f, size, at, color, emissive, heading });

  // ---------------------------------------------------------------- the cabinet, built before any fetch
  await box([10, 0.2, 10], [0, 0, 0], "#141c26");                       // service pad
  await box([2.6, 2.4, 1.8], [0, 0.2, 0], "#33404f");                   // cabinet shell
  await box([2.2, 1.5, 0.06], [0, 0.55, -0.93], "#222c38");             // door
  for (let i = 0; i < 4; i++) await box([1.6, 0.04, 0.03], [0, 0.42 + i * 0.12, -0.97], "#55677b"); // vents
  const amber = await box([0.12, 1.55, 0.07], [-0.9, 0.65, -0.98], AMBER, "#5a3a06");  // Trana side
  const cyan = await box([0.12, 1.55, 0.07], [0.9, 0.65, -0.98], CYAN, "#064a58");     // Twinton side
  await box([1.85, 0.08, 0.08], [0, 1.45, -0.98], "#c7d3df");           // the bridge between them
  const packet = await box([0.16, 0.16, 0.16], [-0.8, 1.41, -0.86], "#ffffff", "#5f6b78");
  const beacon = await box([0.3, 0.3, 0.3], [0, 2.75, 0], GREEN, "#145a32");
  await box([0.12, 5.2, 0.12], [1.05, 2.4, 0.4], "#8fa3b8");            // mast
  await box([1.3, 0.07, 0.07], [1.05, 4.7, 0.4], "#8fa3b8");            // crossbar
  await box([0.55, 0.06, 0.55], [1.05, 5.05, 0.4], "#b7c4d2");          // top plate
  ctx.ring(LAT, LON, 0.000025, CYAN, 3.2);

  // twelve two-hour buckets, one per bar; height carries the count, colour carries the same count
  const bars = [];
  for (let i = 0; i < 12; i++) bars.push(await box([0.18, 1, 0.18], [-1.35 + i * 0.245, 0.3, -1.18], "#25404a"));
  const inc = (v) => (v <= 0 ? 0.2 : 0.6 + Math.min(2.6, v * 0.55));

  // ---------------------------------------------------------------- data state
  const S = { feed: null, layer: null, world: null, bridge: null, feedSource: "—", feedAt: null, drawn: false, lastRead: 0, lastOk: 0, busy: false, error: "", layerState: "connecting", rhythm: null, lastPanel: 0 };
  const now = () => Date.now();
  const fmtAge = (s) => {
    if (s == null || !isFinite(s)) return "—";
    s = Math.max(0, Math.round(s));
    if (s < 90) return s + " s";
    if (s < 5400) return Math.round(s / 60) + " min";
    return (s / 3600).toFixed(1) + " h";
  };
  const cut = (s, n) => (s == null ? "" : (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s)));

  function rhythm(posts) {
    const t = posts.map((p) => +p.at_ms).filter((x) => x > 0).sort((a, b) => a - b);
    const gaps = [];
    for (let i = 1; i < t.length; i++) { const d = (t[i] - t[i - 1]) / 1000; if (d > 30) gaps.push(d); }
    const last = gaps.slice(-12);
    if (!last.length) return { ema: null, mae: null, n: 0, next: null };
    let ema = last[0];
    const errs = [];
    // walk the same EMA the panel shows: each gap is predicted by the EMA of the gaps before it,
    // then the EMA is updated with that gap. The MAE therefore belongs to the displayed model.
    for (let i = 1; i < last.length; i++) {
      errs.push(Math.abs(last[i] - ema));
      ema = ema * 0.7 + last[i] * 0.3;
    }
    const mae = errs.length ? errs.reduce((a, b) => a + b, 0) / errs.length : null;
    return { ema, mae, n: last.length, next: t[t.length - 1] + ema * 1000 };
  }

  function buckets(posts) {
    const nowMs = now(), out = new Array(12).fill(0);
    for (const p of posts) {
      const at = +p.at_ms; if (!at) continue;
      const k = Math.floor((nowMs - at) / 7_200_000);
      if (k >= 0 && k < 12) out[11 - k]++;
    }
    return out;
  }

  function setBars(counts) {
    for (let i = 0; i < bars.length; i++) {
      const h = inc(counts[i]);
      const c = counts[i] === 0 ? "#25404a" : counts[i] < 3 ? "#2f7b8c" : CYAN;
      ctx.set(bars[i], { at: [-1.35 + i * 0.245, 0.3 + h / 2, -1.18], scale: [1, h, 1], color: c });
    }
  }

  function drawWorld(world) {
    if (S.drawn || !world || !Array.isArray(world.subjects)) return;
    const placed = world.subjects.filter((s) => Number.isFinite(s.lat) && Number.isFinite(s.lon));
    if (!placed.length) return;
    const ink = (n) => (n >= 10 ? "#7cf0c0" : n >= 6 ? "#5fc8f0" : "#a9b8ff");
    ctx.points(placed.map((s) => [s.lat, s.lon, 3 + Math.min(6, s.lessons || 0), ink(s.lessons || 0)]));
    for (const s of placed) {
      if (Math.abs(s.lat - LAT) < 0.01 && Math.abs(s.lon - LON) < 0.01) continue;
      ctx.arc([LAT, LON], [s.lat, s.lon], s.lessons >= 10 ? "#7cf0c0" : CYAN, 0.28);
    }
    S.drawn = true;
  }

  function panel() {
    const feed = S.feed, posts = (feed?.posts || []).filter((p) => p.title);
    posts.sort((a, b) => (+b.at_ms || 0) - (+a.at_ms || 0));
    const latest = posts[0] || null;
    const post = posts.find((p) => String(p.title || "").startsWith(POST_PREFIX)) || null;
    const post24 = posts.filter((p) => now() - (+p.at_ms || 0) < 86_400_000).length;
    const rh = S.rhythm || { ema: null, mae: null, n: 0 };
    const placed = (S.world?.subjects || []).filter((s) => Number.isFinite(s.lat));
    const b = S.bridge;
    const bridgeState = b?.link?.state || "no bridge";
    const beatAge = b?.heartbeat?.updated ? now() / 1000 - b.heartbeat.updated : null;
    const feedAge = S.feedAt ? now() / 1000 - S.feedAt : null;
    const feedState = feedAge == null ? "unknown" : feedAge <= 900 ? "fresh" : feedAge <= 3600 ? "lagging" : "stale";
    const layerAge = S.layer?.at_s ? now() / 1000 - S.layer.at_s : null;
    const link = post ? "found · " + String(post.thread || "").split("/").pop()
      : b?.thread ? "bridge only · " + String(b.thread).split("/").pop()
      : "not in the feed";
    const colour = S.error || bridgeState === "broken" ? RED
      : bridgeState === "stale" || (beatAge != null && beatAge > 1800) || feedState === "stale" ? AMBER
      : bridgeState === "no bridge" ? AMBER
      : feedState === "fresh" ? GREEN : AMBER;
    ctx.set(beacon, { color: colour });
    ctx.set(amber, { color: post || b?.thread ? AMBER : "#6b4a16" });
    ctx.set(cyan, { color: S.error ? "#4a5a66" : CYAN });
    ctx.panel({
      title: "Trana-Twinton relay",
      sub: "The link is the twin: a small cabinet reads Trana's public layer every 60 s, and looks up the announcement that names it.",
      rows: [
        ["Link", link],
        ["Heartbeat", b ? bridgeState + " · " + fmtAge(beatAge) + " old" : "no bridge yet"],
        ["Feed", S.feedSource + " · " + feedState],
        ["Feed age", fmtAge(feedAge)],
        ["Public layer", S.layerState + (layerAge == null ? "" : " · " + fmtAge(layerAge))],
        ["Latest", latest ? cut(latest.title, 46) : "—"],
        ["Posts 24 h", String(post24)],
        ["Rhythm (EMA)", rh.ema == null ? "—" : fmtAge(rh.ema) + " between posts"],
        ["Backtest MAE (EMA)", rh.mae == null ? "—" : "±" + fmtAge(rh.mae) + " on " + Math.max(0, rh.n - 1) + " gaps"],
        ["Subjects", placed.length + " placed / " + (S.world?.subjects?.length || 0)],
      ],
      actions: [
        { label: "Read now", onClick: () => load() },
        { label: "Close-up", onClick: () => ctx.orbit(LAT, LON, 70, { heading: 25, tilt: 26 }) },
        { label: "Whole link", onClick: () => ctx.fly(LAT, LON, 1.7, 1800) },
      ],
      source: "Sources: trana.feed/2 and trana.world/2, read with CORS every 60 s; feed.json is a mirror written by the heartbeat when the public layer lags; the bridge is a public heartbeat (GitHub Action). Cabinet is schematic; bars are 2 h post counts, arcs are links to named places, not cables. Packet motion illustrates the modelled posting rhythm; it is not real traffic. Announcement: " + POST_PREFIX + " · " + TWIN_URL,
    });
  }

  async function load() {
    if (S.busy) return;
    S.busy = true; S.lastRead = now();
    try {
      const [layer, world, bridge, mirror] = await Promise.all([
        ctx.data(FEED).catch(() => null),
        ctx.data(WORLD).catch(() => null),
        ctx.data(BRIDGE).catch(() => null),
        ctx.data(MIRROR).catch(() => null),
      ]);
      if (layer && Array.isArray(layer.posts)) {
        S.layer = layer;
        const age = layer.at_s ? (now() - layer.at_s * 1000) / 1000 : null;
        S.layerState = age == null ? "unknown" : age <= 900 ? "fresh" : age <= 3600 ? "lagging" : "stale";
      }
      let feed = null, source = "—", at = null;
      if (mirror && Array.isArray(mirror.posts) && mirror.posts.length) {
        feed = mirror; source = "mirror"; at = mirror.read_at || mirror.at_s || null;
      } else if (layer && Array.isArray(layer.posts)) {
        feed = layer; source = "public layer"; at = layer.at_s || null;
      }
      if (feed) {
        S.feed = feed; S.feedSource = source; S.feedAt = at; S.error = ""; S.lastOk = now();
        setBars(buckets(feed.posts));
        S.rhythm = rhythm(feed.posts.filter((p) => p.title));
      } else if (!S.feed) {
        S.error = "Trana feed unreachable";
        S.layerState = "offline";
      } else {
        S.error = "Trana feed unreachable; last read kept";
      }
      if (world && Array.isArray(world.subjects)) { S.world = world; drawWorld(world); }
      if (bridge && bridge.schema === "twinton.trana/1") S.bridge = bridge;
    } catch (e) {
      S.error = "read failed: " + (e && e.message ? e.message : "unknown");
    } finally {
      S.busy = false;
      panel();
    }
  }

  // the packet crosses the bridge at the modelled rhythm, one pass per gap (clamped so it stays watchable)
  ctx.every(() => {
    const t = now() / 1000;
    const period = S.rhythm?.ema ? Math.max(4, Math.min(60, S.rhythm.ema / 2)) : 12;
    const x = 0.82 * Math.sin((t / period) * Math.PI * 2);
    ctx.set(packet, { at: [x, 1.41, -0.86] });
    if (now() - S.lastPanel > 10_000) { S.lastPanel = now(); panel(); }
    if (now() - S.lastRead > READ_MS && now() - S.lastOk > 20_000) load();
  });

  await load();
  ctx.steps([
    { title: "A relay, not a factory", text: "The cabinet is at ce-net's home in Umea. It is a schematic of the link; the panel is the instrument.", at: [LAT, LON, 160], view: { heading: 25, tilt: 28 } },
    { title: "The layer is the wire", text: "Every 60 s the twin reads Trana's public layer. Green means fresh, amber means lagging, red means stale or unreachable.", at: [LAT, LON, 70], view: { heading: 25, tilt: 26 } },
    { title: "The link is two-way", text: "The announcement names this twin; the twin finds the announcement in the layer. If either side loses the other, the panel says so.", at: [LAT, LON, 12000000] },
  ]);
  ctx.orbit(LAT, LON, 130, { heading: 25, tilt: 28, min: 30 });
}
