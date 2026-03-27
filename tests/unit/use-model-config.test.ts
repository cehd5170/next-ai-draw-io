import { afterEach, describe, expect, it, vi } from "vitest"
import { getSelectedAIConfig } from "@/hooks/use-model-config"
import type { FlattenedModel } from "@/lib/types/model-config"
import { STORAGE_KEYS } from "@/lib/storage"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("getSelectedAIConfig", () => {
    it("prefers the live selected model over stale stored config", () => {
        const getItem = vi.fn((key: string) => {
            if (key === STORAGE_KEYS.accessCode) return "access-from-storage"
            if (key === STORAGE_KEYS.modelConfigs) {
                return JSON.stringify({
                    selectedModelId: "stale-model",
                })
            }
            if (key === "next-ai-draw-io-ai-provider") return "stale-provider"
            if (key === "next-ai-draw-io-ai-base-url") {
                return "https://stale.example/v1"
            }
            if (key === "next-ai-draw-io-ai-api-key") return "stale-key"
            if (key === "next-ai-draw-io-ai-model") return "stale-model-id"
            return null
        })

        vi.stubGlobal("window", {})
        vi.stubGlobal("localStorage", {
            getItem,
            setItem: vi.fn(),
            removeItem: vi.fn(),
        })

        const selectedModel: FlattenedModel = {
            id: "server:team-a:gpt-4o",
            modelId: "gpt-4o",
            provider: "openai",
            providerLabel: "Server · OpenAI",
            apiKey: "live-key",
            baseUrl: "https://live.example/v1",
            awsAccessKeyId: "aws-id",
            awsSecretAccessKey: "aws-secret",
            awsRegion: "us-east-1",
            awsSessionToken: "aws-token",
            vertexApiKey: "vertex-key",
            validated: true,
            source: "server",
            isDefault: true,
        }

        expect(getSelectedAIConfig(selectedModel)).toEqual({
            accessCode: "access-from-storage",
            aiProvider: "openai",
            aiBaseUrl: "https://live.example/v1",
            aiApiKey: "live-key",
            aiModel: "gpt-4o",
            awsAccessKeyId: "aws-id",
            awsSecretAccessKey: "aws-secret",
            awsRegion: "us-east-1",
            awsSessionToken: "aws-token",
            selectedModelId: "server:team-a:gpt-4o",
            vertexApiKey: "vertex-key",
        })
    })
})
