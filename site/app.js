// SCA Papers Explorer: plain JS, no build step.
// Data: data/papers.json + data/topics.json (from `just site-data`), figures lazy-loaded.
// All paper text comes from PDFs (untrusted): it only ever goes into the DOM via textContent.
"use strict";

const WORLD = 1000; // map coordinates are [0, 1] -> [0, WORLD]
const $ = (id) => document.getElementById(id);

const state = {
  papers: [],
  byId: new Map(),
  topics: new Map(),
  hiddenTopics: new Set(),
  yearMin: 0,
  yearMax: 0,
  sizeBy: "pagerank",
  matches: null, // Set of ids matching the search, or null
  selected: null,
  hover: null,
  view: "list", // "list" | "map"
  sort: "newest",
  hitRank: null, // Map id -> search rank, or null
};
let deck;
let search;

function topicColor(index) {
  // Evenly spaced hues, alternating lightness so neighbours stay distinguishable.
  const h = (index * 360 * 0.618033) % 360;
  const l = index % 2 ? 58 : 46;
  return hslToRgb(h, 62, l);
}

function hslToRgb(h, s, l) {
  s /= 100; l /= 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}

const css = (rgb) => `rgb(${rgb.join(",")})`;

function visible(p) {
  return (
    !state.hiddenTopics.has(p.topic) &&
    p.year >= state.yearMin &&
    p.year <= state.yearMax &&
    (!state.matches || state.matches.has(p.id))
  );
}

function radius(p) {
  if (state.sizeBy === "uniform") return 3.5;
  const v = state.sizeBy === "pagerank" ? p.pagerank - 0.5 : p.cited_by;
  return 2.5 + 2.2 * Math.sqrt(Math.max(0, v));
}

function render() {
  const shown = state.papers.filter(visible);
  $("count").textContent = `${shown.length} of ${state.papers.length} papers`;
  document.body.classList.toggle("has-detail", !!state.selected);
  renderList(shown);
  renderMap(shown);
}

function renderMap(shown) {
  if (!deck) return;
  const { ScatterplotLayer, LineLayer } = deck_gl();
  const sel = state.selected && state.byId.get(state.selected);
  const links = sel
    ? [...sel.cites.map((t) => [sel, t]), ...sel.cited.map((s) => [s, sel.id])]
        .map(([a, b]) => [typeof a === "string" ? state.byId.get(a) : a, state.byId.get(b)])
        .filter(([a, b]) => a && b)
    : [];
  const layers = [
    new ScatterplotLayer({
      id: "faded",
      data: state.papers.filter((p) => !visible(p)),
      getPosition: (p) => [p.x * WORLD, (1 - p.y) * WORLD],
      getRadius: 2,
      radiusUnits: "pixels",
      getFillColor: [128, 128, 128, 40],
    }),
    new LineLayer({
      id: "links",
      data: links,
      getSourcePosition: ([a]) => [a.x * WORLD, (1 - a.y) * WORLD],
      getTargetPosition: ([, b]) => [b.x * WORLD, (1 - b.y) * WORLD],
      getColor: ([a]) => (a.id === state.selected ? [36, 99, 199, 160] : [220, 120, 30, 160]),
      getWidth: 1.2,
    }),
    new ScatterplotLayer({
      id: "papers",
      data: shown,
      pickable: true,
      getPosition: (p) => [p.x * WORLD, (1 - p.y) * WORLD],
      getRadius: radius,
      radiusUnits: "pixels",
      getFillColor: (p) => [...state.topics.get(p.topic).rgb, p.outlier ? 150 : 215],
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: 0.4,
      getLineColor: [255, 255, 255, 120],
      updateTriggers: { getRadius: state.sizeBy },
      onHover: ({ object, x, y }) => tooltip(object, x, y),
      onClick: ({ object }) => object && select(object.id),
    }),
    // Selection marker: an accent ring with a halo so it shows on light and dark maps.
    new ScatterplotLayer({
      id: "selected",
      data: sel ? [sel, sel] : [],
      getPosition: (p) => [p.x * WORLD, (1 - p.y) * WORLD],
      getRadius: (p) => radius(p) + 6,
      radiusUnits: "pixels",
      filled: false,
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: (_, { index }) => (index ? 2.5 : 6),
      getLineColor: (_, { index }) => (index ? labelTheme().accent : [...labelTheme().pill.slice(0, 3), 200]),
      updateTriggers: { getRadius: state.sizeBy, getLineColor: labelTheme().key },
    }),
  ];
  state.baseLayers = layers;
  state.labelKey = null;
  updateLabels(true);
}

const LABEL_FONT = "600 14px system-ui, -apple-system, Segoe UI, sans-serif";
const LABEL_GAP = 4; // px between label pills

// Pill size in pixels (text + padding + border), measured once per label.
function labelBox(t) {
  if (!t.box) {
    const ctx = (labelBox.ctx ||= document.createElement("canvas").getContext("2d"));
    ctx.font = LABEL_FONT;
    t.box = [ctx.measureText(t.short).width + 15, 23];
  }
  return t.box;
}

// Greedy placement: biggest topics first, skip any label that would overlap
// one already placed at this zoom. Zooming in spreads them out and reveals more.
function placeLabels(zoom) {
  const scale = 2 ** zoom; // world units -> pixels
  const placed = [];
  const topics = [...state.topics.values()]
    .filter((t) => !state.hiddenTopics.has(t.id))
    .sort((a, b) => b.size - a.size);
  for (const t of topics) {
    const [w, h] = labelBox(t);
    const cx = t.x * WORLD * scale, cy = (1 - t.y) * WORLD * scale;
    const r = [cx - w / 2 - LABEL_GAP, cy - h / 2 - LABEL_GAP, cx + w / 2 + LABEL_GAP, cy + h / 2 + LABEL_GAP];
    if (placed.some(({ r: q }) => r[0] < q[2] && q[0] < r[2] && r[1] < q[3] && q[1] < r[3])) continue;
    placed.push({ t, r });
  }
  return placed.map(({ t }) => t);
}

function updateLabels(force = false) {
  if (!state.baseLayers) return;
  const data = placeLabels(state.mapView?.zoom ?? state.zoom);
  const key = data.map((t) => t.id).join(",");
  if (!force && key === state.labelKey) return;
  state.labelKey = key;
  const theme = labelTheme();
  const labels = new window.deck.TextLayer({
    id: "labels",
    data,
    getPosition: (t) => [t.x * WORLD, (1 - t.y) * WORLD],
    getText: (t) => t.short,
    getSize: 14,
    getColor: theme.text,
    fontWeight: 600,
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
    characterSet: "auto",
    getTextAnchor: "middle",
    getAlignmentBaseline: "center",
    // Opaque pill with a topic-coloured border: readable over dense points.
    background: true,
    getBackgroundColor: theme.pill,
    getBorderColor: (t) => [...t.rgb, 255],
    getBorderWidth: 1.5,
    backgroundPadding: [6, 3],
    backgroundBorderRadius: 4,
    updateTriggers: { getColor: theme.key, getBackgroundColor: theme.key },
  });
  deck.setProps({ layers: [...state.baseLayers, labels] });
}

function labelTheme() {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  return dark
    ? { key: "dark", text: [235, 235, 238, 255], pill: [24, 25, 30, 225], accent: [122, 167, 255, 255] }
    : { key: "light", text: [29, 29, 31, 255], pill: [255, 255, 255, 230], accent: [36, 99, 199, 255] };
}

function deck_gl() {
  return window.deck;
}

function tooltip(p, x, y) {
  const el = $("tooltip");
  if (!p) {
    el.hidden = true;
    return;
  }
  el.replaceChildren();
  const b = document.createElement("b");
  b.textContent = p.title;
  const s = document.createElement("div");
  s.className = "muted";
  s.textContent = `${p.year} · ${p.authors.slice(0, 3).join(", ")}${p.authors.length > 3 ? " et al." : ""}`;
  el.append(b, s);
  const box = $("map").getBoundingClientRect(); // x, y are relative to the map
  el.style.left = `${box.left + x + 14}px`;
  el.style.top = `${box.top + y + 14}px`;
  el.hidden = false;
}

function paperItem(p, onClick) {
  const li = document.createElement("li");
  li.textContent = p.title;
  const small = document.createElement("small");
  small.textContent = ` ${p.year} · ${p.authors[0] || p.id}`;
  li.append(small);
  li.addEventListener("click", onClick);
  return li;
}

function select(id) {
  const p = state.byId.get(id);
  state.selected = p ? id : null;
  if (location.hash.slice(1) !== (p ? id : "")) history.replaceState(null, "", p ? `#${id}` : location.pathname);
  const panel = $("detail");
  if (!p) {
    panel.hidden = true;
    refreshSelection();
    return;
  }
  const topic = state.topics.get(p.topic);
  $("d-id").textContent = p.id + (p.series === "euro" ? " · European symposium" : "");
  $("d-year").textContent = p.year;
  $("d-topic").textContent = topic.label;
  $("d-topic").style.background = css(topic.rgb);
  $("d-title").textContent = p.title;
  $("d-authors").textContent = p.authors.join(", ") || "Authors not extracted";
  $("d-pdf").href = p.url;
  $("d-cited-n").textContent = p.cited.length;
  $("d-cites-n").textContent = p.cites.length;
  $("d-rank").textContent = `#${state.rankOf.get(p.id)}`;
  $("d-rank").title = `of ${state.papers.length} papers, by PageRank on the in-corpus citation graph`;
  const fig = $("d-figure");
  fig.hidden = !p.figure;
  if (p.figure) {
    $("d-img").src = p.figure;
    $("d-caption").textContent = p.caption || "";
  }
  $("d-abstract-wrap").hidden = !p.abstract;
  $("d-abstract").textContent = p.abstract || "";
  $("n-similar").textContent = p.similar.length;
  $("n-cited").textContent = p.cited.length;
  $("n-cites").textContent = p.cites.length;
  showRelated();
  panel.hidden = false;
  panel.querySelector(".d-body").scrollTop = 0;
  refreshSelection();
}

// Selection changes don't refilter anything: update the map and card highlight
// without rebuilding the list (which would lose its scroll position).
function refreshSelection() {
  document.body.classList.toggle("has-detail", !!state.selected);
  markSelectedCard();
  renderMap(state.papers.filter(visible));
}

const RELATED_EMPTY = {
  similar: "No similar papers.",
  cited: "Not cited by other papers in this corpus (as far as the reference matching can tell).",
  cites: "No references matched to papers in this corpus.",
};

function showRelated(tab = state.tab || "similar") {
  state.tab = tab;
  for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", b.dataset.tab === tab);
  const p = state.byId.get(state.selected);
  if (!p) return;
  let items = p[tab].map((i) => state.byId.get(i)).filter(Boolean);
  if (tab !== "similar") items = items.sort((a, b) => b.year - a.year); // similar stays in rank order
  $("d-related").replaceChildren(...items.map(relatedCard));
  $("d-related-empty").hidden = items.length > 0;
  $("d-related-empty").textContent = RELATED_EMPTY[tab];
}

function relatedCard(q) {
  const li = document.createElement("li");
  li.tabIndex = 0;
  const t = document.createElement("span");
  t.className = "t";
  t.textContent = q.title;
  const m = document.createElement("span");
  m.className = "m";
  const dot = document.createElement("span");
  dot.className = "dot";
  dot.style.background = css(state.topics.get(q.topic).rgb);
  const who = q.authors.length ? q.authors[0].split(" ").at(-1) + (q.authors.length > 1 ? " et al." : "") : q.id;
  m.append(dot, `${q.year} · ${who}` + (q.cited_by ? ` · cited ${q.cited_by}×` : ""));
  li.append(t, m);
  li.addEventListener("click", () => focus(q.id));
  li.addEventListener("keydown", (e) => e.key === "Enter" && focus(q.id));
  return li;
}

function setWide(on) {
  $("detail").classList.toggle("wide", on);
  $("wide").setAttribute("aria-pressed", on);
  try {
    localStorage.setItem("wide", on ? "1" : "");
  } catch {}
}

function focus(id) {
  const p = state.byId.get(id);
  if (!p) return;
  select(id);
  scrollListTo(id);
  const zoom = Math.max(state.mapView?.zoom ?? 0, 1.2);
  deck.setProps({
    initialViewState: {
      target: [p.x * WORLD, (1 - p.y) * WORLD, 0],
      zoom,
      transitionDuration: 500,
    },
  });
}

// ---- List view -------------------------------------------------------------

const PAGE = 60; // cards rendered per batch; more are appended on scroll

const SORTS = {
  relevance: (a, b) => state.hitRank.get(a.id) - state.hitRank.get(b.id),
  newest: (a, b) => b.year - a.year || a.id.localeCompare(b.id),
  oldest: (a, b) => a.year - b.year || a.id.localeCompare(b.id),
  cited: (a, b) => b.cited_by - a.cited_by || b.pagerank - a.pagerank,
  pagerank: (a, b) => b.pagerank - a.pagerank,
};

function renderList(shown) {
  const sort = state.sort === "relevance" && !state.hitRank ? "newest" : state.sort;
  state.listItems = [...shown].sort(SORTS[sort]);
  state.listShown = 0;
  state.listSort = sort;
  $("list").replaceChildren();
  $("list-count").textContent = state.matches
    ? `${shown.length} matching paper${shown.length === 1 ? "" : "s"}`
    : `${shown.length} papers`;
  appendCards();
}

function appendCards(upTo = state.listShown + PAGE) {
  const items = state.listItems, list = $("list");
  const byYear = state.listSort === "newest" || state.listSort === "oldest";
  const frag = document.createDocumentFragment();
  for (let i = state.listShown; i < Math.min(upTo, items.length); i++) {
    const p = items[i];
    if (byYear && (i === 0 || items[i - 1].year !== p.year)) {
      const h = document.createElement("li");
      h.className = "year-head";
      h.textContent = p.year;
      frag.append(h);
    }
    frag.append(card(p));
  }
  state.listShown = Math.min(upTo, items.length);
  list.append(frag);
  const left = items.length - state.listShown;
  $("list-more").textContent = left > 0 ? `Scroll for ${left} more…` : items.length ? "" : "No papers match the filters.";
}

function card(p) {
  const li = document.createElement("li");
  li.className = "card" + (p.id === state.selected ? " on" : "");
  li.dataset.id = p.id;
  li.tabIndex = 0;
  const body = document.createElement("div");
  const meta = document.createElement("div");
  meta.className = "c-meta";
  const topic = state.topics.get(p.topic);
  const dot = document.createElement("span");
  dot.className = "dot";
  dot.style.background = css(topic.rgb);
  const metaText = document.createElement("span");
  metaText.textContent = `${topic.short} · ${p.year} · ${p.id}`;
  meta.append(dot, metaText);
  const h = document.createElement("h3");
  h.textContent = p.title;
  const au = document.createElement("p");
  au.className = "c-authors";
  au.textContent = p.authors.join(", ") || "Authors not extracted";
  body.append(meta, h, au);
  if (p.abstract) {
    const ab = document.createElement("p");
    ab.className = "c-abs";
    ab.textContent = p.abstract;
    body.append(ab);
  }
  if (p.cited_by) {
    const foot = document.createElement("div");
    foot.className = "c-foot";
    foot.textContent = `Cited by ${p.cited_by} in this corpus`;
    body.append(foot);
  }
  li.append(body);
  if (p.figure) {
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "";
    img.src = p.figure;
    li.append(img);
  }
  return li;
}

function scrollListTo(id) {
  if (state.view !== "list") return;
  let el = $("list").querySelector(`[data-id="${CSS.escape(id)}"]`);
  if (!el) {
    const i = state.listItems.findIndex((p) => p.id === id);
    if (i < 0) return;
    appendCards(i + PAGE);
    el = $("list").querySelector(`[data-id="${CSS.escape(id)}"]`);
  }
  el?.scrollIntoView({ block: "nearest" });
}

function markSelectedCard() {
  for (const el of $("list").querySelectorAll(".card.on")) el.classList.remove("on");
  if (state.selected) $("list").querySelector(`[data-id="${CSS.escape(state.selected)}"]`)?.classList.add("on");
}

function setupList() {
  const list = $("list");
  const open = (e) => {
    const el = e.target.closest(".card");
    if (el) select(el.dataset.id);
  };
  list.addEventListener("click", open);
  list.addEventListener("keydown", (e) => e.key === "Enter" && open(e));
  $("list-view").addEventListener("scroll", (e) => {
    const v = e.target;
    if (v.scrollTop + v.clientHeight > v.scrollHeight - 800 && state.listShown < state.listItems.length) appendCards();
  });
  $("sort").addEventListener("change", (e) => {
    state.sort = e.target.value;
    $("list-view").scrollTop = 0;
    render();
  });
}

function setView(view) {
  state.view = view;
  document.body.classList.toggle("map", view === "map");
  $("list-view").hidden = view !== "list";
  $("map-view").hidden = view !== "map";
  for (const b of document.querySelectorAll(".views button")) b.setAttribute("aria-selected", b.dataset.view === view);
  if (view === "list" && state.selected) scrollListTo(state.selected);
  try {
    localStorage.setItem("view", view);
  } catch {}
}

// ---- Resizable sidebars -------------------------------------------------------

const WIDTHS = { left: [310, 220, 480], right: [560, 360, 1100] }; // default, min, max

function setWidth(side, px) {
  const [, min, max] = WIDTHS[side];
  const room = innerWidth - (side === "left" ? state.widths.right : state.widths.left) - 320;
  state.widths[side] = Math.round(Math.max(min, Math.min(px, max, room)));
  document.documentElement.style.setProperty(`--${side}-w`, `${state.widths[side]}px`);
}

function setupResizers() {
  state.widths = { left: WIDTHS.left[0], right: WIDTHS.right[0] };
  try {
    const saved = JSON.parse(localStorage.getItem("widths") || "{}");
    for (const side of ["left", "right"]) if (saved[side]) state.widths[side] = saved[side];
  } catch {}
  for (const side of ["left", "right"]) setWidth(side, state.widths[side]);
  const save = () => {
    try {
      localStorage.setItem("widths", JSON.stringify(state.widths));
    } catch {}
  };
  for (const el of document.querySelectorAll(".resizer")) {
    const side = el.dataset.side;
    el.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      el.setPointerCapture(e.pointerId);
      document.body.classList.add("resizing");
      const move = (ev) => setWidth(side, side === "left" ? ev.clientX - 12 : innerWidth - 12 - ev.clientX);
      const up = () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        document.body.classList.remove("resizing");
        save();
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
    });
    el.addEventListener("dblclick", () => {
      setWidth(side, WIDTHS[side][0]);
      save();
    });
  }
  addEventListener("resize", () => ["left", "right"].forEach((side) => setWidth(side, state.widths[side])));
}

function buildTopicList() {
  const ul = $("topics");
  const sorted = [...state.topics.values()].sort((a, b) => b.size - a.size);
  ul.replaceChildren(
    ...sorted.map((t) => {
      const li = document.createElement("li");
      li.title = `${t.keywords.join(", ")}\n\nClick to toggle, double-click to show only this topic`;
      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = css(t.rgb);
      const name = document.createElement("span");
      name.textContent = t.label;
      const n = document.createElement("span");
      n.className = "n";
      n.textContent = t.size;
      li.append(sw, name, n);
      li.addEventListener("click", (e) => {
        if (e.altKey || e.metaKey) {
          // alt/cmd-click: show only this topic
          state.hiddenTopics = new Set([...state.topics.keys()].filter((k) => k !== t.id));
        } else if (state.hiddenTopics.has(t.id)) state.hiddenTopics.delete(t.id);
        else state.hiddenTopics.add(t.id);
        syncTopicList();
        render();
      });
      // Double-click: show only this topic (the two clicks before it cancel out).
      // Double-clicking the only visible topic again shows all topics.
      li.addEventListener("dblclick", () => {
        const solo = state.hiddenTopics.size === state.topics.size - 1 && !state.hiddenTopics.has(t.id);
        state.hiddenTopics = solo ? new Set() : new Set([...state.topics.keys()].filter((k) => k !== t.id));
        syncTopicList();
        render();
      });
      t.li = li;
      return li;
    })
  );
}

function syncTopicList() {
  for (const t of state.topics.values()) t.li.classList.toggle("off", state.hiddenTopics.has(t.id));
}

function setupYears() {
  const years = state.papers.map((p) => p.year);
  const lo = Math.min(...years);
  const hi = Math.max(...years);
  const minEl = $("year-min"), maxEl = $("year-max");
  for (const el of [minEl, maxEl]) Object.assign(el, { min: lo, max: hi, step: 1, placeholder: "" });
  minEl.placeholder = lo;
  maxEl.placeholder = hi;
  minEl.value = state.yearMin = lo;
  maxEl.value = state.yearMax = hi;

  // Parse a box: empty means the default end; anything else must be a year in range.
  const read = (el, fallback) => {
    const v = el.value.trim();
    if (!v) return fallback;
    const n = Number(v);
    return Number.isInteger(n) && n >= lo && n <= hi ? n : null;
  };
  // Apply while typing once both boxes hold valid years (so "20" mid-typing doesn't filter).
  const apply = () => {
    const a = read(minEl, lo), b = read(maxEl, hi);
    minEl.classList.toggle("bad", a === null);
    maxEl.classList.toggle("bad", b === null);
    if (a === null || b === null) return;
    [state.yearMin, state.yearMax] = a <= b ? [a, b] : [b, a];
    $("years-reset").hidden = state.yearMin === lo && state.yearMax === hi;
    render();
  };
  // On leaving a box (or Enter), tidy up: fill empty/invalid boxes and order the pair.
  const settle = () => {
    apply();
    minEl.value = state.yearMin;
    maxEl.value = state.yearMax;
    minEl.classList.remove("bad");
    maxEl.classList.remove("bad");
  };
  for (const el of [minEl, maxEl]) {
    el.addEventListener("input", apply);
    el.addEventListener("change", settle);
    el.addEventListener("keydown", (e) => e.key === "Enter" && settle());
    el.addEventListener("focus", () => el.select());
  }
  $("years-reset").addEventListener("click", () => {
    minEl.value = lo;
    maxEl.value = hi;
    settle();
  });
}

function setupSearch() {
  search = new MiniSearch({
    fields: ["title", "authorText", "abstract", "id"],
    storeFields: [],
    searchOptions: {
      boost: { title: 3, authorText: 2, id: 3 },
      prefix: true,
      fuzzy: 0.15,
      combineWith: "AND",
    },
  });
  search.addAll(state.papers.map((p) => ({ ...p, authorText: p.authors.join(" "), abstract: p.abstract || "" })));
  let timer;
  $("search").addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(runSearch, 120);
  });
}

function runSearch() {
  const q = $("search").value.trim();
  const list = $("results");
  const sortEl = $("sort");
  if (!q) {
    state.matches = state.hitRank = null;
    sortEl.querySelector('[value="relevance"]').disabled = true;
    if (state.sort === "relevance") sortEl.value = state.sort = state.sortBeforeSearch || "newest";
    list.replaceChildren();
    render();
    return;
  }
  const hits = search.search(q);
  state.matches = new Set(hits.map((h) => h.id));
  state.hitRank = new Map(hits.map((h, i) => [h.id, i]));
  sortEl.querySelector('[value="relevance"]').disabled = false;
  if (state.sort !== "relevance") {
    state.sortBeforeSearch = state.sort;
    sortEl.value = state.sort = "relevance";
  }
  $("list-view").scrollTop = 0;
  list.replaceChildren(
    ...hits.slice(0, 40).map((h) => paperItem(state.byId.get(h.id), () => focus(h.id)))
  );
  if (hits.length > 40) {
    const more = document.createElement("li");
    more.className = "muted";
    more.textContent = `… ${hits.length - 40} more on the map`;
    list.append(more);
  }
  render();
}

async function main() {
  setupResizers(); // before measuring the map, so it starts at its final size
  const [papers, topics] = await Promise.all([
    fetch("data/papers.json").then((r) => r.json()),
    fetch("data/topics.json").then((r) => r.json()),
  ]);
  state.papers = papers;
  for (const p of papers) state.byId.set(p.id, p);
  const bySize = [...topics].sort((a, b) => b.size - a.size);
  bySize.forEach((t, i) => {
    t.rgb = topicColor(i);
    t.short = t.label.split(" / ").slice(0, 2).join(" / ");
    state.topics.set(t.id, t);
  });
  state.rankOf = new Map(
    [...papers].sort((a, b) => b.pagerank - a.pagerank).map((p, i) => [p.id, i + 1])
  );

  // Fit the map to the viewport. Pass everything at construction: calling
  // setProps before deck.gl has created its GPU device throws.
  const box = $("map").getBoundingClientRect();
  const zoom = Math.log2(Math.min(box.width, box.height) / (WORLD * 1.08));
  state.zoom = zoom;
  deck = new window.deck.Deck({
    parent: $("map"),
    views: new window.deck.OrthographicView({ flipY: false }),
    initialViewState: { target: [WORLD / 2, WORLD / 2, 0], zoom, minZoom: zoom - 1, maxZoom: 6 },
    controller: { doubleClickZoom: true },
    onViewStateChange: ({ viewState }) => {
      state.mapView = viewState;
      updateLabels();
      return viewState;
    },
    getCursor: ({ isHovering }) => (isHovering ? "pointer" : "grab"),
    layers: [],
  });

  buildTopicList();
  setupList();
  for (const b of document.querySelectorAll(".views button")) b.addEventListener("click", () => setView(b.dataset.view));
  try {
    setView(localStorage.getItem("view") === "map" ? "map" : "list");
  } catch {
    setView("list");
  }
  setupYears();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => render());
  setupSearch();
  $("size-by").addEventListener("change", (e) => {
    state.sizeBy = e.target.value;
    render();
  });
  $("topics-all").addEventListener("click", () => {
    state.hiddenTopics.clear();
    syncTopicList();
    render();
  });
  $("topics-none").addEventListener("click", () => {
    state.hiddenTopics = new Set(state.topics.keys());
    syncTopicList();
    render();
  });
  $("close").addEventListener("click", () => select(null));
  $("wide").addEventListener("click", () => setWide(!$("detail").classList.contains("wide")));
  try {
    setWide(localStorage.getItem("wide") === "1");
  } catch {}
  for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => showRelated(b.dataset.tab));
  $("d-topic").addEventListener("click", () => {
    const t = state.byId.get(state.selected)?.topic;
    if (t === undefined) return;
    state.hiddenTopics = new Set([...state.topics.keys()].filter((k) => k !== t));
    syncTopicList();
    render();
  });
  $("d-copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      $("d-copy").textContent = "Copied";
    } catch {
      $("d-copy").textContent = "Copy failed";
    }
    setTimeout(() => ($("d-copy").textContent = "Copy link"), 1500);
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select, textarea")) return;
    if (e.key === "Escape") select(null);
    else if (e.key === "r" && state.selected) setWide(!$("detail").classList.contains("wide"));
  });
  window.addEventListener("hashchange", () => focus(location.hash.slice(1)));
  render();
  if (location.hash.length > 1) focus(decodeURIComponent(location.hash.slice(1)));
}

main().catch((err) => {
  $("count").textContent = `Failed to load data: ${err.message}`;
});
