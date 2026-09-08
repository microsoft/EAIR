"use strict";

(() => {
  const data = globalThis.TOOLKIT_DOCS;
  const article = document.getElementById("article");
  if (!data || !Array.isArray(data.pages)) {
    article.textContent = "Documentation data is missing. Reinstall or export the complete website, including data.js.";
    return;
  }
  const labels = {
    documentation: "Documentation", searchPlaceholder: "Search documentation", guideLabel: "EAIR GUIDE", onThisPage: "ON THIS PAGE", cliReference: "CLI reference", researchBoundaries: "Research and release boundaries", previous: "Previous", next: "Next", copy: "Copy code", copied: "Copied", copyFailed: "Select and copy the code manually", searchStart: "Browse the guides or search a command, concept, or error.", noResults: "No matching documentation.", searchResults: "matching sections", notFound: "Page not found", returnHome: "Go to quick start", menu: "Open navigation", print: "Print this page", closeSearch: "Close search",
  };
  const groups = [
    { id: "start", icon: "book-open", label: "Get started" },
    { id: "worlds", icon: "network", label: "Microworlds" },
    { id: "verification", icon: "scan-line", label: "Detect & mitigate" },
    { id: "reference", icon: "braces", label: "Reference" },
  ];
  const navigation = document.getElementById("navigation");
  const outline = document.getElementById("outline");
  const dialog = document.getElementById("search-dialog");
  const query = document.getElementById("search-query");
  const results = document.getElementById("search-results");
  const menu = document.getElementById("menu-toggle");
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("nav-backdrop");
  const mobile = matchMedia("(max-width: 760px)");
  let currentPage = null;
  let observer = null;
  let searchIndex = [];

  const text = (key) => labels[key] || key;
  const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  const icon = (name) => `<i data-lucide="${name}" aria-hidden="true"></i>`;
  const refreshIcons = () => globalThis.lucide?.createIcons({ attrs: { "aria-hidden": "true" } });
  const localized = (value) => typeof value === "string" ? value : value.en;

  function setMenu(open, restoreFocus = false) {
    const expanded = open && mobile.matches;
    document.body.classList.toggle("nav-open", expanded);
    menu.setAttribute("aria-expanded", String(expanded));
    backdrop.hidden = !expanded;
    sidebar.inert = mobile.matches && !expanded;
    if (expanded) sidebar.querySelector("[aria-current='page']")?.focus();
    if (restoreFocus) menu.focus();
  }

  function renderNavigation() {
    navigation.innerHTML = groups.map((group) => {
      const pages = data.pages.filter((page) => page.group === group.id);
      if (!pages.length) return "";
      return `<section class="nav-group"><h2>${icon(group.icon)}${escapeHTML(group.label)}</h2><ul>${pages.map((page) => `<li><a class="nav-link" href="#${page.id}" ${page.id === currentPage?.id ? 'aria-current="page"' : ""}>${escapeHTML(localized(page.title))}</a></li>`).join("")}</ul></section>`;
    }).join("");
  }

  function getRoute() {
    try {
      const [page = "quickstart", section = ""] = decodeURIComponent(location.hash.slice(1) || "quickstart").split("/");
      return { page, section };
    } catch { return { page: "not-found", section: "" }; }
  }

  function renderPage(options = {}) {
    const route = getRoute();
    currentPage = data.pages.find((page) => page.id === route.page);
    observer?.disconnect();
    renderNavigation();
    outline.innerHTML = "";
    if (!currentPage) {
      article.innerHTML = `<h1>${text("notFound")}</h1><p><a href="#quickstart">${text("returnHome")}</a></p>`;
      document.getElementById("pagination").innerHTML = "";
      document.getElementById("breadcrumb").textContent = "Documentation";
      document.title = `${text("notFound")} | EAIR`;
      refreshIcons();
      return;
    }
    const group = groups.find((entry) => entry.id === currentPage.group);
    document.title = `${localized(currentPage.title)} | EAIR`;
    document.getElementById("breadcrumb").innerHTML = `<span>${escapeHTML(group.label)}</span>${icon("chevron-right")}<span>${escapeHTML(localized(currentPage.title))}</span>`;
    article.innerHTML = `<h1>${escapeHTML(localized(currentPage.title))}</h1><p class="lead">${escapeHTML(localized(currentPage.description))}</p>${currentPage.sections.map((section) => `<section class="doc-section" id="section-${section.id}"><h2>${escapeHTML(localized(section.title))}<a class="heading-anchor" href="#${currentPage.id}/${section.id}" aria-label="${escapeHTML(localized(section.title))}">#</a></h2>${localized(section.body)}</section>`).join("")}`;
    outline.innerHTML = currentPage.sections.map((section) => `<a href="#${currentPage.id}/${section.id}" data-section="${section.id}">${escapeHTML(localized(section.title))}</a>`).join("");
    document.querySelectorAll(".copy-code").forEach((button) => {
      button.title = text("copy");
      button.setAttribute("aria-label", text("copy"));
    });
    const index = data.pages.indexOf(currentPage);
    const previous = data.pages[index - 1];
    const next = data.pages[index + 1];
    const pageLink = (page, direction) => page ? `<a href="#${page.id}">${direction === "previous" ? icon("arrow-left") : ""}<span><small>${text(direction)}</small>${escapeHTML(localized(page.title))}</span>${direction === "next" ? icon("arrow-right") : ""}</a>` : "<span></span>";
    document.getElementById("pagination").innerHTML = pageLink(previous, "previous") + pageLink(next, "next");
    refreshIcons();
    observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((first, second) => first.boundingClientRect.top - second.boundingClientRect.top)[0];
      if (!visible) return;
      outline.querySelectorAll("a").forEach((anchor) => {
        if (`section-${anchor.dataset.section}` === visible.target.id) anchor.setAttribute("aria-current", "location");
        else anchor.removeAttribute("aria-current");
      });
    }, { rootMargin: "-100px 0px -60% 0px", threshold: 0 });
    article.querySelectorAll(".doc-section").forEach((section) => observer.observe(section));
    if (!options.preserveScroll) {
      requestAnimationFrame(() => {
        const target = route.section && document.getElementById(`section-${route.section}`);
        if (target) target.scrollIntoView({ block: "start" });
        else scrollTo({ top: 0, behavior: "instant" });
      });
    }
  }

  function rebuildSearchIndex() {
    const scratch = document.createElement("div");
    searchIndex = data.pages.flatMap((page) => page.sections.map((section) => {
      scratch.innerHTML = localized(section.body);
      const content = (scratch.textContent || "").replace(/\s+/g, " ");
      return { page: page.id, section: section.id, title: localized(page.title), heading: localized(section.title), content, searchable: `${localized(page.title)} ${localized(section.title)} ${content}`.toLocaleLowerCase() };
    }));
  }

  function renderSearch() {
    const needle = query.value.trim().toLocaleLowerCase();
    const words = needle.split(/\s+/).filter(Boolean);
    const matching = needle ? searchIndex.filter((entry) => words.every((word) => entry.searchable.includes(word))).sort((first, second) => Number(second.heading.toLocaleLowerCase().includes(needle)) - Number(first.heading.toLocaleLowerCase().includes(needle))) : searchIndex.filter((entry) => entry.section === data.pages.find((page) => page.id === entry.page).sections[0].id);
    document.getElementById("search-status").textContent = needle ? (matching.length ? `${matching.length} ${text("searchResults")}` : text("noResults")) : text("searchStart");
    results.innerHTML = matching.slice(0, 16).map((entry) => {
      const position = needle ? entry.content.toLocaleLowerCase().indexOf(words[0]) : 0;
      const start = Math.max(0, position - 50);
      const excerpt = entry.content.slice(start, start + 160);
      return `<a class="search-result" href="#${entry.page}/${entry.section}"><strong>${escapeHTML(entry.title)} / ${escapeHTML(entry.heading)}</strong><span>${start ? "... " : ""}${escapeHTML(excerpt)}${excerpt.length === 160 ? "..." : ""}</span></a>`;
    }).join("");
  }

  function initializeLabels() {
    document.documentElement.lang = "en";
    document.querySelectorAll("[data-i18n]").forEach((element) => { element.textContent = text(element.dataset.i18n); });
    query.placeholder = text("searchPlaceholder");
    query.setAttribute("aria-label", text("searchPlaceholder"));
    document.getElementById("search-title").textContent = text("searchPlaceholder");
    for (const [identifier, label] of [["menu-toggle", "menu"], ["print-page", "print"], ["search-close", "closeSearch"], ["search-open", "searchPlaceholder"]]) {
      const button = document.getElementById(identifier);
      button.title = text(label);
      button.setAttribute("aria-label", text(label));
    }
    rebuildSearchIndex();
    renderPage({ preserveScroll: true });
    renderSearch();
  }

  async function copyCode(button) {
    const source = button.closest(".code-block").querySelector("code").textContent;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(source);
      else throw new Error("Clipboard API unavailable");
    } catch {
      const selection = document.createElement("textarea");
      selection.value = source;
      selection.style.position = "fixed";
      selection.style.opacity = "0";
      document.body.append(selection);
      selection.select();
      const copied = document.execCommand("copy");
      selection.remove();
      button.focus();
      if (!copied) {
        document.getElementById("copy-status").textContent = text("copyFailed");
        button.title = text("copyFailed");
        return;
      }
    }
    button.classList.add("copied");
    button.innerHTML = icon("check");
    button.title = text("copied");
    button.setAttribute("aria-label", text("copied"));
    document.getElementById("copy-status").textContent = text("copied");
    refreshIcons();
    setTimeout(() => {
      if (!button.isConnected) return;
      button.classList.remove("copied");
      button.innerHTML = icon("copy");
      button.title = text("copy");
      button.setAttribute("aria-label", text("copy"));
      refreshIcons();
    }, 1800);
  }

  document.addEventListener("click", (event) => {
    const copy = event.target.closest(".copy-code");
    if (copy) copyCode(copy);
    const platform = event.target.closest("[data-platform]");
    if (platform) {
      const section = platform.closest(".doc-section");
      section.querySelectorAll("[data-platform]").forEach((button) => button.setAttribute("aria-selected", String(button === platform)));
      section.querySelectorAll("[data-platform-panel]").forEach((panel) => { panel.hidden = panel.dataset.platformPanel !== platform.dataset.platform; });
    }
    const link = event.target.closest('a[href^="#"]');
    if (link?.getAttribute("href") === "#main-content") {
      event.preventDefault();
      document.getElementById("main-content").focus();
      return;
    }
    if (link) {
      if (dialog.open) dialog.close();
      setMenu(false);
      if (link.getAttribute("href") === location.hash) renderPage();
    }
  });
  menu.addEventListener("click", () => setMenu(menu.getAttribute("aria-expanded") !== "true"));
  backdrop.addEventListener("click", () => setMenu(false, true));
  mobile.addEventListener("change", () => setMenu(false));
  document.getElementById("print-page").addEventListener("click", () => print());
  document.getElementById("search-open").addEventListener("click", () => { dialog.showModal(); renderSearch(); query.focus(); });
  document.getElementById("search-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) { const bounds = dialog.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close(); } });
  query.addEventListener("input", renderSearch);
  query.addEventListener("keydown", (event) => { if (event.key === "ArrowDown") { event.preventDefault(); results.querySelector("a")?.focus(); } if (event.key === "Enter") { event.preventDefault(); results.querySelector("a")?.click(); } });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); if (!dialog.open) dialog.showModal(); query.focus(); renderSearch(); }
    if (event.key === "Escape" && document.body.classList.contains("nav-open")) setMenu(false, true);
    if (event.key === "Tab" && document.body.classList.contains("nav-open")) {
      const links = [...sidebar.querySelectorAll("a")];
      if (!event.shiftKey && document.activeElement === links.at(-1)) { event.preventDefault(); links[0].focus(); }
      if (event.shiftKey && document.activeElement === links[0]) { event.preventDefault(); links.at(-1).focus(); }
    }
  });
  addEventListener("hashchange", () => renderPage());
  document.getElementById("version").textContent = `v${data.version}`;
  document.getElementById("footer-version").textContent = `Enterprise Agent Risk (EAIR) / v${data.version}`;
  initializeLabels();
  setMenu(false);
  if (getRoute().section) requestAnimationFrame(() => document.getElementById(`section-${getRoute().section}`)?.scrollIntoView());
})();