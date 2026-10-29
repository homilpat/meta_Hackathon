import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ApiError, request } from './api/client'
import { Badge, Card, Empty, Icon } from './components/ui'
import { USERS } from './constants'
import { Audit } from './features/audit/Audit'
import { Dashboard } from './features/dashboard/Dashboard'
import { Reports } from './features/documents/Reports'
import { EightD } from './features/eightd/EightD'
import { DataWorkspace } from './features/evidence/DataWorkspace'
import { HistoryScreen } from './features/history/HistoryScreen'
import { Impact } from './features/impact/Impact'
import { Investigation } from './features/investigation/Investigation'
import { Prediction } from './features/prediction/Prediction'
import { Queue } from './features/queue/Queue'
import { Spc } from './features/spc/Spc'
import type { Ctx, J } from './types'

// Every value on screen comes from the QualityOps API. Nothing here is a hard-coded result.
const nav = [
  ['dashboard', '개요', 'grid'], ['queue', '할 일', 'check'], ['eightd', 'D0~D8 진행', 'nodes'], ['spc', 'SPC 라인 모니터링', 'pulse'], ['data', '제조 데이터 · 증거', 'database'], ['prediction', '품질 예측 · XAI', 'chart'],
  ['investigation', 'AI 품질 조사', 'spark'], ['history', '과거 품질 사례', 'history'], ['reports', '문서 · 결재', 'document'],
  ['impact', '변경 영향 분석', 'nodes'], ['audit', '감사 · 보안', 'shield'],
] as const

export default function App() {
  const [active, setActive] = useState('dashboard')
  const [user, setUser] = useState('alice')
  const [cases, setCases] = useState<J[]>([])
  const [cid, setCid] = useState('')
  const [me, setMe] = useState<J>(null)
  const [provider, setProvider] = useState<J>(null)
  const [msg, setMsg] = useState('')
  const [tick, setTick] = useState(0)
  const [focus, setFocus] = useState('')

  const api = useCallback(async (path: string, method = 'GET', body?: unknown, idem = false) => {
    try {
      const j = await request(user, path, method, body, idem)
      if (method !== 'GET') setMsg('')
      return j
    } catch (e) {
      if (e instanceof ApiError) { if (method !== 'GET') setMsg(e.message); throw new Error(String(e.status)) }
      throw e
    }
  }, [user])
  const refresh = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => { fetch('/provider').then(r => r.json()).then(setProvider).catch(() => setProvider(null)) }, [])
  useEffect(() => {
    api('/me').then(setMe).catch(() => setMe(null))
    api('/cases').then((cs: J[]) => { setCases(cs); setCid(c => cs.some(x => x.case_id === c) ? c : cs[cs.length - 1]?.case_id ?? '') }).catch(() => setCases([]))
  }, [api, tick])

  const newCase = async (line: boolean) => {
    const id = `${line ? 'SMT' : 'PCB'}-${Date.now().toString(36).toUpperCase()}`
    await api('/cases', 'POST', { case_id: id })
    await api(`/cases/${id}/sources`, 'POST', await (await fetch(line ? '/synthetic/line/7' : '/synthetic/7')).json())
    for (const u of ['bob', 'erin', 'frank']) await api(`/cases/${id}/assignments`, 'POST', { user_id: u })
    setCid(id); refresh()
  }

  const open = useCallback((c: string, sel: string, screen = 'reports') => { setCid(c); setFocus(sel); setActive(screen); refresh() }, [refresh])
  const ctx: Ctx = { cid, me, api, refresh, tick, open, focus }
  const screens: Record<string, ReactNode> = {
    dashboard: <Dashboard ctx={ctx} cases={cases} onNew={newCase}/>, queue: <Queue ctx={ctx}/>, eightd: <EightD ctx={ctx}/>, spc: <Spc ctx={ctx}/>, data: <DataWorkspace ctx={ctx}/>, prediction: <Prediction ctx={ctx}/>,
    investigation: <Investigation ctx={ctx} provider={provider}/>, history: <HistoryScreen ctx={ctx}/>, reports: <Reports ctx={ctx}/>, impact: <Impact ctx={ctx}/>, audit: <Audit ctx={ctx}/>,
  }
  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><span/><span/><span/></div><div><b>QualityOps</b><small>AI</small></div></div>
      <label className="site-select"><span><small>현재 사건</small><select value={cid} onChange={e => setCid(e.target.value)}>{cases.map(c => <option key={c.case_id}>{c.case_id}</option>)}{!cases.length && <option value="">배정된 사건 없음</option>}</select></span></label>
      <nav>{nav.map(n => <button key={n[0]} className={active === n[0] ? 'active' : ''} onClick={() => { setFocus(''); setActive(n[0]) }}><Icon name={n[2]}/><span>{n[1]}</span>{n[0] === 'investigation' && <i>AI</i>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="status-live"><i className={provider?.configured ? '' : 'off'}/><span><b>Meta · {provider?.model ?? '-'}</b><small>{provider?.live_status === 'VERIFIED' ? 'LIVE 호출 검증됨' : provider?.configured ? '키 설정됨 · LIVE 미검증' : '키 없음 · 호출 불가'}</small></span></div></div>
    </aside>
    <div className="shell">
      <header><div className="breadcrumb"><span>QualityOps AI</span><Icon name="chevron" size={13}/><b>{nav.find(x => x[0] === active)?.[1]}</b></div>
        <div className="header-actions"><Badge tone="blue">SYNTHETIC 데이터</Badge>
          <label className="user"><div className="avatar">{user[0].toUpperCase()}</div><span><small>데모 사용자 (X-User, 비밀번호 없음)</small><select value={user} onChange={e => setUser(e.target.value)}>{USERS.map(u => <option key={u[0]} value={u[0]}>{u[1]}</option>)}</select></span></label></div></header>
      {msg && <div className="error-bar" onClick={() => setMsg('')}>{msg}</div>}
      {cid || active === 'dashboard' || active === 'spc' ? screens[active] : <main className="page"><Card><Empty>배정된 사건이 없습니다.</Empty></Card></main>}
    </div>
  </div>
}
