import type { NextConfig } from "next"
import packageJson from "./package.json"

const nextConfig: NextConfig = {
    /* config options here */
    output: "standalone",
    // Support for subdirectory deployment (e.g., https://example.com/nextaidrawio)
    // Set NEXT_PUBLIC_BASE_PATH environment variable to your subdirectory path (e.g., /nextaidrawio)
    basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
    env: {
        APP_VERSION: packageJson.version,
    },
    // Include instrumentation.ts in standalone build for Langfuse telemetry
    outputFileTracingIncludes: {
        "*": ["./instrumentation.ts"],
    },
    // Proxy /api/* to the Python backend.
    // PYTHON_API_URL is required — the frontend has no local API routes;
    // all API logic lives in the FastAPI backend.
    async rewrites() {
        const pythonApiUrl = process.env.PYTHON_API_URL
        if (!pythonApiUrl) {
            throw new Error(
                "PYTHON_API_URL environment variable is required. " +
                    "The frontend has no local API routes — all API requests " +
                    "are proxied to the Python backend. Set PYTHON_API_URL " +
                    "(e.g. http://backend:8000) in your environment or docker-compose.",
            )
        }
        return [
            {
                source: "/api/:path*",
                destination: `${pythonApiUrl}/api/:path*`,
            },
        ]
    },
}

export default nextConfig

// Initialize OpenNext Cloudflare for local development only
// This must be a dynamic import to avoid loading workerd binary during builds
if (process.env.NODE_ENV === "development") {
    import("@opennextjs/cloudflare").then(
        ({ initOpenNextCloudflareForDev }) => {
            initOpenNextCloudflareForDev()
        },
    )
}
