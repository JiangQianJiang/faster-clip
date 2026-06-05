export interface GlobalSettings {
  llmBaseUrl: string;
  llmModel: string;
  llmApiKey: string;
  asrProvider: string;
  asrBaseUrl: string;
  asrModel: string;
  asrApiKey: string;
}

export interface ClipConfig {
  clipMinDuration: number;
  clipMaxDuration: number;
  bufferSeconds: number;
  burnSubtitle: boolean;
}

export const DEFAULT_GLOBAL_SETTINGS: GlobalSettings = {
  llmBaseUrl: "https://api.deepseek.com/anthropic",
  llmModel: "deepseek-v4-pro",
  llmApiKey: "",
  asrProvider: "qwen",
  asrBaseUrl: "https://dashscope.aliyuncs.com",
  asrModel: "qwen3-asr-flash-filetrans",
  asrApiKey: "",
};

export const DEFAULT_CLIP_CONFIG: ClipConfig = {
  clipMinDuration: 30,
  clipMaxDuration: 120,
  bufferSeconds: 3,
  burnSubtitle: false,
};

export function loadSettings(): GlobalSettings {
  try {
    const raw = localStorage.getItem("global_llm_settings");
    if (!raw) return { ...DEFAULT_GLOBAL_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<GlobalSettings>;
    return { ...DEFAULT_GLOBAL_SETTINGS, ...parsed };
  } catch {
    return { ...DEFAULT_GLOBAL_SETTINGS };
  }
}

export function saveSettingsToStorage(settings: GlobalSettings): void {
  localStorage.setItem("global_llm_settings", JSON.stringify(settings));
}
