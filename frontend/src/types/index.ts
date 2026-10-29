
export type Tone = 'teal' | 'green' | 'amber' | 'red' | 'blue' | 'slate' | 'violet'
export type J = any // eslint-disable-line @typescript-eslint/no-explicit-any

// Shared screen context: current case, user, API caller and refresh tick.
export type Ctx = { cid: string; me: J; api: (path: string, method?: string, body?: unknown, idem?: boolean) => Promise<J>; refresh: () => void; tick: number
  open: (cid: string, sel: string, screen?: string) => void; focus: string }
