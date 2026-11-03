import { useEffect } from 'react'
import { request } from '../api/client'

// English record text shown in Korean on every screen (user 2026-11-04). After each render the English sentences in
// view are sent together to POST /translations: the model translates, the server keeps a translation only if its
// numbers and codes match the original. Records are unchanged; hovering shows the original. Quotes of a source
// document stay as written: mark them data-no-ko. A text is asked for once per page load.
const ENGLISH = /[A-Za-z][a-z]{2,}(?:[^A-Za-z가-힣]+[A-Za-z][a-z]+){2,}/
const done = new Map<string, string>()
const asked = new Map<string, number>()  // when it was asked
const failed = new Set<string>()  // no translation passed the check: the original is shown
const WAIT_MS = 8000  // a sentence waiting longer is shown as written

// Hidden while its translation is on the way, so the screen never flips from English to Korean in view
const hide = (el: HTMLElement | null, on: boolean) => { if (el) el.style.visibility = on ? 'hidden' : '' }

function textNodes(root: Element): Text[] {
  const out: Text[] = []
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: n =>
    n.parentElement?.closest('[data-no-ko],script,style,textarea,select,option') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT })
  while (walk.nextNode()) out.push(walk.currentNode as Text)
  return out
}

export function useScreenKorean(user: string, rootSelector = '.shell') {
  useEffect(() => {
    let timer = 0
    const pass = () => {
      const root = document.querySelector(rootSelector)
      if (!root) return
      const todo: string[] = []
      for (const n of textNodes(root)) {
        const t = (n.nodeValue ?? '').trim()
        if (!ENGLISH.test(t)) continue
        const ko = done.get(t)
        if (ko) { n.nodeValue = (n.nodeValue ?? '').replace(t, ko); n.parentElement?.setAttribute('title', `원문: ${t}`); hide(n.parentElement, false) }
        else if (failed.has(t) || Date.now() - (asked.get(t) ?? Date.now()) > WAIT_MS) { failed.add(t); hide(n.parentElement, false) }
        else { hide(n.parentElement, true); if (!asked.has(t)) { asked.set(t, Date.now()); todo.push(t); window.setTimeout(schedule, WAIT_MS + 100) } }
      }
      for (let i = 0; i < todo.length; i += 40) {
        const batch = todo.slice(i, i + 40)
        request(user, '/translations', 'POST', { texts: batch })
          .then((j: { ko?: Record<string, string> }) => { Object.entries(j?.ko ?? {}).forEach(([t, k]) => done.set(t, k)) })
          .catch(() => { /* no translation: the original stays */ })
          .finally(() => { batch.forEach(t => { if (!done.has(t)) failed.add(t) }); schedule() })
      }
    }
    const schedule = () => { clearTimeout(timer); timer = window.setTimeout(pass, 150) }
    const watch = new MutationObserver(schedule)
    watch.observe(document.body, { subtree: true, childList: true, characterData: true })
    schedule()
    return () => { watch.disconnect(); clearTimeout(timer) }
  }, [user, rootSelector])
}
