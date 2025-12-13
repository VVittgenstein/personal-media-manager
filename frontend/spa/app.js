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
  delete: "/api/delete",
  move: "/api/move",
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
const fileOpsDialog = createFileOpsDialog();
appRoot.append(imageOverlay.root, videoOverlay.root, fileOpsDialog.root);

function closeAllOverlays({ restoreScroll = false, restoreFocus = false } = {}) {
  imageOverlay.close({ restoreScroll, restoreFocus });
  videoOverlay.close({ restoreScroll, restoreFocus });
  fileOpsDialog.close({ restoreScroll, restoreFocus });
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

async function fetchJson(url, init = {}) {
  const headers = new Headers(init?.headers || {});
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  const res = await fetch(url, { ...init, headers, cache: "no-store" });
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

async function postJson(url, body) {
  return fetchJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
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

function createFileOpsDialog() {
  const root = el("div", { class: "modal", "aria-hidden": "true" }, []);
  const backdrop = el("button", { class: "modal__backdrop", type: "button", "aria-label": "Close dialog" }, []);
  const panel = el("div", { class: "modal__panel", role: "dialog", "aria-modal": "true" }, []);

  const header = el("div", { class: "modal__header" }, []);
  const meta = el("div", { class: "modal__meta" }, []);
  const title = el("div", { class: "modal__title", text: "" }, []);
  const subtitle = el("div", { class: "modal__subtitle", text: "" }, []);
  meta.append(title, subtitle);
  const closeBtn = el(
    "button",
    { class: "modal__iconbtn", type: "button", "aria-label": "Close dialog (Esc)" },
    [el("span", { text: "✕" }, [])],
  );
  header.append(meta, closeBtn);

  const body = el("div", { class: "modal__body" }, []);
  const footer = el("div", { class: "modal__footer" }, []);
  const cancelBtn = el("button", { class: "btn", type: "button" }, [el("span", { text: "Cancel" })]);
  const primaryBtn = el("button", { class: "btn", type: "button" }, [el("span", { text: "" })]);
  footer.append(cancelBtn, primaryBtn);

  panel.append(header, body, footer);
  root.append(backdrop, panel);

  let isOpen = false;
  let openerEl = null;
  let savedScrollY = 0;
  let savedBodyOverflow = "";
  let savedBodyPaddingRight = "";
  let requestEpoch = 0;
  let primaryAction = null;

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
    requestAnimationFrame(() => window.scrollTo(0, savedScrollY));
  }

  function describeFileOpsError(err) {
    const code = err?.code ? String(err.code) : "UNKNOWN";
    const msg = err?.message ? String(err.message) : "Unknown error";
    const hints = {
      SANDBOX_VIOLATION: "路径越界：只能操作 MediaRoot 内的相对路径。",
      ROOT_FORBIDDEN: "禁止对 MediaRoot 根目录执行此操作。",
      DST_EXISTS: "目标已存在：请更换目标路径或先处理同名文件。",
      DST_PARENT_MISSING: "目标目录不存在：可勾选“Create parents”自动创建。",
      DST_PARENT_NOT_DIR: "目标父路径不是文件夹。",
      INVALID_MOVE: "无效移动：不能把文件夹移动到自身内部。",
      STALE_CONFIRM_TOKEN: "文件状态已变化：请重新打开窗口获取最新确认信息。",
      STAT_FAILED: "读取文件信息失败：可能已被删除或权限不足。",
    };
    const hint = hints[code] || "";
    return { code, msg, hint };
  }

  function renderKv(labelText, valueText, { mono = false } = {}) {
    const valueAttrs = { class: mono ? "modal__value modal__value--mono" : "modal__value", text: valueText };
    return el("div", { class: "modal__kv" }, [
      el("div", { class: "modal__label", text: labelText }),
      el("div", valueAttrs),
    ]);
  }

  function renderErrorBox(err) {
    const { code, msg, hint } = describeFileOpsError(err);
    const heading = hint || "操作失败。";
    return el("div", { class: "modal-error" }, [
      el("div", { class: "modal-error__title", text: heading }),
      el("pre", { class: "modal-error__detail", text: `${code}: ${msg}` }),
    ]);
  }

  function openBase({ nextTitle, nextSubtitle, opener } = {}) {
    requestEpoch += 1;
    openerEl = opener instanceof HTMLElement ? opener : document.activeElement instanceof HTMLElement ? document.activeElement : null;
    title.textContent = String(nextTitle || "");
    subtitle.textContent = String(nextSubtitle || "");
    body.replaceChildren();
    cancelBtn.disabled = false;
    primaryBtn.disabled = true;
    primaryBtn.classList.remove("btn--danger");
    primaryBtn.querySelector("span").textContent = "";
    primaryAction = null;

    if (!isOpen) {
      lockBodyScroll();
      isOpen = true;
      root.classList.add("is-open");
      root.setAttribute("aria-hidden", "false");
    }
    closeBtn.focus({ preventScroll: true });
    return requestEpoch;
  }

  function close({ restoreScroll = true, restoreFocus = true } = {}) {
    if (!isOpen) return;
    requestEpoch += 1;
    isOpen = false;
    root.classList.remove("is-open");
    root.setAttribute("aria-hidden", "true");
    primaryAction = null;
    body.replaceChildren();
    if (restoreScroll) {
      unlockBodyScroll();
    } else {
      document.body.classList.remove("overlay-open");
      document.body.style.overflow = savedBodyOverflow;
      document.body.style.paddingRight = savedBodyPaddingRight;
    }
    if (restoreFocus && openerEl) {
      openerEl.focus({ preventScroll: true });
    }
    openerEl = null;
  }

  function setBusy(isBusy) {
    cancelBtn.disabled = isBusy;
    closeBtn.disabled = isBusy;
    backdrop.disabled = isBusy;
    if (!isBusy) return;
    primaryBtn.disabled = true;
  }

  async function openDelete({ relPath, opener, onDone } = {}) {
    const srcRelPath = String(relPath || "");
    if (!srcRelPath) return;

    const req = openBase({ nextTitle: "Delete", nextSubtitle: shortenText(srcRelPath, 64), opener });
    cancelBtn.querySelector("span").textContent = "Cancel";
    primaryBtn.querySelector("span").textContent = "Delete";
    primaryBtn.classList.add("btn--danger");
    body.replaceChildren(el("div", { class: "modal__hint", text: "Loading preview…" }));

    let confirmToken = "";
    try {
      const data = await postJson(API.delete, { path: srcRelPath });
      if (!isOpen || req !== requestEpoch) return;

      const preview = data?.preview && typeof data.preview === "object" ? data.preview : {};
      confirmToken = typeof data?.confirm_token === "string" ? data.confirm_token : "";

      const parts = [
        el("div", { class: "modal__text", text: "确认删除以下内容？删除后将无法恢复。" }),
        renderKv("Source", preview.src_rel_path ? String(preview.src_rel_path) : srcRelPath, { mono: true }),
        renderKv("Type", preview.is_dir ? "Folder" : "File"),
      ];
      if (!preview.is_dir) {
        parts.push(renderKv("Size", formatBytes(preview.size_bytes)));
      }
      parts.push(renderKv("Modified", formatDateTime(preview.mtime_ms)));
      body.replaceChildren(...parts);

      primaryBtn.disabled = !confirmToken;
      primaryAction = async () => {
        if (!confirmToken) return;
        const execReq = (requestEpoch += 1);
        setBusy(true);
        body.append(el("div", { class: "modal__hint", text: "Deleting…" }));
        try {
          await postJson(API.delete, { path: srcRelPath, confirm: true, confirm_token: confirmToken });
          if (!isOpen || execReq !== requestEpoch) return;
          close({ restoreScroll: true, restoreFocus: true });
          onDone?.();
	        } catch (err) {
	          if (!isOpen || execReq !== requestEpoch) return;
	          setBusy(false);
	          body.append(renderErrorBox(err));
	          primaryBtn.disabled = false;
	        }
	      };
      primaryBtn.focus({ preventScroll: true });
    } catch (err) {
      if (!isOpen || req !== requestEpoch) return;
      body.replaceChildren(renderErrorBox(err));
      primaryBtn.disabled = true;
    }
  }

  async function openMove({ relPath, opener, onDone } = {}) {
    const srcRelPath = String(relPath || "");
    if (!srcRelPath) return;

    const req = openBase({ nextTitle: "Move", nextSubtitle: shortenText(srcRelPath, 64), opener });
    cancelBtn.querySelector("span").textContent = "Cancel";
    primaryBtn.querySelector("span").textContent = "Move";

    const dstInput = el("input", {
      class: "modal__input",
      type: "text",
      value: "",
      placeholder: srcRelPath,
      spellcheck: "false",
      autocomplete: "off",
    });
    const createParents = el("input", { type: "checkbox" }, []);
    const previewHost = el("div", { class: "modal__preview" }, [el("div", { class: "modal__hint", text: "输入目标路径后将自动校验预览。" })]);

    body.replaceChildren(
      el("div", { class: "modal__text", text: "请输入目标路径（相对 MediaRoot）。确认后将移动文件/文件夹。" }),
      renderKv("Source", srcRelPath, { mono: true }),
      el("div", { class: "modal__kv" }, [
        el("div", { class: "modal__label", text: "Destination" }),
        dstInput,
        el("div", { class: "modal__hint", text: "例：archive/2025/" + (basename(srcRelPath) || "file.ext") }),
      ]),
      el("label", { class: "modal__checkbox" }, [
        createParents,
        el("span", { text: "Create parents" }),
      ]),
      previewHost,
    );

    let previewTimeout = null;
    let movePreviewToken = "";
    let lastPreviewKey = "";
    let previewSeq = 0;

    function currentKey() {
      const dst = String(dstInput.value || "").trim();
      return JSON.stringify({ src: srcRelPath, dst, create_parents: createParents.checked });
    }

    function clearPreview() {
      movePreviewToken = "";
      lastPreviewKey = "";
      primaryBtn.disabled = true;
    }

	    async function refreshPreview() {
	      if (!isOpen || req !== requestEpoch) return;
	      const dstRelPath = String(dstInput.value || "").trim();
	      const createParentsValue = Boolean(createParents.checked);
	      const key = currentKey();
	      clearPreview();

      if (!dstRelPath) {
        previewHost.replaceChildren(el("div", { class: "modal__hint", text: "请输入目标路径。" }));
        return;
      }
      if (normalizeRelPathLike(dstRelPath) === normalizeRelPathLike(srcRelPath)) {
        previewHost.replaceChildren(el("div", { class: "modal__hint", text: "目标路径不能与源相同。" }));
        return;
      }

      const seq = (previewSeq += 1);
      previewHost.replaceChildren(el("div", { class: "modal__hint", text: "Validating…" }));
      try {
        const data = await postJson(API.move, { src: srcRelPath, dst: dstRelPath, create_parents: createParentsValue });
        if (!isOpen || req !== requestEpoch || seq !== previewSeq) return;
        const preview = data?.preview && typeof data.preview === "object" ? data.preview : {};
        const token = typeof data?.confirm_token === "string" ? data.confirm_token : "";
        if (!token) {
          previewHost.replaceChildren(el("div", { class: "modal__hint", text: "Preview missing confirm token." }));
          return;
        }
        movePreviewToken = token;
        lastPreviewKey = key;

        const parts = [
          renderKv("Target", preview.dst_rel_path ? String(preview.dst_rel_path) : dstRelPath, { mono: true }),
          renderKv("Type", preview.is_dir ? "Folder" : "File"),
        ];
        if (!preview.is_dir) {
          parts.push(renderKv("Size", formatBytes(preview.size_bytes)));
        }
        parts.push(renderKv("Modified", formatDateTime(preview.mtime_ms)));
        previewHost.replaceChildren(...parts);
        primaryBtn.disabled = false;
      } catch (err) {
        if (!isOpen || req !== requestEpoch || seq !== previewSeq) return;
        previewHost.replaceChildren(renderErrorBox(err));
      }
    }

    function schedulePreview() {
      if (!isOpen || req !== requestEpoch) return;
      clearPreview();
      if (previewTimeout) {
        window.clearTimeout(previewTimeout);
      }
      previewTimeout = window.setTimeout(() => refreshPreview(), 260);
    }

    dstInput.addEventListener("input", () => schedulePreview());
    createParents.addEventListener("change", () => schedulePreview());

    primaryAction = async () => {
      const dstRelPath = String(dstInput.value || "").trim();
      const createParentsValue = Boolean(createParents.checked);
      const key = currentKey();
      if (!movePreviewToken || !dstRelPath || key !== lastPreviewKey) {
        schedulePreview();
        return;
      }

      const execReq = (requestEpoch += 1);
      setBusy(true);
      previewHost.append(el("div", { class: "modal__hint", text: "Moving…" }));
      try {
        await postJson(API.move, {
          src: srcRelPath,
          dst: dstRelPath,
          create_parents: createParentsValue,
          confirm: true,
          confirm_token: movePreviewToken,
        });
        if (!isOpen || execReq !== requestEpoch) return;
        close({ restoreScroll: true, restoreFocus: true });
        onDone?.();
      } catch (err) {
        if (!isOpen || execReq !== requestEpoch) return;
        setBusy(false);
        previewHost.append(renderErrorBox(err));
        clearPreview();
      }
    };

    requestAnimationFrame(() => dstInput.focus({ preventScroll: true }));
  }

  function normalizeRelPathLike(value) {
    return String(value || "")
      .trim()
      .replace(/\\\\/g, "/")
      .replace(/^\\/+/, "")
      .replace(/\\/+$/, "");
  }

  backdrop.addEventListener("click", () => close({ restoreScroll: true, restoreFocus: true }));
  closeBtn.addEventListener("click", () => close({ restoreScroll: true, restoreFocus: true }));
  cancelBtn.addEventListener("click", () => close({ restoreScroll: true, restoreFocus: true }));
  primaryBtn.addEventListener("click", () => primaryAction?.());

  document.addEventListener("keydown", (event) => {
    if (!isOpen) return;
    if (event.defaultPrevented) return;
    if (event.key === "Escape") {
      event.preventDefault();
      close({ restoreScroll: true, restoreFocus: true });
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      primaryAction?.();
    }
  });

  return {
    root,
    openDelete,
    openMove,
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

function renderFileOpsActions(relPath, { variant = "overlay" } = {}) {
  const path = String(relPath || "");
  const isInline = variant === "inline";
  const containerClass = isInline ? "item-actions item-actions--inline" : "item-actions item-actions--overlay";
  const moveLabel = isInline ? "Move" : "⇄";
  const deleteLabel = isInline ? "Delete" : "🗑";
  const moveClass = isInline ? "btn btn--sm" : "iconbtn";
  const deleteClass = isInline ? "btn btn--sm btn--danger" : "iconbtn iconbtn--danger";
  return el("div", { class: containerClass }, [
    el("button", { class: moveClass, type: "button", title: "Move", "aria-label": "Move", "data-fileop": "move", "data-rel-path": path }, [
      el("span", { text: moveLabel }),
    ]),
    el(
      "button",
      { class: deleteClass, type: "button", title: "Delete", "aria-label": "Delete", "data-fileop": "delete", "data-rel-path": path },
      [el("span", { text: deleteLabel })],
    ),
  ]);
}

function renderAlbumsGrid(albums, { onFileOps } = {}) {
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
      const shell = el("div", { class: "media-shell" }, []);
      const openBtn = el("button", { class: "album-card", type: "button", "data-album": album.rel_path, "data-title": albumTitle }, [
        el("div", { class: "album-cover" }, [cover.frame]),
        el("div", { class: "album-title", text: albumTitle }),
        el("div", { class: "album-subtitle", title: album.rel_path, text: shortenText(album.rel_path, 44) }),
      ]);
      shell.append(openBtn);
      if (typeof onFileOps === "function") {
        shell.append(renderFileOpsActions(album.rel_path, { variant: "overlay" }));
      }
      return shell;
    }),
  );
  grid.addEventListener("click", (event) => {
    const fileBtn = event.target instanceof Element ? event.target.closest("button[data-fileop]") : null;
    if (fileBtn && grid.contains(fileBtn)) {
      const action = fileBtn.getAttribute("data-fileop") || "";
      const relPath = fileBtn.getAttribute("data-rel-path") || "";
      onFileOps?.({ action, relPath, opener: fileBtn });
      return;
    }
    const target = event.target instanceof Element ? event.target.closest("button[data-album]") : null;
    if (!target || !grid.contains(target)) return;
    const rel = target.getAttribute("data-album") || "";
    const title = target.getAttribute("data-title") || rel;
    imageOverlay.openAlbum({ albumRelPath: rel, title, opener: target });
  });
  observeLazyImages(grid);
  return grid;
}

function renderThumbGrid(items, { onFileOps } = {}) {
  if (!items.length) return renderEmptyState("没有找到散图。");
  const relPaths = items.map((item) => item.rel_path);
  const grid = el(
    "div",
    { class: "thumbs-grid" },
    items.map((item, i) => {
      const name = basename(item.rel_path) || item.rel_path;
      const thumb = createLazyThumb({ src: API.thumb(item.rel_path), alt: name });
      const caption = el("div", { class: "thumb-caption", title: item.rel_path, text: shortenText(name, 28) });
      const shell = el("div", { class: "media-shell" }, []);
      const openBtn = el("button", { class: "thumb-tile", type: "button", "data-index": String(i) }, [thumb.frame, caption]);
      shell.append(openBtn);
      if (typeof onFileOps === "function") {
        shell.append(renderFileOpsActions(item.rel_path, { variant: "overlay" }));
      }
      return shell;
    }),
  );
  grid.addEventListener("click", (event) => {
    const fileBtn = event.target instanceof Element ? event.target.closest("button[data-fileop]") : null;
    if (fileBtn && grid.contains(fileBtn)) {
      const action = fileBtn.getAttribute("data-fileop") || "";
      const relPath = fileBtn.getAttribute("data-rel-path") || "";
      onFileOps?.({ action, relPath, opener: fileBtn });
      return;
    }
    const target = event.target instanceof Element ? event.target.closest("button[data-index]") : null;
    if (!target || !grid.contains(target)) return;
    const idx = Number.parseInt(target.getAttribute("data-index") || "", 10);
    if (!Number.isFinite(idx)) return;
    imageOverlay.open({ relPaths, startIndex: idx, title: "Scattered", opener: target });
  });
  observeLazyImages(grid);
  return grid;
}

function renderVideosGrid(items, { onFileOps } = {}) {
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
      const shell = el("div", { class: "media-shell" }, []);
      const openBtn = el("button", { class: "video-card", type: "button", "data-index": String(i) }, [
        el("div", { class: "video-cover" }, [thumb.frame]),
        title,
        meta,
      ]);
      shell.append(openBtn);
      if (typeof onFileOps === "function") {
        shell.append(renderFileOpsActions(item.rel_path, { variant: "overlay" }));
      }
      return shell;
    }),
  );
  grid.addEventListener("click", (event) => {
    const fileBtn = event.target instanceof Element ? event.target.closest("button[data-fileop]") : null;
    if (fileBtn && grid.contains(fileBtn)) {
      const action = fileBtn.getAttribute("data-fileop") || "";
      const relPath = fileBtn.getAttribute("data-rel-path") || "";
      onFileOps?.({ action, relPath, opener: fileBtn });
      return;
    }
    const target = event.target instanceof Element ? event.target.closest("button[data-index]") : null;
    if (!target || !grid.contains(target)) return;
    const idx = Number.parseInt(target.getAttribute("data-index") || "", 10);
    if (!Number.isFinite(idx)) return;
    videoOverlay.open({ items, startIndex: idx, title: "Videos", opener: target });
  });
  observeLazyImages(grid);
  return grid;
}

function renderFileTable(items, { emptyMessage, onFileOps } = {}) {
  if (!items.length) return renderEmptyState(emptyMessage || "没有文件。");
  const showActions = typeof onFileOps === "function";

  const header = el("tr", {}, [
    el("th", { text: "Name" }),
    el("th", { text: "Folder" }),
    el("th", { text: "Ext" }),
    el("th", { class: "cell--num", text: "Size" }),
    el("th", { text: "Modified" }),
    ...(showActions ? [el("th", { class: "cell--actions", text: "Actions" })] : []),
  ]);

  const rows = items.map((item) => {
    const cells = [
      el("td", { class: "cell--path", title: item.rel_path, text: basename(item.rel_path) || item.rel_path }),
      el("td", { class: "cell--path", title: item.folder_rel_path || "", text: item.folder_rel_path || "/" }),
      el("td", { text: item.ext || "" }),
      el("td", { class: "cell--num", text: formatBytes(item.size_bytes) }),
      el("td", { text: formatDateTime(item.mtime_ms) }),
    ];
    if (showActions) {
      cells.push(el("td", { class: "cell--actions" }, [renderFileOpsActions(item.rel_path, { variant: "inline" })]));
    }
    return el("tr", {}, cells);
  });

  const table = el("table", { class: "file-table" }, [el("thead", {}, [header]), el("tbody", {}, rows)]);
  if (showActions) {
    table.addEventListener("click", (event) => {
      const fileBtn = event.target instanceof Element ? event.target.closest("button[data-fileop]") : null;
      if (!fileBtn || !table.contains(fileBtn)) return;
      const action = fileBtn.getAttribute("data-fileop") || "";
      const relPath = fileBtn.getAttribute("data-rel-path") || "";
      onFileOps?.({ action, relPath, opener: fileBtn });
    });
  }
  return table;
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
	        bodyHost.replaceChildren(renderAlbumsGrid(albums, { onFileOps: openFileOps }));
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
	        bodyHost.replaceChildren(renderThumbGrid(items, { onFileOps: openFileOps }));
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
	        bodyHost.replaceChildren(renderVideosGrid(items, { onFileOps: openFileOps }));
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
	          bodyHost.replaceChildren(renderFileTable(games, { emptyMessage: "没有找到游戏文件。", onFileOps: openFileOps }));
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
	        bodyHost.replaceChildren(renderFileTable(others, { emptyMessage: "没有找到其他文件。", onFileOps: openFileOps }));
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

	  const openFileOps = ({ action, relPath, opener } = {}) => {
	    const nextAction = String(action || "");
	    const nextRelPath = String(relPath || "");
	    if (!nextRelPath) return;
	    if (token !== renderEpoch) return;

	    const refreshAfter = () => {
	      if (token !== renderEpoch) return;
	      load({ refresh: true });
	    };

	    if (nextAction === "delete") {
	      fileOpsDialog.openDelete({ relPath: nextRelPath, opener, onDone: refreshAfter });
	      return;
	    }
	    if (nextAction === "move") {
	      fileOpsDialog.openMove({ relPath: nextRelPath, opener, onDone: refreshAfter });
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
