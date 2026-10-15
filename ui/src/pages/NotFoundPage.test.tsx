import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import NotFoundPage from './NotFoundPage'
import appSource from '../App.tsx?raw'

// T-12-12: a catch-all 404 page. sec: the path is rendered as text only.
const at = (path: string) => renderToStaticMarkup(
  <MemoryRouter initialEntries={[path]}>
    <Routes><Route path="*" element={<NotFoundPage />} /></Routes>
  </MemoryRouter>,
)

describe('NotFoundPage', () => {
  it('says the page was not found, names the path and links home', () => {
    const h = at('/no-such-page')
    expect(h).toContain('Page not found')
    expect(h).toContain('/no-such-page')
    expect(h).toContain('href="/home"')
  })

  it('renders the path as text, never markup', () => {
    const h = at('/x<img src=x onerror=alert(1)>')
    expect(h).not.toContain('<img')
  })

  it('the app routes every unknown path to it', () => {
    expect(appSource).toMatch(/<Route path="\*" element={<NotFoundPage \/>} \/>/)
  })
})
