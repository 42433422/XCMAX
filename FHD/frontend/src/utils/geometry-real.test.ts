import { describe, it, expect } from 'vitest'
import {
  createTetrahedron,
  createOctahedron,
  createIcosahedron,
  createDodecahedron,
} from './geometry-real'

describe('geometry-real polyhedra', () => {
  it('createTetrahedron has 4 vertices and 4 faces', () => {
    const t = createTetrahedron(50)
    expect(t.vertices).toHaveLength(4)
    expect(t.faces).toHaveLength(4)
    t.vertices.forEach((v) => {
      const len = Math.hypot(v[0], v[1], v[2])
      expect(len).toBeCloseTo(50, 1)
    })
  })

  it('createOctahedron has 6 vertices and 8 faces', () => {
    const o = createOctahedron(80)
    expect(o.vertices).toHaveLength(6)
    expect(o.faces).toHaveLength(8)
  })

  it('createIcosahedron has 12 vertices and 20 faces', () => {
    const i = createIcosahedron(100)
    expect(i.vertices).toHaveLength(12)
    expect(i.faces).toHaveLength(20)
    i.faces.forEach((f) => {
      expect(f.normal.length).toBe(3)
      const nlen = Math.hypot(f.normal[0], f.normal[1], f.normal[2])
      expect(nlen).toBeCloseTo(1, 5)
    })
  })

  it('createDodecahedron derives from icosahedron', () => {
    const d = createDodecahedron(60)
    expect(d.vertices.length).toBeGreaterThan(0)
    expect(d.faces.length).toBeGreaterThan(0)
  })
})
