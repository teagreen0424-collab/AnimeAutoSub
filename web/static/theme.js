// 2026 Modern UI Theme Engine (Studio Light / Spatial Dark / Auto Follow)
const STORAGE_KEY = "aas-theme";
const STORAGE_LEGACY = "aas_theme";

function getSystemPreference() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function getSavedTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY) || localStorage.getItem(STORAGE_LEGACY) || "light";
  } catch (_) {
    return "light";
  }
}

export function resolveEffectiveTheme(mode) {
  if (mode === "dark" || mode === "light") return mode;
  return getSystemPreference();
}

export function applyTheme(mode, persist = true) {
  const effective = resolveEffectiveTheme(mode);

  // 1. Set html[data-theme] and body classes
  document.documentElement.dataset.theme = effective;
  if (document.body) {
    document.body.classList.remove("dark-theme", "light-theme");
    document.body.classList.add(effective + "-theme");
  }

  // 2. Toggle button icon: 浅色显示 🌙 (点此变暗), 暗色显示 ☀️ (点此变亮)
  const icon = document.getElementById("themeIcon");
  if (icon) {
    icon.textContent = effective === "light" ? "🌙" : "☀️";
  }
  const btn = document.getElementById("btnThemeToggle");
  if (btn) {
    btn.title = effective === "light" ? "当前为浅色主题 (点击切换暗色)" : "当前为暗色主题 (点击切换浅色)";
  }

  // 3. Sync Settings select
  const sel = document.getElementById("selectThemeMode");
  if (sel && sel.value !== mode) {
    sel.value = mode;
    sel.dispatchEvent(new Event("change", { bubbles: false }));
  }

  // 4. Persistence
  if (persist) {
    try {
      localStorage.setItem(STORAGE_KEY, mode);
      localStorage.setItem(STORAGE_LEGACY, mode);
    } catch (_) {}
  }
}

export function toggleTheme() {
  const curEffective = document.documentElement.dataset.theme || (document.body && document.body.classList.contains("dark-theme") ? "dark" : "light");
  const next = curEffective === "light" ? "dark" : "light";
  applyTheme(next, true);
}

function initThemeEngine() {
  const saved = getSavedTheme();
  applyTheme(saved, false);

  const toggleBtn = document.getElementById("btnThemeToggle");
  if (toggleBtn) {
    toggleBtn.onclick = (e) => {
      e.preventDefault();
      toggleTheme();
    };
  }

  const sel = document.getElementById("selectThemeMode");
  if (sel) {
    sel.value = saved;
    sel.onchange = () => {
      applyTheme(sel.value, true);
    };
  }

  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      const curSaved = getSavedTheme();
      if (curSaved === "auto") {
        applyTheme("auto", false);
      }
    };
    if (mq.addEventListener) mq.addEventListener("change", handler);
    else if (mq.addListener) mq.addListener(handler);
  }
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initThemeEngine);
  } else {
    initThemeEngine();
  }
}

window.__applyTheme = applyTheme;
window.__toggleTheme = toggleTheme;
