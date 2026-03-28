import type { PublicConfigResponse } from "@/lib/types/public-config"

const ABSOLUTE_URL_RE = /^[a-zA-Z][a-zA-Z\d+\-.]*:/

export function resolveRuntimeUrl(
    value: string | null | undefined,
    origin: string,
): string | null {
    if (!value) return null

    const trimmed = value.trim()
    if (!trimmed) return null

    if (ABSOLUTE_URL_RE.test(trimmed)) {
        return trimmed
    }

    const relativePath = trimmed.startsWith("/")
        ? trimmed
        : `/${trimmed.replace(/^\/+/, "")}`
    return `${origin}${relativePath}`
}

export function resolveDrawioBaseUrl(
    config: Pick<PublicConfigResponse, "drawioBaseUrl"> | null | undefined,
    fallbackUrl: string,
    origin: string,
): string {
    return resolveRuntimeUrl(config?.drawioBaseUrl, origin) ?? fallbackUrl
}
