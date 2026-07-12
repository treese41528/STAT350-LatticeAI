import { useEffect } from "react";
import { AppShell } from "./components/shell/AppShell";
import { TooltipProvider } from "./components/ui/Tooltip";
import { useAppStore } from "./stores/appStore";
import { useChatStore } from "./stores/chatStore";
import { useSettingsStore, applyTheme } from "./stores/settingsStore";
import { installEventFlushHandlers } from "./api/events";

export default function App() {
  const loadConfig = useAppStore((s) => s.loadConfig);
  const loadProfile = useAppStore((s) => s.loadProfile);
  const loadConversations = useChatStore((s) => s.loadConversations);
  const theme = useSettingsStore((s) => s.theme);

  // Boot: config, profile, conversation list, analytics flush hooks.
  useEffect(() => {
    void loadConfig();
    void loadProfile();
    void loadConversations();
    installEventFlushHandlers();
  }, [loadConfig, loadProfile, loadConversations]);

  // Theme: apply on change; track OS preference while in "system".
  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  return (
    <TooltipProvider>
      <AppShell />
    </TooltipProvider>
  );
}
