import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ExperienceCard } from '../src/features/experience/ExperienceCard'

const xp = { latest: { retrieval_id: 7, mode: 'KNOWN', choices: ['REVIEW_PRIOR_RESPONSE', 'INVESTIGATE_MORE'],
  matches: [{ entry_key: 'K1', mode: 'KNOWN', role: 'PRIOR_RESPONSE', action: 'clean stencil', outcome: 'EFFECTIVE', recurrence: 'NONE',
    matched_factors: [], differing_factors: [], warnings: [] }] }, decisions: [] }

function Harness({ api }: { api: (...a: unknown[]) => Promise<unknown> }) {
  const [f, setF] = useState<Record<string, string>>({ whyx: '', htext: '' })
  const set = (k: string) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }))
  return <ExperienceCard xp={xp} cid="L" api={api as never} run={p => p} role="AUTHOR" f={f} set={set}/>
}

afterEach(cleanup)

describe('ExperienceCard', () => {
  it('sends only the reason the person typed; no reason, no choice', () => {
    const api = vi.fn(async () => ({}))
    render(<Harness api={api}/>)
    const choice = screen.getByText('더 조사') as HTMLButtonElement
    expect(choice.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('선택 사유'), { target: { value: '   ' } })
    expect(choice.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('선택 사유'), { target: { value: '스텐실 조건이 달라 추가 조사' } })
    fireEvent.click(choice)
    expect(api).toHaveBeenCalledWith('/cases/L/experience/decisions', 'POST',
      { retrieval_id: 7, entry_key: 'K1', decision: 'INVESTIGATE_MORE', reason: '스텐실 조건이 달라 추가 조사' })
  })
})
