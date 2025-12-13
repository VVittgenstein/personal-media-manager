const main = document.getElementById("main");

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
  ["/", { title: "Home", render: renderHome }],
  ...CATEGORIES.map((category) => [category.path, { title: category.label, render: () => renderCategory(category) }]),
]);

const scrollPositions = new Map();

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
  const route = ROUTES.get(location.pathname);
  if (route) {
    route.render();
    document.title = `Personal Media Manager · ${route.title}`;
  } else {
    renderNotFound();
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

function renderHome() {
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

function renderCategory(category) {
  const header = el("div", { class: "view-header" }, [
    el("div", {}, [
      el("div", { class: "breadcrumb", text: `Home / ${category.label}` }),
      el("h1", { class: "title", text: category.label }),
      el("p", { class: "subtitle", text: category.description }),
    ]),
    el("a", { class: "pill", href: "/", "data-nav": "" }, [el("span", { text: "← Home" })]),
  ]);

  const body = el("div", { class: "placeholder" }, [
    el("div", { text: "该视图目前为壳（shell）。下一步任务会在这里接入后端索引 API 并渲染列表/网格。" }),
    el("div", { text: `Route: ${category.path}` }),
  ]);

  main.replaceChildren(header, body);
}

function renderNotFound() {
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
