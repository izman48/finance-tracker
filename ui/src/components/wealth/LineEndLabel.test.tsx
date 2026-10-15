import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { lineEndLabel } from './LineEndLabel'

// ux T-11-2 "Lines on": each drawn line carries its name at its right end,
// so a line is never told apart by colour alone.
const render = (el: ReturnType<ReturnType<typeof lineEndLabel>>) =>
  renderToStaticMarkup(<svg>{el}</svg>)

describe('lineEndLabel', () => {
  const label = lineEndLabel('Property & other', '#F472B6', 11)

  it('names the line at its last point, in its colour', () => {
    const h = render(label({ x: 300, y: 40, index: 11 }))
    expect(h).toContain('Property &amp; other')
    expect(h).toContain('fill="#F472B6"')
    expect(h).toMatch(/x="306"/)
  })

  it('draws nothing at any other point', () => {
    expect(render(label({ x: 100, y: 40, index: 3 }))).toBe('<svg></svg>')
  })
})
