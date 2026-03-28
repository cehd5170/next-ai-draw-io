export interface PublicConfigResponse {
    accessCodeRequired?: boolean
    dailyRequestLimit?: number
    dailyTokenLimit?: number
    tpmLimit?: number
    maxFileSize?: number
    maxFiles?: number
    maxImageSize?: number
    enableVlmValidation?: boolean
    drawioBaseUrl?: string | null
}
