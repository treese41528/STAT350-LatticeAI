import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeSetting = "system" | "light" | "dark";

interface SettingsState {
  theme: ThemeSetting;
  setTheme: (theme: ThemeSetting) => void;
}

/**
 * Persisted under "stat350.settings" — the inline theme-boot script in
 * index.html reads the same key before first paint, so keep the shape
 * ({ state: { theme } }) stable.
 */
export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      theme: "system",
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: "stat350.settings",
      partialize: (s) => ({ theme: s.theme }),
    },
  ),
);

export function resolveTheme(theme: ThemeSetting): "light" | "dark" {
  if (theme !== "system") return theme;
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: ThemeSetting): void {
  document.documentElement.setAttribute("data-theme", resolveTheme(theme));
}
