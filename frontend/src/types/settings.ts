export interface GlobalSettings {
  llmBaseUrl: string;
  llmModel: string;
  asrProvider: string;
  asrBaseUrl: string;
  asrModel: string;
}
export interface LlmPreset {
  id: string;
  name: string;
  baseUrl: string;
  model: string;
}

export interface AsrPreset {
  id: string;
  name: string;
  provider: "qwen" | "whisper_api";
  baseUrl: string;
  model: string;
}

export interface ProviderPresets {
  llm: LlmPreset[];
  asr: AsrPreset[];
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
  asrProvider: "qwen",
  asrBaseUrl: "https://dashscope.aliyuncs.com",
  asrModel: "qwen3-asr-flash-filetrans",
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
    const parsed = JSON.parse(raw) as Partial<GlobalSettings> & {
      llmApiKey?: unknown;
      asrApiKey?: unknown;
    };
    const sanitized = {
      llmBaseUrl: parsed.llmBaseUrl ?? DEFAULT_GLOBAL_SETTINGS.llmBaseUrl,
      llmModel: parsed.llmModel ?? DEFAULT_GLOBAL_SETTINGS.llmModel,
      asrProvider: parsed.asrProvider ?? DEFAULT_GLOBAL_SETTINGS.asrProvider,
      asrBaseUrl: parsed.asrBaseUrl ?? DEFAULT_GLOBAL_SETTINGS.asrBaseUrl,
      asrModel: parsed.asrModel ?? DEFAULT_GLOBAL_SETTINGS.asrModel,
    };
    if ("llmApiKey" in parsed || "asrApiKey" in parsed) {
      saveSettingsToStorage(sanitized);
    }
    return sanitized;
  } catch {
    return { ...DEFAULT_GLOBAL_SETTINGS };
  }
}

export function saveSettingsToStorage(settings: GlobalSettings): void {
  localStorage.setItem("global_llm_settings", JSON.stringify(settings));
}
