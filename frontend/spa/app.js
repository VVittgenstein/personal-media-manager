const main = document.getElementById("main");
const appRoot = document.getElementById("app") || document.body;

const API = {
  albums: "/api/albums",
  albumImages: (relPath) => `/api/album-images?path=${encodeURIComponent(relPath)}`,
  scattered: "/api/scattered",
  videos: "/api/videos",
  others: "/api/others",
  thumb: (relPath) => `/api/thumb?path=${encodeURIComponent(relPath)}`,
  albumCover: (relPath) => `/api/album-cover?path=${encodeURIComponent(relPath)}`,
  videoMosaic: (relPath) => `/api/video-mosaic?path=${encodeURIComponent(relPath)}`,
  media: (relPath) => `/api/media?path=${encodeURIComponent(relPath)}`,
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
const imageOverlay = createImageOverlay();
const videoOverlay = createVideoOverlay();
appRoot.append(imageOverlay.root, videoOverlay.root);

function closeAllOverlays({ restoreScroll = false, restoreFocus = false } = {}) {
  imageOverlay.close({ restoreScroll, restoreFocus });
  videoOverlay.close({ restoreScroll, restoreFocus });
}

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
  closeAllOverlays({ restoreScroll: false, restoreFocus: false });
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

function createImageOverlay() {
  const root = el("div", { class: "overlay", "aria-hidden": "true" }, []);
  const backdrop = el(
    "button",
    { class: "overlay__backdrop", type: "button", "aria-label": "Close overlay" },
    [],
  );
  const panel = el("div", { class: "overlay__panel", role: "dialog", "aria-modal": "true" }, []);

  const header = el("div", { class: "overlay__header" }, []);
  const meta = el("div", { class: "overlay__meta" }, []);
  const title = el("div", { class: "overlay__title" }, []);
  const subtitle = el("div", { class: "overlay__subtitle" }, []);
  meta.append(title, subtitle);

  const controls = el("div", { class: "overlay__controls" }, []);
  const closeBtn = el(
    "button",
    { class: "overlay__iconbtn", type: "button", "aria-label": "Close (Esc)" },
    [el("span", { text: "✕" }, [])],
  );
  controls.append(closeBtn);
  header.append(meta, controls);

  const viewer = el("div", { class: "overlay__viewer" }, []);
  const prevBtn = el(
    "button",
    { class: "overlay__nav overlay__nav--prev", type: "button", "aria-label": "Previous (←)" },
    [el("span", { text: "←" }, [])],
  );
	  const nextBtn = el(
	    "button",
	    { class: "overlay__nav overlay__nav--next", type: "button", "aria-label": "Next (→)" },
	    [el("span", { text: "→" }, [])],
	  );
	  const stage = el("div", { class: "overlay__stage" }, []);
	  const bg = el("div", { class: "overlay__bg" }, []);
	  const status = el("div", { class: "overlay__status", text: "" }, []);
	  const img = el("img", { class: "overlay__img", alt: "" }, []);
	  stage.append(bg, status, img);
	  viewer.append(prevBtn, stage, nextBtn);

  panel.append(header, viewer);
  root.append(backdrop, panel);

  const albumCache = new Map();
  let requestEpoch = 0;
  let isOpen = false;
  let items = [];
  let index = 0;
  let contextTitle = "";
  let message = "";
  let openerEl = null;
  let savedScrollY = 0;
  let savedBodyOverflow = "";
  let savedBodyPaddingRight = "";

  function lockBodyScroll() {
    savedScrollY = window.scrollY;
    savedBodyOverflow = document.body.style.overflow;
    savedBodyPaddingRight = document.body.style.paddingRight;
    const gap = window.innerWidth - document.documentElement.clientWidth;
    document.body.classList.add("overlay-open");
    document.body.style.overflow = "hidden";
    if (gap > 0) {
      document.body.style.paddingRight = `${gap}px`;
    }
  }

  function unlockBodyScroll() {
    document.body.classList.remove("overlay-open");
    document.body.style.overflow = savedBodyOverflow;
    document.body.style.paddingRight = savedBodyPaddingRight;
  }

	  function update() {
	    if (!isOpen) return;
	    const total = items.length;
	    const hasItems = total > 0;
	    prevBtn.disabled = !hasItems || index <= 0;
	    nextBtn.disabled = !hasItems || index >= total - 1;
	    stage.classList.toggle("has-media", hasItems);

	    const currentRelPath = hasItems ? String(items[index] || "") : "";
	    const currentName = currentRelPath ? basename(currentRelPath) || currentRelPath : "";
	    title.textContent = contextTitle || currentName || "Image";

	    if (hasItems) {
	      subtitle.textContent = `${currentName} · ${index + 1}/${total}`;
	      status.textContent = "Loading…";
	      img.classList.remove("is-loaded", "is-error");
	      img.alt = currentName || "image";
	      const src = API.thumb(currentRelPath);
	      bg.style.backgroundImage = `url("${src}")`;
	      img.src = src;
	      return;
	    }

	    subtitle.textContent = "";
	    bg.style.backgroundImage = "";
	    img.removeAttribute("src");
	    img.alt = "";
	    status.textContent = message || "No image.";
	  }

  function open({ relPaths, startIndex = 0, title: nextTitle = "", opener } = {}) {
    requestEpoch += 1;
    openerEl = opener instanceof HTMLElement ? opener : document.activeElement instanceof HTMLElement ? document.activeElement : null;
    contextTitle = String(nextTitle || "");
    message = "";
    items = Array.isArray(relPaths) ? relPaths.filter((p) => typeof p === "string" && p.trim()) : [];
    const max = Math.max(0, items.length - 1);
    index = Math.min(Math.max(0, Number(startIndex) || 0), max);

    if (!isOpen) {
      isOpen = true;
      lockBodyScroll();
      root.classList.add("is-open");
      root.setAttribute("aria-hidden", "false");
    }

    update();
    closeBtn.focus({ preventScroll: true });
  }

	  function close({ restoreScroll = true, restoreFocus = true } = {}) {
	    if (!isOpen) return;
	    requestEpoch += 1;
	    isOpen = false;
	    items = [];
	    index = 0;
	    contextTitle = "";
	    message = "";
	    root.classList.remove("is-open");
	    root.setAttribute("aria-hidden", "true");
	    stage.classList.remove("has-media");
	    bg.style.backgroundImage = "";
	    img.removeAttribute("src");
	    img.alt = "";
	    unlockBodyScroll();

    const focusTarget = openerEl;
    openerEl = null;
    const y = savedScrollY;
    if (restoreScroll) {
      requestAnimationFrame(() => window.scrollTo(0, y));
    }
    if (restoreFocus && focusTarget && focusTarget.isConnected) {
      focusTarget.focus({ preventScroll: true });
    }
  }

  function move(delta) {
    if (!isOpen) return;
    const total = items.length;
    if (!total) return;
    const nextIndex = Math.min(Math.max(0, index + delta), total - 1);
    if (nextIndex === index) return;
    index = nextIndex;
    update();
  }

  async function openAlbum({ albumRelPath, title: nextTitle, opener } = {}) {
    const rel = typeof albumRelPath === "string" ? albumRelPath.trim() : "";
    if (!rel) return;

    const cached = albumCache.get(rel);
    if (Array.isArray(cached) && cached.length) {
      open({ relPaths: cached, startIndex: 0, title: nextTitle || rel, opener });
      return;
    }

    open({ relPaths: [], startIndex: 0, title: nextTitle || rel, opener });
    const req = requestEpoch;
    message = "Loading…";
    update();

    try {
      const data = await fetchJson(API.albumImages(rel));
      if (req !== requestEpoch || !isOpen) return;
      const relPaths = Array.isArray(data.items) ? data.items.filter((p) => typeof p === "string" && p.trim()) : [];
      albumCache.set(rel, relPaths);
      if (!relPaths.length) {
        message = "No images in album.";
        update();
        return;
      }
      items = relPaths;
      index = 0;
      message = "";
      update();
    } catch (err) {
      if (req !== requestEpoch || !isOpen) return;
      message = err?.message ? String(err.message) : "Failed to load album images.";
      update();
    }
  }

  backdrop.addEventListener("click", () => close());
  closeBtn.addEventListener("click", () => close());
  prevBtn.addEventListener("click", () => move(-1));
  nextBtn.addEventListener("click", () => move(1));

	  img.addEventListener("load", () => {
	    if (!isOpen) return;
	    img.classList.add("is-loaded");
	    status.textContent = "";
	  });
	  img.addEventListener("error", () => {
	    if (!isOpen) return;
	    img.classList.add("is-error");
	    stage.classList.remove("has-media");
	    bg.style.backgroundImage = "";
	    status.textContent = "Failed to load.";
	  });

  document.addEventListener("keydown", (event) => {
    if (!isOpen) return;
    if (event.defaultPrevented) return;
    if (event.target instanceof HTMLElement) {
      const tag = event.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || event.target.isContentEditable) return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      move(-1);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      move(1);
    }
  });

  return {
    root,
    open,
    openAlbum,
    close,
    get isOpen() {
      return isOpen;
    },
  };
}

function createVideoOverlay() {
  const root = el("div", { class: "overlay overlay--video", "aria-hidden": "true" }, []);
  const backdrop = el(
    "button",
    { class: "overlay__backdrop", type: "button", "aria-label": "Close overlay" },
    [],
  );
  const panel = el("div", { class: "overlay__panel", role: "dialog", "aria-modal": "true" }, []);

  const header = el("div", { class: "overlay__header" }, []);
  const meta = el("div", { class: "overlay__meta" }, []);
  const title = el("div", { class: "overlay__title" }, []);
  const subtitle = el("div", { class: "overlay__subtitle" }, []);
  meta.append(title, subtitle);

  const controls = el("div", { class: "overlay__controls" }, []);
  const closeBtn = el(
    "button",
    { class: "overlay__iconbtn", type: "button", "aria-label": "Close (Esc)" },
    [el("span", { text: "✕" }, [])],
  );
  controls.append(closeBtn);
  header.append(meta, controls);

  const viewer = el("div", { class: "overlay__viewer" }, []);
  const prevBtn = el(
    "button",
    { class: "overlay__nav overlay__nav--prev", type: "button", "aria-label": "Previous (←)" },
    [el("span", { text: "←" }, [])],
  );
  const nextBtn = el(
    "button",
    { class: "overlay__nav overlay__nav--next", type: "button", "aria-label": "Next (→)" },
    [el("span", { text: "→" }, [])],
  );
  const stage = el("div", { class: "overlay__stage" }, []);
  const bg = el("div", { class: "overlay__bg" }, []);
  const status = el("div", { class: "overlay__status", text: "" }, []);
  const video = el("video", { class: "overlay__video", controls: "", playsinline: "", preload: "metadata" }, []);
  stage.append(bg, status, video);
  viewer.append(prevBtn, stage, nextBtn);

  panel.append(header, viewer);
  root.append(backdrop, panel);

  let requestEpoch = 0;
  let isOpen = false;
  let items = [];
  let index = 0;
  let contextTitle = "";
  let message = "";
  let openerEl = null;
  let savedScrollY = 0;
  let savedBodyOverflow = "";
  let savedBodyPaddingRight = "";

  function lockBodyScroll() {
    savedScrollY = window.scrollY;
    savedBodyOverflow = document.body.style.overflow;
    savedBodyPaddingRight = document.body.style.paddingRight;
    const gap = window.innerWidth - document.documentElement.clientWidth;
    document.body.classList.add("overlay-open");
    document.body.style.overflow = "hidden";
    if (gap > 0) {
      document.body.style.paddingRight = `${gap}px`;
    }
  }

  function unlockBodyScroll() {
    document.body.classList.remove("overlay-open");
    document.body.style.overflow = savedBodyOverflow;
    document.body.style.paddingRight = savedBodyPaddingRight;
  }

  function stopVideo() {
    try {
      video.pause();
    } catch {
      // ignore
    }
    video.removeAttribute("src");
    video.removeAttribute("poster");
    try {
      video.load();
    } catch {
      // ignore
    }
  }

  function update() {
    if (!isOpen) return;
    const total = items.length;
    const hasItems = total > 0;
    prevBtn.disabled = !hasItems || index <= 0;
    nextBtn.disabled = !hasItems || index >= total - 1;
    stage.classList.toggle("has-media", hasItems);

    const current = hasItems ? items[index] : null;
    const currentRelPath = current?.rel_path ? String(current.rel_path) : "";
    const currentName = currentRelPath ? basename(currentRelPath) || currentRelPath : "";
    title.textContent = contextTitle || currentName || "Video";

    if (hasItems && currentRelPath) {
      const ext = current?.ext ? String(current.ext) : "";
      const folder = current?.folder_rel_path ? String(current.folder_rel_path) : "/";
      const size = current?.size_bytes !== null && current?.size_bytes !== undefined ? formatBytes(current.size_bytes) : "";
      const parts = [`${index + 1}/${total}`];
      if (ext) parts.push(ext);
      if (size && size !== "—") parts.push(size);
      if (folder) parts.push(folder);
      subtitle.textContent = `${currentName} · ${parts.join(" · ")}`;

      status.textContent = "Loading…";
      const src = API.media(currentRelPath);
      const poster = API.videoMosaic(currentRelPath);
      bg.style.backgroundImage = `url("${poster}")`;

      if (video.getAttribute("src") !== src) {
        stopVideo();
        video.src = src;
        video.poster = poster;
      }

      const req = requestEpoch;
      const playPromise = video.play();
      if (playPromise && typeof playPromise.then === "function") {
        playPromise
          .then(() => {
            if (req !== requestEpoch || !isOpen) return;
            status.textContent = "";
          })
          .catch((err) => {
            if (req !== requestEpoch || !isOpen) return;
            status.textContent = err?.message ? String(err.message) : "Autoplay blocked. Press play.";
          });
      } else {
        status.textContent = "";
      }
      return;
    }

    subtitle.textContent = "";
    bg.style.backgroundImage = "";
    stopVideo();
    status.textContent = message || "No video.";
  }

  function open({ items: nextItems, startIndex = 0, title: nextTitle = "", opener } = {}) {
    requestEpoch += 1;
    openerEl = opener instanceof HTMLElement ? opener : document.activeElement instanceof HTMLElement ? document.activeElement : null;
    contextTitle = String(nextTitle || "");
    message = "";
    items = Array.isArray(nextItems)
      ? nextItems.filter((item) => item && typeof item.rel_path === "string" && item.rel_path.trim())
      : [];
    const max = Math.max(0, items.length - 1);
    index = Math.min(Math.max(0, Number(startIndex) || 0), max);

    if (!isOpen) {
      isOpen = true;
      lockBodyScroll();
      root.classList.add("is-open");
      root.setAttribute("aria-hidden", "false");
    }

    update();
    closeBtn.focus({ preventScroll: true });
  }

  function close({ restoreScroll = true, restoreFocus = true } = {}) {
    if (!isOpen) return;
    requestEpoch += 1;
    isOpen = false;
    items = [];
    index = 0;
    contextTitle = "";
    message = "";
    root.classList.remove("is-open");
    root.setAttribute("aria-hidden", "true");
    stage.classList.remove("has-media");
    bg.style.backgroundImage = "";
    stopVideo();
    unlockBodyScroll();

    const focusTarget = openerEl;
    openerEl = null;
    const y = savedScrollY;
    if (restoreScroll) {
      requestAnimationFrame(() => window.scrollTo(0, y));
    }
    if (restoreFocus && focusTarget && focusTarget.isConnected) {
      focusTarget.focus({ preventScroll: true });
    }
  }

  function move(delta) {
    if (!isOpen) return;
    const total = items.length;
    if (!total) return;
    const nextIndex = Math.min(Math.max(0, index + delta), total - 1);
    if (nextIndex === index) return;
    index = nextIndex;
    update();
  }

  backdrop.addEventListener("click", () => close());
  closeBtn.addEventListener("click", () => close());
  prevBtn.addEventListener("click", () => move(-1));
  nextBtn.addEventListener("click", () => move(1));

  video.addEventListener("playing", () => {
    if (!isOpen) return;
    status.textContent = "";
  });
  video.addEventListener("error", () => {
    if (!isOpen) return;
    status.textContent = "Failed to load.";
  });

  document.addEventListener("keydown", (event) => {
    if (!isOpen) return;
    if (event.defaultPrevented) return;
    if (event.target instanceof HTMLElement) {
      const tag = event.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "VIDEO" || event.target.isContentEditable) return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      move(-1);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      move(1);
    }
  });

  return {
    root,
    open,
    close,
    get isOpen() {
      return isOpen;
    },
  };
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

      const albumTitle = album.name || album.title || album.rel_path;
      return el("button", { class: "album-card", type: "button", "data-album": album.rel_path, "data-title": albumTitle }, [
        el("div", { class: "album-cover" }, [cover.frame]),
        el("div", { class: "album-title", text: albumTitle }),
        el("div", { class: "album-subtitle", title: album.rel_path, text: shortenText(album.rel_path, 44) }),
      ]);
    }),
  );
  grid.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("button[data-album]") : null;
    if (!target || !grid.contains(target)) return;
    const rel = target.getAttribute("data-album") || "";
    const title = target.getAttribute("data-title") || rel;
    imageOverlay.openAlbum({ albumRelPath: rel, title, opener: target });
  });
  observeLazyImages(grid);
  return grid;
}

function renderThumbGrid(items) {
  if (!items.length) return renderEmptyState("没有找到散图。");
  const relPaths = items.map((item) => item.rel_path);
  const grid = el(
    "div",
    { class: "thumbs-grid" },
    items.map((item, i) => {
      const name = basename(item.rel_path) || item.rel_path;
      const thumb = createLazyThumb({ src: API.thumb(item.rel_path), alt: name });
      const caption = el("div", { class: "thumb-caption", title: item.rel_path, text: shortenText(name, 28) });
      return el("button", { class: "thumb-tile", type: "button", "data-index": String(i) }, [thumb.frame, caption]);
    }),
  );
  grid.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("button[data-index]") : null;
    if (!target || !grid.contains(target)) return;
    const idx = Number.parseInt(target.getAttribute("data-index") || "", 10);
    if (!Number.isFinite(idx)) return;
    imageOverlay.open({ relPaths, startIndex: idx, title: "Scattered", opener: target });
  });
  observeLazyImages(grid);
  return grid;
}

function renderVideosGrid(items) {
  if (!items.length) return renderEmptyState("没有找到视频文件。");
  const grid = el(
    "div",
    { class: "videos-grid" },
    items.map((item, i) => {
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
      return el("button", { class: "video-card", type: "button", "data-index": String(i) }, [
        el("div", { class: "video-cover" }, [thumb.frame]),
        title,
        meta,
      ]);
    }),
  );
  grid.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("button[data-index]") : null;
    if (!target || !grid.contains(target)) return;
    const idx = Number.parseInt(target.getAttribute("data-index") || "", 10);
    if (!Number.isFinite(idx)) return;
    videoOverlay.open({ items, startIndex: idx, title: "Videos", opener: target });
  });
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

window.addEventListener("popstate", () => {
  closeAllOverlays({ restoreScroll: false, restoreFocus: false });
  render();
});

document.addEventListener("click", (event) => {
  const anchor = event.target instanceof Element ? event.target.closest("a") : null;
  if (!anchor) return;
  if (!isSpaNavigableClick(event, anchor)) return;

  event.preventDefault();
  navigate(anchor.getAttribute("href") || "/");
});

render();
