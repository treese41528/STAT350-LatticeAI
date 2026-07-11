import { create } from "zustand";
import * as api from "../api/client";
import type { HealthStatus } from "../api/client";
import type { AppConfig, Modality } from "../api/types";

export const MODALITY_LABELS: Record<Modality, string> = {
  flipped: "Flipped",
  traditional: "Traditional Lecture",
  indy: "Traditional (Indianapolis)",
  online: "Asynchronous Online",
  winter: "Winter Session",
};

const FALLBACK_CONFIG: AppConfig = {
  courseName: "STAT 350",
  term: "",
  welcome: "Ask me anything about STAT 350 — I'll help you reason it out.",
  starterQuestions: [],
  modalities: ["flipped", "traditional", "indy", "online", "winter"],
  features: { digDeeper: false },
  maxMessageChars: 4000,
};

interface AppState {
  config: AppConfig;
  configLoaded: boolean;
  configError: boolean;
  modality: Modality | null;
  profileLoaded: boolean;
  health: HealthStatus | null;
  online: boolean;

  loadConfig: () => Promise<void>;
  loadProfile: () => Promise<void>;
  setModality: (m: Modality | null) => Promise<void>;
  refreshHealth: () => Promise<void>;
  setOnline: (online: boolean) => void;
}

export const useAppStore = create<AppState>()((set) => ({
  config: FALLBACK_CONFIG,
  configLoaded: false,
  configError: false,
  modality: null,
  profileLoaded: false,
  health: null,
  online: typeof navigator === "undefined" ? true : navigator.onLine,

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
