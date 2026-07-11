import { useSettingsStore, applyTheme, type ThemeSetting } from "../../stores/settingsStore";
import { IconButton } from "../ui/IconButton";
import { MonitorIcon, MoonIcon, SunIcon } from "../ui/icons";

const NEXT: Record<ThemeSetting, ThemeSetting> = {
  system: "light",
  light: "dark",
  dark: "system",
};

const LABELS: Record<ThemeSetting, string> = {
  system: "Theme: system (click for light)",
  light: "Theme: light (click for dark)",
  dark: "Theme: dark (click for system)",
};

export function ThemeToggle() {
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);

  const cycle = () => {
    const next = NEXT[theme];
    setTheme(next);
    applyTheme(next);
  };

  const Icon = theme === "light" ? SunIcon : theme === "dark" ? MoonIcon : MonitorIcon;

  return (
    <IconButton variant="topbar" label={LABELS[theme]} onClick={cycle}>
      <Icon size={18} />
    </IconButton>
  );
}
