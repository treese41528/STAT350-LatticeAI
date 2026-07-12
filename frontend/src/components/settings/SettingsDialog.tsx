import { useState } from "react";
import clsx from "clsx";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { Spinner } from "../ui/Spinner";
import { useSettingsStore, applyTheme, type ThemeSetting } from "../../stores/settingsStore";
import { useAppStore, MODALITY_LABELS } from "../../stores/appStore";
import { resetDeviceId } from "../../lib/identity";
import { MonitorIcon, MoonIcon, SunIcon, KeyIcon, ShieldIcon, CheckIcon, AlertIcon } from "../ui/icons";
import styles from "./SettingsDialog.module.css";

const THEME_OPTIONS: { value: ThemeSetting; label: string; Icon: typeof SunIcon }[] = [
  { value: "system", label: "System", Icon: MonitorIcon },
  { value: "light", label: "Light", Icon: SunIcon },
  { value: "dark", label: "Dark", Icon: MoonIcon },
];

/** The "Use your own API key" section. Extracted so its own local input state
 *  resets cleanly when the dialog remounts. */
function OwnKeySection() {
  const status = useAppStore((s) => s.ownKey.status);
  const message = useAppStore((s) => s.ownKey.message);
  const validateOwnKey = useAppStore((s) => s.validateOwnKey);
  const clearOwnKey = useAppStore((s) => s.clearOwnKey);
  const [value, setValue] = useState("");
  const [showHow, setShowHow] = useState(false);

  const validating = status === "validating";
  const active = status === "active";

  const submit = async () => {
    const key = value.trim();
    if (key === "" || validating) return;
    const ok = await validateOwnKey(key);
    if (ok) setValue(""); // never keep the raw key in component state
  };

  return (
    <section className={styles.section}>
      <h3 className={styles.heading}>
        <KeyIcon size={14} /> Use your own API key
      </h3>
      <p className={styles.text}>
        Everyone shares the class API key, which allows only about 20 questions per minute across
        all students — so at busy times you'll wait in line. Adding your own free GenAI Studio key
        gives you your own quota and skips the queue. It's optional.
      </p>

      {active ? (
        <div className={styles.keyActive}>
          <span className={clsx(styles.badge, styles.badgeOk)}>
            <CheckIcon size={13} /> Your key is active
          </span>
          {message ? <span className={styles.badgeNote}>{message}</span> : null}
          <Button variant="outline" size="sm" onClick={clearOwnKey}>
            Remove key
          </Button>
        </div>
      ) : (
        <>
          <div className={styles.keyRow}>
            <input
              type="password"
              className={styles.keyInput}
              placeholder="Paste your GenAI Studio API key"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              value={value}
              disabled={validating}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submit();
              }}
              aria-label="Your GenAI Studio API key"
            />
            <Button
              size="sm"
              onClick={() => void submit()}
              disabled={value.trim() === "" || validating}
            >
              {validating ? <Spinner size={14} /> : "Validate & save"}
            </Button>
          </div>
          {status === "invalid" && message ? (
            <p className={clsx(styles.text, styles.keyError)}>
              <AlertIcon size={14} /> {message}
            </p>
          ) : null}
        </>
      )}

      <p className={styles.keyPrivacy}>
        <ShieldIcon size={13} /> Your key stays in this browser and is sent only to Purdue's GenAI
        Studio to answer your questions. It is never saved on our server, never logged, and never
        shown to your instructor.
      </p>

      <button
        type="button"
        className={styles.howToggle}
        aria-expanded={showHow}
        onClick={() => setShowHow((v) => !v)}
      >
        {showHow ? "Hide" : "How do I get a key?"}
      </button>

      {showHow && (
        <div className={styles.howBox}>
          <p className={styles.howStep}>
            <strong>Step 1: Access GenAI Studio</strong>
          </p>
          <ul className={styles.howList}>
            <li>
              Navigate to{" "}
              <a href="https://genai.rcac.purdue.edu" target="_blank" rel="noopener noreferrer">
                genai.rcac.purdue.edu
              </a>
            </li>
            <li>Log in with your Purdue credentials</li>
            <li>You'll see the OpenWebUI interface</li>
          </ul>
          <p className={styles.howStep}>
            <strong>Step 2: Generate an API Key</strong>
          </p>
          <ul className={styles.howList}>
            <li>Click your profile icon (top right)</li>
            <li>
              Go to <em>Settings → Account</em>
            </li>
            <li>
              Under <em>API Keys</em>, click <em>Create new secret key</em>
            </li>
            <li>Copy and save your API key securely</li>
          </ul>
        </div>
      )}
    </section>
  );
}

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
  const byokEnabled = useAppStore((s) => s.config.features.byok === true);
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

      {byokEnabled && <OwnKeySection />}

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
