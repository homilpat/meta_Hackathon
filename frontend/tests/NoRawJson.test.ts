import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// Screens show values through labels.show() and errors through api/client.readable(), never as raw JSON
// (2026-11-03). JSON.stringify is allowed only where data is sent or stored: a request body, a query parameter.
const ALLOWED = /body:|JSON\.stringify\(body\)|params\.set\(|JSON\.stringify\(mapping\)/

function files(dir: string): string[] {
  return readdirSync(dir).flatMap(f => statSync(join(dir, f)).isDirectory() ? files(join(dir, f)) : [join(dir, f)])
}

describe('screens', () => {
  it('never print raw JSON', () => {
    const hits = files('src').filter(f => /\.tsx?$/.test(f)).flatMap(f => readFileSync(f, 'utf8').split('\n')
      .map((line, i) => [f, i + 1, line] as const).filter(([, , line]) => line.includes('JSON.stringify') && !ALLOWED.test(line)))
    expect(hits.map(([f, n]) => `${f}:${n}`)).toEqual([])
  })
})
