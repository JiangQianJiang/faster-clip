import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getApiSettings, saveApiSettings } from "./client";

describe("api settings client", () => {
  beforeEach(() => {
    const storage = new Map<string, string>();
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads server api settings without plaintext keys", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          llm_base_url: "https://llm.example.com",
          llm_model: "llm-model",
          llm_api_key_configured: true,
          asr_provider: "qwen",
          asr_base_url: "https://asr.example.com",
          asr_model: "asr-model",
          asr_api_key_configured: false,
        }),
        { status: 200 },
      ),
    );

    const settings = await getApiSettings();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/api",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
    expect(settings).toEqual({
      llmBaseUrl: "https://llm.example.com",
      llmModel: "llm-model",
      llmApiKeyConfigured: true,
      asrProvider: "qwen",
      asrBaseUrl: "https://asr.example.com",
      asrModel: "asr-model",
      asrApiKeyConfigured: false,
    });
    expect(JSON.stringify(settings)).not.toContain("secret");
  });

  it("saves server api settings with optional replacement keys", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          llm_base_url: "https://llm.example.com",
          llm_model: "llm-model",
          llm_api_key_configured: true,
          asr_provider: "whisper_api",
          asr_base_url: "https://asr.example.com",
          asr_model: "asr-model",
          asr_api_key_configured: true,
        }),
        { status: 200 },
      ),
    );

    await saveApiSettings({
      llmBaseUrl: "https://llm.example.com",
      llmModel: "llm-model",
      llmApiKey: "new-llm-key",
      asrProvider: "whisper_api",
      asrBaseUrl: "https://asr.example.com",
      asrModel: "asr-model",
      asrApiKey: "",
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [_url, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({
      llm_base_url: "https://llm.example.com",
      llm_model: "llm-model",
      llm_api_key: "new-llm-key",
      asr_provider: "whisper_api",
      asr_base_url: "https://asr.example.com",
      asr_model: "asr-model",
      asr_api_key: "",
    });
  });
});
