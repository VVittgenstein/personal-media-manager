const main = document.getElementById("main");

const API = {
  albums: "/api/albums",
  scattered: "/api/scattered",
  videos: "/api/videos",
  others: "/api/others",
  thumb: (relPath) => `/api/thumb?path=${encodeURIComponent(relPath)}`,
  albumCover: (relPath) => `/api/album-cover?path=${encodeURIComponent(relPath)}`,
  videoMosaic: (relPath) => `/api/video-mosaic?path=${encodeURIComponent(relPath)}`,
};

const CATEGORIES = [
  {
    key: "images",
    path: "/images",
    label: "Images",
    description: "按相册（Album）浏览图片。",
    meta: "Albums grid",
  },
  {
    key: "scattered",
    path: "/scattered",
    label: "Scattered",
    description: "扁平浏览未归档的散图。",
    meta: "Flat thumbnails",
  },
  {
    key: "videos",
    path: "/videos",
    label: "Videos",
    description: "扁平浏览全部视频文件。",
    meta: "Video cards",
  },
  {
    key: "games",
    path: "/games",
    label: "Games",
    description: "暂时占位（不提供执行入口）。",
    meta: "Placeholder",
  },
  {
    key: "others",
    path: "/others",
    label: "Others",
    description: "浏览非媒体类型的文件列表。",
    meta: "File list",
  },
];

const ROUTES = new Map([
  ["/", { title: "Home", render: (token) => renderHome(token) }],
  ...CATEGORIES.map((category) => [
    category.path,
    { title: category.label, render: (token) => renderCategory(category, token) },
  ]),
]);

const scrollPositions = new Map();
let renderEpoch = 0;
let lazyImageObserver = null;

if ("scrollRestoration" in history) {
  history.scrollRestoration = "manual";
}

function currentPathKey() {
  return `${location.pathname}${location.search}`;
}

function saveScrollPosition() {
  scrollPositions.set(currentPathKey(), window.scrollY);
  try {
    sessionStorage.setItem(`ppm.scroll:${currentPathKey()}`, String(window.scrollY));
  } catch {
    // ignore
  }
}

function loadScrollPosition() {
  const key = currentPathKey();
  if (scrollPositions.has(key)) {
    return scrollPositions.get(key) ?? 0;
  }
  try {
    const raw = sessionStorage.getItem(`ppm.scroll:${key}`);
    const y = raw ? Number.parseInt(raw, 10) : 0;
    return Number.isFinite(y) ? y : 0;
  } catch {
    return 0;
  }
}

function isSpaNavigableClick(event, anchor) {
  if (event.defaultPrevented) return false;
  if (event.button !== 0) return false;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
  if (anchor.target && anchor.target !== "_self") return false;

  const url = new URL(anchor.href);
  if (url.origin !== location.origin) return false;
  return anchor.hasAttribute("data-nav");
}

function navigate(to, { replace = false } = {}) {
  saveScrollPosition();
  const url = new URL(to, location.origin);
  const next = `${url.pathname}${url.search}`;
  if (replace) {
    history.replaceState({}, "", next);
  } else {
    history.pushState({}, "", next);
  }
  render();
}

function setActiveNav(pathname) {
  const navLinks = document.querySelectorAll("a[data-nav]");
  for (const link of navLinks) {
    const url = new URL(link.href);
    const isActive = url.pathname === pathname;
    if (isActive) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }
}

function render() {
  if (lazyImageObserver) {
    lazyImageObserver.disconnect();
  }

  const token = (renderEpoch += 1);
  const route = ROUTES.get(location.pathname);
  if (route) {
    route.render(token);
    document.title = `Personal Media Manager · ${route.title}`;
  } else {
    renderNotFound(token);
    document.title = "Personal Media Manager · Not Found";
  }

  setActiveNav(location.pathname);
  main.focus({ preventScroll: true });

  const y = loadScrollPosition();
  requestAnimationFrame(() => window.scrollTo(0, y));
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") {
      node.className = String(value);
      continue;
    }
    if (key === "text") {
      node.textContent = String(value);
      continue;
    }
    if (key === "html") {
      node.innerHTML = String(value);
      continue;
    }
    if (value === false || value === null || value === undefined) {
      continue;
    }
    node.setAttribute(key, String(value));
  }
  for (const child of children) {
    node.append(child);
  }
  return node;
}

function basename(relPath) {
  if (!relPath) return "";
  const parts = String(relPath).split("/");
  return parts[parts.length - 1] || "";
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "—";
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = n / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const digits = value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[unitIndex]}`;
}

function formatDateTime(ms) {
  if (ms === null || ms === undefined) return "—";
  const n = Number(ms);
  if (!Number.isFinite(n)) return "—";
  const date = new Date(n);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}

function shortenText(text, maxLen = 48) {
  const raw = String(text || "");
  if (raw.length <= maxLen) return raw;
  const head = Math.max(8, Math.floor(maxLen * 0.6));
  const tail = Math.max(8, maxLen - head - 1);
  return `${raw.slice(0, head)}…${raw.slice(-tail)}`;
}

function ensureLazyObserver() {
  if (!("IntersectionObserver" in window)) return null;
  if (lazyImageObserver) return lazyImageObserver;
  lazyImageObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const img = entry.target;
        const src = img.getAttribute("data-src");
        if (src) {
          img.src = src;
          img.removeAttribute("data-src");
        }
        lazyImageObserver.unobserve(img);
      }
    },
    { root: null, rootMargin: "360px 0px", threshold: 0.01 },
  );
  return lazyImageObserver;
}

function observeLazyImages(container) {
  const imgs = container.querySelectorAll("img[data-src]");
  if (!imgs.length) return;
  const observer = ensureLazyObserver();
  for (const img of imgs) {
    if (!observer) {
      const src = img.getAttribute("data-src");
      if (src) {
        img.src = src;
        img.removeAttribute("data-src");
      }
      continue;
    }
    observer.observe(img);
  }
}

function createLazyThumb({ src, alt, placeholder = "" } = {}) {
  const frame = el("div", { class: "thumb-frame" }, []);
  const placeholderEl = el("div", { class: "thumb-placeholder", text: placeholder }, []);
  const imgAttrs = { class: "thumb-img", alt: alt || "", loading: "lazy" };
  if (src) {
    imgAttrs["data-src"] = src;
  }
  const img = el("img", imgAttrs, []);
  img.addEventListener("load", () => frame.classList.add("is-loaded"));
  img.addEventListener("error", () => frame.classList.add("is-error"));
  frame.append(placeholderEl, img);
  return { frame, img };
}

async function fetchJson(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
  const contentType = res.headers.get("Content-Type") || "";
  const isJson = contentType.includes("application/json");
  let payload;
  try {
    payload = isJson ? await res.json() : await res.text();
  } catch {
    payload = null;
  }

  if (!res.ok) {
    const error = payload && typeof payload === "object" && payload.error ? payload.error : null;
    const message = error?.message || `Request failed: ${res.status}`;
    const code = error?.code || "REQUEST_FAILED";
    const err = new Error(message);
    err.code = code;
    err.status = res.status;
    err.payload = payload;
    throw err;
  }

  return payload;
}

function renderHome(_token) {
  const header = el("div", { class: "view-header" }, [
    el("div", {}, [
      el("div", { class: "breadcrumb", text: "Home" }),
      el("h1", { class: "title", text: "Choose a view" }),
      el("p", { class: "subtitle", text: "首页固定 5 个入口卡片；点击同页切换，支持前进/后退/刷新。 " }),
    ]),
  ]);

  const grid = el(
    "div",
    { class: "home-grid" },
    CATEGORIES.map((category) =>
      el("a", { class: "card card--link", href: category.path, "data-nav": "" }, [
        el("div", { class: "card__title", text: category.label }),
        el("div", { class: "card__desc", text: category.description }),
        el("div", { class: "card__meta" }, [el("span", { text: category.meta }), el("span", { text: "↗" })]),
      ]),
    ),
  );

  main.replaceChildren(header, grid);
}

function renderMetaBar({ badges = [], onRefresh, refreshLabel = "Refresh index" } = {}) {
  const badgeEls = badges.map((b) =>
    el("div", { class: "meta-badge", title: b.title || "" }, [
      el("div", { class: "meta-badge__label", text: b.label }),
      el("div", { class: "meta-badge__value", text: b.value }),
    ]),
  );
  const actions = el("div", { class: "view-actions" }, [
    el(
      "button",
      { class: "btn", type: "button" },
      [el("span", { text: refreshLabel })],
    ),
  ]);
  const button = actions.querySelector("button");
  button.addEventListener("click", () => onRefresh?.());

  return el("div", { class: "view-meta" }, [el("div", { class: "view-badges" }, badgeEls), actions]);
}

function renderErrorState(err, { onRetry } = {}) {
  const code = err?.code ? String(err.code) : "UNKNOWN";
  const msg = err?.message ? String(err.message) : "Unknown error";
  const detail = el("pre", { class: "error-detail", text: `${code}: ${msg}` }, []);
  const actions = el("div", { class: "error-actions" }, []);
  if (onRetry) {
    const btn = el("button", { class: "btn", type: "button" }, [el("span", { text: "Retry" })]);
    btn.addEventListener("click", () => onRetry());
    actions.append(btn);
  }
  return el("div", { class: "placeholder" }, [el("div", { text: "加载失败。" }), detail, actions]);
}

function renderEmptyState(message) {
  return el("div", { class: "placeholder" }, [el("div", { text: message })]);
}

function renderAlbumsGrid(albums) {
  if (!albums.length) return renderEmptyState("没有找到相册（Album）。");

  const grid = el(
    "div",
    { class: "albums-grid" },
    albums.map((album) => {
      const cover = createLazyThumb({
        src: API.albumCover(album.rel_path),
        alt: `${album.name} cover`,
        placeholder: "Cover",
      });
      const countBadge = el("div", { class: "thumb-count", text: `${album.image_count}` });
      cover.frame.append(countBadge);

      return el("div", { class: "album-card" }, [
        el("div", { class: "album-cover" }, [cover.frame]),
        el("div", { class: "album-title", text: album.name || album.title || album.rel_path }),
        el("div", { class: "album-subtitle", title: album.rel_path, text: shortenText(album.rel_path, 44) }),
      ]);
    }),
  );
  observeLazyImages(grid);
  return grid;
}

function renderThumbGrid(items) {
  if (!items.length) return renderEmptyState("没有找到散图。");
  const grid = el(
    "div",
    { class: "thumbs-grid" },
    items.map((item) => {
      const name = basename(item.rel_path) || item.rel_path;
      const thumb = createLazyThumb({ src: API.thumb(item.rel_path), alt: name });
      const caption = el("div", { class: "thumb-caption", title: item.rel_path, text: shortenText(name, 28) });
      return el("div", { class: "thumb-tile" }, [thumb.frame, caption]);
    }),
  );
  observeLazyImages(grid);
  return grid;
}

function renderVideosGrid(items) {
  if (!items.length) return renderEmptyState("没有找到视频文件。");
  const grid = el(
    "div",
    { class: "videos-grid" },
    items.map((item) => {
      const name = basename(item.rel_path) || item.rel_path;
      const thumb = createLazyThumb({
        src: API.videoMosaic(item.rel_path),
        alt: `${name} preview`,
        placeholder: "Preview",
      });
      const title = el("div", { class: "video-title", title: item.rel_path, text: name });
      const meta = el("div", { class: "video-meta" }, [
        el("span", { text: item.ext || "" }),
        el("span", { text: formatBytes(item.size_bytes) }),
        el("span", { text: item.folder_rel_path ? item.folder_rel_path : "/" }),
      ]);
      return el("div", { class: "video-card" }, [el("div", { class: "video-cover" }, [thumb.frame]), title, meta]);
    }),
  );
  observeLazyImages(grid);
  return grid;
}

function renderFileTable(items, { emptyMessage } = {}) {
  if (!items.length) return renderEmptyState(emptyMessage || "没有文件。");

  const header = el("tr", {}, [
    el("th", { text: "Name" }),
    el("th", { text: "Folder" }),
    el("th", { text: "Ext" }),
    el("th", { class: "cell--num", text: "Size" }),
    el("th", { text: "Modified" }),
  ]);

  const rows = items.map((item) =>
    el("tr", {}, [
      el("td", { class: "cell--path", title: item.rel_path, text: basename(item.rel_path) || item.rel_path }),
      el("td", { class: "cell--path", title: item.folder_rel_path || "", text: item.folder_rel_path || "/" }),
      el("td", { text: item.ext || "" }),
      el("td", { class: "cell--num", text: formatBytes(item.size_bytes) }),
      el("td", { text: formatDateTime(item.mtime_ms) }),
    ]),
  );

  return el("table", { class: "file-table" }, [el("thead", {}, [header]), el("tbody", {}, rows)]);
}

function renderCategory(category, token) {
  const header = el("div", { class: "view-header" }, [
    el("div", {}, [
      el("div", { class: "breadcrumb", text: `Home / ${category.label}` }),
      el("h1", { class: "title", text: category.label }),
      el("p", { class: "subtitle", text: category.description }),
    ]),
    el("a", { class: "pill", href: "/", "data-nav": "" }, [el("span", { text: "← Home" })]),
  ]);

  const metaHost = el("div", {}, []);
  const bodyHost = el("div", { class: "view-body" }, []);

  main.replaceChildren(header, metaHost, bodyHost);

  let requestEpoch = 0;
  const load = async ({ refresh = false } = {}) => {
    const req = (requestEpoch += 1);

    metaHost.replaceChildren(
      renderMetaBar({
        badges: [
          { label: "Status", value: refresh ? "Refreshing…" : "Loading…" },
          { label: "Route", value: category.path },
        ],
        onRefresh: () => load({ refresh: true }),
      }),
    );
    bodyHost.replaceChildren(el("div", { class: "placeholder" }, [el("div", { text: "Loading…" })]));

    try {
      const refreshParam = refresh ? "?refresh=1" : "";

      if (category.key === "images") {
        const data = await fetchJson(`${API.albums}${refreshParam}`);
        if (token !== renderEpoch || req !== requestEpoch) return;
        const albums = Array.isArray(data.items) ? data.items : [];
        metaHost.replaceChildren(
          renderMetaBar({
            badges: [
              { label: "Albums", value: String(albums.length) },
              { label: "Scanned", value: formatDateTime(data.scanned_at_ms) },
              { label: "MediaRoot", value: shortenText(data.media_root, 44), title: data.media_root },
            ],
            onRefresh: () => load({ refresh: true }),
          }),
        );
        bodyHost.replaceChildren(renderAlbumsGrid(albums));
        return;
      }

      if (category.key === "scattered") {
        const data = await fetchJson(`${API.scattered}${refreshParam}`);
        if (token !== renderEpoch || req !== requestEpoch) return;
        const items = Array.isArray(data.items) ? data.items : [];
        metaHost.replaceChildren(
          renderMetaBar({
            badges: [
              { label: "Images", value: String(items.length) },
              { label: "Scanned", value: formatDateTime(data.scanned_at_ms) },
              { label: "MediaRoot", value: shortenText(data.media_root, 44), title: data.media_root },
            ],
            onRefresh: () => load({ refresh: true }),
          }),
        );
        bodyHost.replaceChildren(renderThumbGrid(items));
        return;
      }

      if (category.key === "videos") {
        const data = await fetchJson(`${API.videos}${refreshParam}`);
        if (token !== renderEpoch || req !== requestEpoch) return;
        const items = Array.isArray(data.items) ? data.items : [];
        metaHost.replaceChildren(
          renderMetaBar({
            badges: [
              { label: "Videos", value: String(items.length) },
              { label: "Scanned", value: formatDateTime(data.scanned_at_ms) },
              { label: "MediaRoot", value: shortenText(data.media_root, 44), title: data.media_root },
            ],
            onRefresh: () => load({ refresh: true }),
          }),
        );
        bodyHost.replaceChildren(renderVideosGrid(items));
        return;
      }

      if (category.key === "games" || category.key === "others") {
        const data = await fetchJson(`${API.others}${refreshParam}`);
        if (token !== renderEpoch || req !== requestEpoch) return;
        const games = Array.isArray(data.games) ? data.games : [];
        const others = Array.isArray(data.others) ? data.others : [];

        if (category.key === "games") {
          metaHost.replaceChildren(
            renderMetaBar({
              badges: [
                { label: "Games", value: String(games.length) },
                { label: "Scanned", value: formatDateTime(data.scanned_at_ms) },
                { label: "MediaRoot", value: shortenText(data.media_root, 44), title: data.media_root },
              ],
              onRefresh: () => load({ refresh: true }),
            }),
          );
          bodyHost.replaceChildren(renderFileTable(games, { emptyMessage: "没有找到游戏文件。" }));
          return;
        }

        metaHost.replaceChildren(
          renderMetaBar({
            badges: [
              { label: "Files", value: String(others.length) },
              { label: "Scanned", value: formatDateTime(data.scanned_at_ms) },
              { label: "MediaRoot", value: shortenText(data.media_root, 44), title: data.media_root },
            ],
            onRefresh: () => load({ refresh: true }),
          }),
        );
        bodyHost.replaceChildren(renderFileTable(others, { emptyMessage: "没有找到其他文件。" }));
        return;
      }

      bodyHost.replaceChildren(renderEmptyState("该视图尚未实现。"));
    } catch (err) {
      if (token !== renderEpoch || req !== requestEpoch) return;
      metaHost.replaceChildren(
        renderMetaBar({
          badges: [
            { label: "Status", value: "Error" },
            { label: "Route", value: category.path },
          ],
          onRefresh: () => load({ refresh: true }),
        }),
      );
      bodyHost.replaceChildren(renderErrorState(err, { onRetry: () => load({ refresh: false }) }));
    }
  };

  load({ refresh: false });
}

function renderNotFound(_token) {
  const header = el("div", { class: "view-header" }, [
    el("div", {}, [
      el("div", { class: "breadcrumb", text: `Not Found` }),
      el("h1", { class: "title", text: "Page not found" }),
      el("p", { class: "subtitle", text: "该路径未定义，返回首页继续。" }),
    ]),
    el("a", { class: "pill", href: "/", "data-nav": "" }, [el("span", { text: "← Home" })]),
  ]);
  main.replaceChildren(header);
}

window.addEventListener("popstate", () => render());

document.addEventListener("click", (event) => {
  const anchor = event.target instanceof Element ? event.target.closest("a") : null;
  if (!anchor) return;
  if (!isSpaNavigableClick(event, anchor)) return;

  event.preventDefault();
  navigate(anchor.getAttribute("href") || "/");
});

render();
