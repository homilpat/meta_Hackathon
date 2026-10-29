import { useEffect, useState } from 'react'
import type { Ctx } from '../types'

export function useLoad<T>(ctx: Ctx, path: string | null, init: T): T {
  const [v, setV] = useState<T>(init)
  useEffect(() => { // reload per user/case; ignore a late answer from a previous user or case
    let live = true
    if (path) ctx.api(path).then(x => live && setV(x)).catch(() => live && setV(init))
    return () => { live = false }
  }, [path, ctx.tick, ctx.api]) // eslint-disable-line react-hooks/exhaustive-deps
  return v
}
