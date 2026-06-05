import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import type { GlobalSettings } from "../types/settings";
import { loadSettings, saveSettingsToStorage } from "../types/settings";

interface SettingsContextValue {
  settings: GlobalSettings;
  saveSettings: (s: GlobalSettings) => void;
  isConfigured: boolean;
  isModalOpen: boolean;
  openSettings: () => void;
  closeSettings: () => void;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<GlobalSettings>(loadSettings);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const saveSettings = useCallback((s: GlobalSettings) => {
    saveSettingsToStorage(s);
    setSettings(s);
  }, []);

  const isConfigured = settings.llmApiKey.trim() !== "";

  const openSettings = useCallback(() => setIsModalOpen(true), []);
  const closeSettings = useCallback(() => setIsModalOpen(false), []);

  return (
    <SettingsContext.Provider
      value={{
        settings,
        saveSettings,
        isConfigured,
        isModalOpen,
        openSettings,
        closeSettings,
      }}
    >
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettingsContext(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) {
    throw new Error(
      "useSettingsContext must be used within a SettingsProvider"
    );
  }
  return ctx;
}
