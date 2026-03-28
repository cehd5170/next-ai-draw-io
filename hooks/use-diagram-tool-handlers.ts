import type { MutableRefObject } from "react"
import type { DiagramOperation } from "@/components/chat/types"
import type {
    ValidationState,
    ValidationStatus,
} from "@/components/chat/ValidationCard"
import type { ValidationResult } from "@/lib/diagram-validator"
import { formatValidationFeedback } from "@/lib/diagram-validator"
import { isMxCellXmlComplete, prepareDiagramXmlForDisplay } from "@/lib/utils"

const DEBUG = process.env.NODE_ENV === "development"

interface ToolCall {
    toolCallId: string
    toolName: string
    input: unknown
}

type AddToolOutputSuccess = {
    tool: string
    toolCallId: string
    state?: "output-available"
    output: string
    errorText?: undefined
}

type AddToolOutputError = {
    tool: string
    toolCallId: string
    state: "output-error"
    output?: undefined
    errorText: string
}

type AddToolOutputParams = AddToolOutputSuccess | AddToolOutputError

type AddToolOutputFn = (params: AddToolOutputParams) => void

const MAX_VALIDATION_RETRIES = 3
const VALIDATION_CAPTURE_TIMEOUT_MS = 4000
const VALIDATION_REQUEST_TIMEOUT_MS = 8000

// Type for the validation function passed from useValidateDiagram hook
type ValidateDiagramFn = (
    imageData: string,
    sessionId?: string,
) => Promise<ValidationResult>

interface UseDiagramToolHandlersParams {
    partialXmlRef: MutableRefObject<string>
    editDiagramOriginalXmlRef: MutableRefObject<Map<string, string>>
    chartXMLRef: MutableRefObject<string>
    onDisplayChart: (xml: string, skipValidation?: boolean) => string | null
    onFetchChart: (saveToHistory?: boolean) => Promise<string>
    onExport: () => void
    captureValidationPng?: () => Promise<string | null>
    validateDiagram?: ValidateDiagramFn
    enableVlmValidation?: boolean
    sessionId?: string
    onValidationStateChange?: (
        toolCallId: string,
        state: ValidationState,
    ) => void
}

/**
 * Hook that creates the onToolCall handler for diagram-related tools.
 * Handles display_diagram, edit_diagram, and append_diagram tools.
 *
 * Note: addToolOutput is passed at call time (not hook init) because
 * it comes from useChat which creates a circular dependency.
 */
export function useDiagramToolHandlers({
    partialXmlRef,
    editDiagramOriginalXmlRef,
    chartXMLRef,
    onDisplayChart,
    onFetchChart,
    onExport,
    captureValidationPng,
    validateDiagram,
    enableVlmValidation = true,
    sessionId,
    onValidationStateChange,
}: UseDiagramToolHandlersParams) {
    const withTimeout = async <T>(
        promise: Promise<T>,
        timeoutMs: number,
        label: string,
    ): Promise<T> => {
        let timeoutId: ReturnType<typeof setTimeout> | null = null
        try {
            return await Promise.race([
                promise,
                new Promise<T>((_, reject) => {
                    timeoutId = setTimeout(() => {
                        reject(
                            new Error(
                                `${label} timed out after ${timeoutMs}ms`,
                            ),
                        )
                    }, timeoutMs)
                }),
            ])
        } finally {
            if (timeoutId) {
                clearTimeout(timeoutId)
            }
        }
    }

    // Helper to update validation state
    const updateValidationState = (
        toolCallId: string,
        status: ValidationStatus,
        options?: {
            attempt?: number
            maxAttempts?: number
            result?: ValidationResult
            error?: string
            imageData?: string
        },
    ) => {
        if (onValidationStateChange) {
            onValidationStateChange(toolCallId, {
                status,
                ...options,
            })
        }
    }
    const handleToolCall = async (
        { toolCall }: { toolCall: ToolCall },
        addToolOutput: AddToolOutputFn,
    ) => {
        if (DEBUG) {
            console.log(
                `[onToolCall] Tool: ${toolCall.toolName}, CallId: ${toolCall.toolCallId}`,
            )
        }

        if (toolCall.toolName === "display_diagram") {
            await handleDisplayDiagram(toolCall, addToolOutput)
        } else if (toolCall.toolName === "edit_diagram") {
            await handleEditDiagram(toolCall, addToolOutput)
        } else if (toolCall.toolName === "append_diagram") {
            handleAppendDiagram(toolCall, addToolOutput)
        }
    }

    const handleDisplayDiagram = async (
        toolCall: ToolCall,
        addToolOutput: AddToolOutputFn,
    ) => {
        const { xml } = toolCall.input as { xml: string }

        // DEBUG: Log raw input to diagnose false truncation detection
        if (DEBUG) {
            console.log(
                "[display_diagram] XML ending (last 100 chars):",
                xml.slice(-100),
            )
            console.log("[display_diagram] XML length:", xml.length)
        }

        // Check if XML is truncated (incomplete mxCell indicates truncated output)
        const isTruncated = !isMxCellXmlComplete(xml)
        if (DEBUG) {
            console.log("[display_diagram] isTruncated:", isTruncated)
        }

        if (isTruncated) {
            // Store the partial XML for continuation via append_diagram
            partialXmlRef.current = xml

            // Tell LLM to use append_diagram to continue
            const partialEnding = partialXmlRef.current.slice(-500)
            addToolOutput({
                tool: "display_diagram",
                toolCallId: toolCall.toolCallId,
                state: "output-error",
                errorText: `Output was truncated due to length limits. Use the append_diagram tool to continue.

Your output ended with:
\`\`\`
${partialEnding}
\`\`\`

NEXT STEP: Call append_diagram with the continuation XML.
- Do NOT include wrapper tags or root cells (id="0", id="1")
- Start from EXACTLY where you stopped
- Complete all remaining mxCell elements`,
            })
            return
        }

        // Complete XML received - use it directly
        // (continuation is now handled via append_diagram tool)
        const finalXml = xml
        partialXmlRef.current = "" // Reset any partial from previous truncation

        const prepared = prepareDiagramXmlForDisplay(finalXml)

        if (!prepared.valid) {
            console.warn("[display_diagram] Validation error:", prepared.error)
            // Return error to model - sendAutomaticallyWhen will trigger retry
            if (DEBUG) {
                console.log(
                    "[display_diagram] Adding tool output with state: output-error",
                )
            }
            addToolOutput({
                tool: "display_diagram",
                toolCallId: toolCall.toolCallId,
                state: "output-error",
                errorText: `${prepared.error}

Please fix the XML issues and call display_diagram again with corrected XML.

Your failed XML:
\`\`\`xml
${finalXml}
\`\`\``,
            })
        } else {
            // Success - diagram will be rendered by chat-message-display
            if (DEBUG) {
                console.log(
                    "[display_diagram] Success! Returning tool output immediately.",
                )
            }

            onDisplayChart(prepared.xml, true)
            addToolOutput({
                tool: "display_diagram",
                toolCallId: toolCall.toolCallId,
                output: "Successfully displayed the diagram.",
            })

            // VLM validation runs in the background so the tool round-trip
            // does not stall the chat UI after the diagram is already visible.
            if (
                enableVlmValidation &&
                captureValidationPng &&
                validateDiagram
            ) {
                void (async () => {
                    let capturedPngData: string | null = null
                    try {
                        updateValidationState(toolCall.toolCallId, "capturing")

                        await new Promise((resolve) => setTimeout(resolve, 100))

                        capturedPngData = await withTimeout(
                            captureValidationPng(),
                            VALIDATION_CAPTURE_TIMEOUT_MS,
                            "Diagram capture",
                        )
                        if (!capturedPngData) {
                            updateValidationState(
                                toolCall.toolCallId,
                                "skipped",
                            )
                            return
                        }

                        if (DEBUG) {
                            console.log(
                                "[display_diagram] Captured PNG for background validation",
                            )
                        }

                        updateValidationState(
                            toolCall.toolCallId,
                            "validating",
                            {
                                attempt: 1,
                                maxAttempts: MAX_VALIDATION_RETRIES,
                                imageData: capturedPngData,
                            },
                        )

                        const result = await withTimeout(
                            validateDiagram(capturedPngData, sessionId),
                            VALIDATION_REQUEST_TIMEOUT_MS,
                            "Diagram validation",
                        )

                        if (!result.valid) {
                            if (DEBUG) {
                                console.log(
                                    "[display_diagram] Background validation found issues:",
                                    formatValidationFeedback(result),
                                )
                            }
                            updateValidationState(
                                toolCall.toolCallId,
                                "failed",
                                {
                                    attempt: 1,
                                    maxAttempts: MAX_VALIDATION_RETRIES,
                                    result,
                                    imageData: capturedPngData,
                                },
                            )
                            return
                        }

                        const hasWarnings = result.issues.length > 0
                        updateValidationState(
                            toolCall.toolCallId,
                            hasWarnings ? "success_with_warnings" : "success",
                            { result, imageData: capturedPngData },
                        )
                    } catch (error) {
                        console.warn(
                            "[display_diagram] VLM validation error:",
                            error,
                        )
                        const message =
                            error instanceof Error
                                ? error.message
                                : "Validation failed"
                        const timedOut = message
                            .toLowerCase()
                            .includes("timed out")
                        updateValidationState(
                            toolCall.toolCallId,
                            timedOut ? "skipped" : "error",
                            timedOut
                                ? { imageData: capturedPngData || undefined }
                                : {
                                      error: message,
                                      imageData: capturedPngData || undefined,
                                  },
                        )
                    }
                })()
            }
        }
    }

    const handleEditDiagram = async (
        toolCall: ToolCall,
        addToolOutput: AddToolOutputFn,
    ) => {
        const { operations } = toolCall.input as {
            operations: DiagramOperation[]
        }

        let currentXml = ""
        try {
            // Use the original XML captured during streaming (shared with chat-message-display)
            // This ensures we apply operations to the same base XML that streaming used
            const originalXml = editDiagramOriginalXmlRef.current.get(
                toolCall.toolCallId,
            )
            if (originalXml) {
                currentXml = originalXml
            } else {
                // Fallback: use chartXML from ref if streaming didn't capture original
                const cachedXML = chartXMLRef.current
                if (cachedXML) {
                    currentXml = cachedXML
                } else {
                    // Last resort: export from iframe
                    currentXml = await onFetchChart(false)
                }
            }

            const { applyDiagramOperations } = await import("@/lib/utils")
            const { result: editedXml, errors } = applyDiagramOperations(
                currentXml,
                operations,
            )

            // Check for operation errors
            if (errors.length > 0) {
                const errorMessages = errors
                    .map(
                        (e) =>
                            `- ${e.type} on cell_id="${e.cellId}": ${e.message}`,
                    )
                    .join("\n")

                addToolOutput({
                    tool: "edit_diagram",
                    toolCallId: toolCall.toolCallId,
                    state: "output-error",
                    errorText: `Some operations failed:\n${errorMessages}

Current diagram XML:
\`\`\`xml
${currentXml}
\`\`\`

Please check the cell IDs and retry.`,
                })
                // Clean up the shared original XML ref
                editDiagramOriginalXmlRef.current.delete(toolCall.toolCallId)
                return
            }

            // loadDiagram validates and returns error if invalid
            const validationError = onDisplayChart(editedXml)
            if (validationError) {
                console.warn(
                    "[edit_diagram] Validation error:",
                    validationError,
                )
                addToolOutput({
                    tool: "edit_diagram",
                    toolCallId: toolCall.toolCallId,
                    state: "output-error",
                    errorText: `Edit produced invalid XML: ${validationError}

Current diagram XML:
\`\`\`xml
${currentXml}
\`\`\`

Please fix the operations to avoid structural issues.`,
                })
                // Clean up the shared original XML ref
                editDiagramOriginalXmlRef.current.delete(toolCall.toolCallId)
                return
            }
            onExport()
            addToolOutput({
                tool: "edit_diagram",
                toolCallId: toolCall.toolCallId,
                output: `Successfully applied ${operations.length} operation(s) to the diagram.`,
            })
            // Clean up the shared original XML ref
            editDiagramOriginalXmlRef.current.delete(toolCall.toolCallId)
        } catch (error) {
            console.error("[edit_diagram] Failed:", error)

            const errorMessage =
                error instanceof Error ? error.message : String(error)

            addToolOutput({
                tool: "edit_diagram",
                toolCallId: toolCall.toolCallId,
                state: "output-error",
                errorText: `Edit failed: ${errorMessage}

Current diagram XML:
\`\`\`xml
${currentXml || "No XML available"}
\`\`\`

Please check cell IDs and retry, or use display_diagram to regenerate.`,
            })
            // Clean up the shared original XML ref even on error
            editDiagramOriginalXmlRef.current.delete(toolCall.toolCallId)
        }
    }

    const handleAppendDiagram = (
        toolCall: ToolCall,
        addToolOutput: AddToolOutputFn,
    ) => {
        const { xml } = toolCall.input as { xml: string }

        // Detect if LLM incorrectly started fresh instead of continuing
        // LLM should only output bare mxCells now, so wrapper tags indicate error
        const trimmed = xml.trim()
        const isFreshStart =
            trimmed.startsWith("<mxGraphModel") ||
            trimmed.startsWith("<root") ||
            trimmed.startsWith("<mxfile") ||
            trimmed.startsWith('<mxCell id="0"') ||
            trimmed.startsWith('<mxCell id="1"')

        if (isFreshStart) {
            addToolOutput({
                tool: "append_diagram",
                toolCallId: toolCall.toolCallId,
                state: "output-error",
                errorText: `ERROR: You started fresh with wrapper tags. Do NOT include wrapper tags or root cells (id="0", id="1").

Continue from EXACTLY where the partial ended:
\`\`\`
${partialXmlRef.current.slice(-500)}
\`\`\`

Start your continuation with the NEXT character after where it stopped.`,
            })
            return
        }

        // Append to accumulated XML
        partialXmlRef.current += xml

        // Check if XML is now complete (last mxCell is complete)
        const isComplete = isMxCellXmlComplete(partialXmlRef.current)

        if (isComplete) {
            // Wrap and display the complete diagram
            const finalXml = partialXmlRef.current
            partialXmlRef.current = "" // Reset

            const prepared = prepareDiagramXmlForDisplay(finalXml)

            if (!prepared.valid) {
                addToolOutput({
                    tool: "append_diagram",
                    toolCallId: toolCall.toolCallId,
                    state: "output-error",
                    errorText: `Validation error after assembly: ${prepared.error}

Assembled XML:
\`\`\`xml
${finalXml.substring(0, 2000)}...
\`\`\`

Please use display_diagram with corrected XML.`,
                })
            } else {
                onDisplayChart(prepared.xml, true)
                addToolOutput({
                    tool: "append_diagram",
                    toolCallId: toolCall.toolCallId,
                    output: "Diagram assembly complete and displayed successfully.",
                })
            }
        } else {
            // Still incomplete - signal to continue
            addToolOutput({
                tool: "append_diagram",
                toolCallId: toolCall.toolCallId,
                state: "output-error",
                errorText: `XML still incomplete (mxCell not closed). Call append_diagram again to continue.

Current ending:
\`\`\`
${partialXmlRef.current.slice(-500)}
\`\`\`

Continue from EXACTLY where you stopped.`,
            })
        }
    }

    return { handleToolCall }
}
