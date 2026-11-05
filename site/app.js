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
  const { ScatterplotLayer, TextLayer, LineLayer } = deck_gl();
  const shown = state.papers.filter(visible);
  $("count").textContent = `${shown.length} of ${state.papers.length} papers`;
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
      getLineWidth: (p) => (p.id === state.selected ? 2.5 : 0.4),
      getLineColor: (p) => (p.id === state.selected ? [20, 20, 20, 255] : [255, 255, 255, 120]),
      updateTriggers: { getRadius: state.sizeBy, getLineWidth: state.selected, getLineColor: state.selected },
      onHover: ({ object, x, y }) => tooltip(object, x, y),
      onClick: ({ object }) => object && select(object.id),
    }),
    new TextLayer({
      id: "labels",
      data: [...state.topics.values()].filter((t) => !state.hiddenTopics.has(t.id)),
      getPosition: (t) => [t.x * WORLD, (1 - t.y) * WORLD],
      getText: (t) => t.short,
      getSize: 12,
      getColor: (t) => [...t.rgb.map((c) => Math.round(c * 0.6)), 230],
      fontWeight: 700,
      fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
      outlineWidth: 3,
      outlineColor: [255, 255, 255, 200],
      fontSettings: { sdf: true },
      characterSet: "auto",
      getTextAnchor: "middle",
      getAlignmentBaseline: "center",
    }),
  ];
  deck.setProps({ layers });
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
    render();
    return;
  }
  const topic = state.topics.get(p.topic);
  $("d-id").textContent = p.id + (p.series === "euro" ? " (European symposium)" : "");
  $("d-year").textContent = p.year;
  $("d-topic").textContent = topic.label;
  $("d-topic").style.background = css(topic.rgb);
  $("d-title").textContent = p.title;
  $("d-authors").textContent = p.authors.join(", ") || "Authors not extracted";
  $("d-pdf").href = p.url;
  const rank = state.rankOf.get(p.id);
  $("d-scores").textContent = `cited ${p.cited_by}× in corpus · PageRank #${rank}`;
  const fig = $("d-figure");
  fig.hidden = !p.figure;
  if (p.figure) {
    $("d-img").src = p.figure;
    $("d-caption").textContent = p.caption || "";
  }
  $("d-abstract-wrap").hidden = !p.abstract;
  $("d-abstract").textContent = p.abstract || "";
  fillLinks("d-cited", p.cited);
  fillLinks("d-cites", p.cites);
  panel.hidden = false;
  panel.scrollTop = 0;
  render();
}

function fillLinks(listId, ids) {
  const items = ids.map((i) => state.byId.get(i)).filter(Boolean).sort((a, b) => b.year - a.year);
  $(`${listId}-wrap`).hidden = !items.length;
  $(listId).replaceChildren(...items.map((q) => paperItem(q, () => focus(q.id))));
}

function focus(id) {
  const p = state.byId.get(id);
  if (!p) return;
  select(id);
  deck.setProps({
    initialViewState: {
      target: [p.x * WORLD, (1 - p.y) * WORLD, 0],
      zoom: Math.max(state.view?.zoom ?? 0, 1.2),
      transitionDuration: 500,
    },
  });
}

function buildTopicList() {
  const ul = $("topics");
  const sorted = [...state.topics.values()].sort((a, b) => b.size - a.size);
  ul.replaceChildren(
    ...sorted.map((t) => {
      const li = document.createElement("li");
      li.title = t.keywords.join(", ");
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
  for (const el of [$("year-min"), $("year-max")]) Object.assign(el, { min: lo, max: hi, step: 1 });
  $("year-min").value = state.yearMin = lo;
  $("year-max").value = state.yearMax = hi;
  const update = () => {
    let a = +$("year-min").value;
    let b = +$("year-max").value;
    if (a > b) [a, b] = [b, a];
    state.yearMin = a;
    state.yearMax = b;
    $("year-label").textContent = `${a}–${b}`;
    render();
  };
  $("year-min").addEventListener("input", update);
  $("year-max").addEventListener("input", update);
  $("year-label").textContent = `${lo}–${hi}`;
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
  if (!q) {
    state.matches = null;
    list.replaceChildren();
    render();
    return;
  }
  const hits = search.search(q);
  state.matches = new Set(hits.map((h) => h.id));
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
  deck = new window.deck.Deck({
    parent: $("map"),
    views: new window.deck.OrthographicView({ flipY: false }),
    initialViewState: { target: [WORLD / 2, WORLD / 2, 0], zoom, minZoom: zoom - 1, maxZoom: 6 },
    controller: { doubleClickZoom: true },
    onViewStateChange: ({ viewState }) => {
      state.view = viewState;
      return viewState;
    },
    getCursor: ({ isHovering }) => (isHovering ? "pointer" : "grab"),
    layers: [],
  });

  buildTopicList();
  setupYears();
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
  document.addEventListener("keydown", (e) => e.key === "Escape" && select(null));
  window.addEventListener("hashchange", () => focus(location.hash.slice(1)));
  render();
  if (location.hash.length > 1) focus(decodeURIComponent(location.hash.slice(1)));
}

main().catch((err) => {
  $("count").textContent = `Failed to load data: ${err.message}`;
});
