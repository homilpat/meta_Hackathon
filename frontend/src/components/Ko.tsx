import { useEffect } from 'react'
import { request } from '../api/client'

// English record text shown in Korean on every screen (user 2026-11-04). After each render the English sentences in
// view are sent together to POST /translations: the model translates, the server keeps a translation only if its
// numbers and codes match the original. Records are unchanged; hovering shows the original. Quotes of a source
// document stay as written: mark them data-no-ko. A text is asked for once per page load.
const ENGLISH = /[A-Za-z][a-z]{2,}(?:[^A-Za-z가-힣]+[A-Za-z][a-z]+){2,}/
const done = new Map<string, string>()
const asked = new Set<string>()

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
        if (ko) { n.nodeValue = (n.nodeValue ?? '').replace(t, ko); n.parentElement?.setAttribute('title', `원문: ${t}`) }
        else if (!asked.has(t)) { asked.add(t); todo.push(t) }
      }
      for (let i = 0; i < todo.length; i += 40) {
        request(user, '/translations', 'POST', { texts: todo.slice(i, i + 40) })
          .then((j: { ko?: Record<string, string> }) => { Object.entries(j?.ko ?? {}).forEach(([t, k]) => done.set(t, k)); schedule() })
          .catch(() => { /* no translation: the original stays */ })
      }
    }
    const schedule = () => { clearTimeout(timer); timer = window.setTimeout(pass, 150) }
    const watch = new MutationObserver(schedule)
    watch.observe(document.body, { subtree: true, childList: true, characterData: true })
    schedule()
    return () => { watch.disconnect(); clearTimeout(timer) }
  }, [user, rootSelector])
}
