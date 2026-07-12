import { create } from "zustand";
import * as api from "../api/client";
import type { HealthStatus } from "../api/client";
import { trackEvent } from "../api/events";
import { clearOwnKey as clearStoredKey, ownKeyActive, saveOwnKey } from "../lib/apiKey";
import type { AppConfig, Modality } from "../api/types";

export const MODALITY_LABELS: Record<Modality, string> = {
  flipped: "Flipped",
  traditional: "Traditional Lecture",
  indy: "Traditional (Indianapolis)",
  online: "Asynchronous Online",
  winter: "Winter Session",
  summer: "Summer Session",
};

const FALLBACK_CONFIG: AppConfig = {
  courseName: "STAT 350",
  term: "",
  welcome: "Ask me anything about STAT 350 — I'll help you reason it out.",
  starterQuestions: [],
  modalities: ["flipped", "traditional", "indy", "online", "winter", "summer"],
  features: { digDeeper: false },
  maxMessageChars: 4000,
};

export type OwnKeyStatus = "none" | "validating" | "active" | "invalid";

interface AppState {
  config: AppConfig;
  configLoaded: boolean;
  configError: boolean;
  modality: Modality | null;
  profileLoaded: boolean;
  health: HealthStatus | null;
  online: boolean;
  ownKey: { status: OwnKeyStatus; message: string };
  /** Shared open-state for the Settings dialog so any component (e.g. the
   *  queue nudge) can open it, not just the sidebar footer button. */
  settingsOpen: boolean;

  loadConfig: () => Promise<void>;
  loadProfile: () => Promise<void>;
  setModality: (m: Modality | null) => Promise<void>;
  refreshHealth: () => Promise<void>;
  setOnline: (online: boolean) => void;
  validateOwnKey: (key: string) => Promise<boolean>;
  clearOwnKey: () => void;
  setSettingsOpen: (open: boolean) => void;
}

export const useAppStore = create<AppState>()((set) => ({
  config: FALLBACK_CONFIG,
  configLoaded: false,
  configError: false,
  modality: null,
  profileLoaded: false,
  health: null,
  online: typeof navigator === "undefined" ? true : navigator.onLine,
  ownKey: { status: ownKeyActive() ? "active" : "none", message: "" },
  settingsOpen: false,

  loadConfig: async () => {
    try {
      const config = await api.getConfig();
      set({ config, configLoaded: true, configError: false });
    } catch {
      set({ configLoaded: true, configError: true });
    }
  },

  loadProfile: async () => {
    try {
      const profile = await api.getProfile();
      set({ modality: profile.modality, profileLoaded: true });
    } catch {
      set({ profileLoaded: true });
    }
  },

  setModality: async (modality) => {
    const prev = useAppStore.getState().modality;
    set({ modality }); // optimistic
    try {
      await api.patchProfile(modality);
    } catch {
      set({ modality: prev });
    }
  },

  validateOwnKey: async (key) => {
    set({ ownKey: { status: "validating", message: "" } });
    try {
      const res = await api.validateKey(key.trim());
      if (res.usable) {
        saveOwnKey(key.trim(), true);
        trackEvent("own_key_set");
        set({ ownKey: { status: "active", message: res.message } });
        return true;
      }
      clearStoredKey(); // never store an unusable key
      set({ ownKey: { status: "invalid", message: res.message } });
      return false;
    } catch (e) {
      clearStoredKey();
      set({
        ownKey: {
          status: "invalid",
          message: e instanceof Error ? e.message : "Couldn't validate the key.",
        },
      });
      return false;
    }
  },

  clearOwnKey: () => {
    clearStoredKey();
    trackEvent("own_key_removed");
    set({ ownKey: { status: "none", message: "" } });
  },

  setSettingsOpen: (open) => set({ settingsOpen: open }),

  refreshHealth: async () => {
    try {
      const health = await api.getHealth();
      set({ health });
    } catch {
      set({ health: null });
    }
  },

  setOnline: (online) => set({ online }),
}));
