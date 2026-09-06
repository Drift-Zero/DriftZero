/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_DEMO_MODE?: string
  readonly VITE_RECOVERY_API_KEY?: string
  readonly VITE_RECOVERY_ACTOR?: string
  readonly VITE_RECOVERY_ROLE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
