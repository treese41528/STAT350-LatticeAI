import { useState } from "react";
import clsx from "clsx";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { useSettingsStore, applyTheme, type ThemeSetting } from "../../stores/settingsStore";
import { useAppStore, MODALITY_LABELS } from "../../stores/appStore";
import { resetDeviceId } from "../../lib/identity";
import { MonitorIcon, MoonIcon, SunIcon } from "../ui/icons";
import styles from "./SettingsDialog.module.css";

const THEME_OPTIONS: { value: ThemeSetting; label: string; Icon: typeof SunIcon }[] = [
  { value: "system", label: "System", Icon: MonitorIcon },
  { value: "light", label: "Light", Icon: SunIcon },
  { value: "dark", label: "Dark", Icon: MoonIcon },
];

export function SettingsDialog({
  open,
  onOpenChange,
  onOpenModality,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenModality: () => void;
}) {
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);
  const modality = useAppStore((s) => s.modality);
  const config = useAppStore((s) => s.config);
  const [confirmClear, setConfirmClear] = useState(false);

  const pickTheme = (t: ThemeSetting) => {
    setTheme(t);
    applyTheme(t);
  };

  const clearData = async () => {
    // await the server cookie reset BEFORE reload, else the surviving cookie
    // mismatches the new device id and locks the user out.
    await resetDeviceId();
    try {
      localStorage.removeItem("stat350.settings");
      sessionStorage.clear();
    } catch {
      /* storage unavailable */
    }
    window.location.reload();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Settings" wide>
      <section className={styles.section}>
        <h3 className={styles.heading}>Appearance</h3>
        <div className={styles.themeRow} role="radiogroup" aria-label="Theme">
          {THEME_OPTIONS.map(({ value, label, Icon }) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={theme === value}
              className={clsx(styles.themeOption, theme === value && styles.themeOn)}
              onClick={() => pickTheme(value)}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <h3 className={styles.heading}>Course section</h3>
        <p className={styles.text}>
          {modality
            ? `You're set as ${MODALITY_LABELS[modality]}.`
            : "Not set — syllabus and schedule answers will ask which section you're in."}
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            onOpenChange(false);
            onOpenModality();
          }}
        >
          Change section
        </Button>
      </section>

      <section className={styles.section}>
        <h3 className={styles.heading}>Privacy</h3>
        <p className={styles.text}>
          Conversations are linked to an anonymous id stored on this device. Clearing it starts you
          fresh — your existing conversations will no longer be reachable from this browser.
        </p>
        {confirmClear ? (
          <div className={styles.confirmRow}>
            <span className={styles.confirmText}>Are you sure?</span>
            <Button variant="danger" size="sm" onClick={clearData}>
              Yes, clear my data
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmClear(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button variant="outline" size="sm" onClick={() => setConfirmClear(true)}>
            Clear my data on this device
          </Button>
        )}
      </section>

      <section className={styles.section}>
        <h3 className={styles.heading}>About</h3>
        <p className={styles.text}>
          {config.courseName} Tutor{config.term ? ` · ${config.term}` : ""} — a Socratic study
          companion grounded in the course webbook and lecture transcripts. It guides you toward
          answers instead of handing them over, and it cites its sources. Always verify against the
          course website; policies there are canonical.
        </p>
      </section>
    </Dialog>
  );
}
