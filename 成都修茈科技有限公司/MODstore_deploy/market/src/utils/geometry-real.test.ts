import { describe, expect, it } from 'vitest'
import { createTetrahedron, createOctahedron, createIcosahedron, createDodecahedron } from './geometry-real'

describe('geometry-real', () => {
  it('createTetrahedron returns 4 vertices and 4 faces', () => {
    const poly = createTetrahedron(100)
    expect(poly.vertices).toHaveLength(4)
    expect(poly.faces).toHaveLength(4)
  })

  it('createTetrahedron vertices have correct radius', () => {
    const poly = createTetrahedron(50)
    for (const v of poly.vertices) {
      const len = Math.hypot(v[0], v[1], v[2])
      expect(len).toBeCloseTo(50, 5)
    }
  })

  it('createTetrahedron faces have normals', () => {
    const poly = createTetrahedron(100)
    for (const face of poly.faces) {
      const len = Math.hypot(face.normal[0], face.normal[1], face.normal[2])
      expect(len).toBeCloseTo(1, 5)
    }
  })

  it('createTetrahedron uses default radius', () => {
    const poly = createTetrahedron()
    for (const v of poly.vertices) {
      const len = Math.hypot(v[0], v[1], v[2])
      expect(len).toBeCloseTo(100, 5)
    }
  })

  it('createOctahedron returns 6 vertices and 8 faces', () => {
    const poly = createOctahedron(100)
    expect(poly.vertices).toHaveLength(6)
    expect(poly.faces).toHaveLength(8)
  })

  it('createOctahedron vertices have correct radius', () => {
    const poly = createOctahedron(75)
    for (const v of poly.vertices) {
      const len = Math.hypot(v[0], v[1], v[2])
      expect(len).toBeCloseTo(75, 5)
    }
  })

  it('createOctahedron faces are triangles', () => {
    const poly = createOctahedron(100)
    for (const face of poly.faces) {
      expect(face.indices).toHaveLength(3)
      expect(face.vertices).toHaveLength(3)
    }
  })

  it('createIcosahedron returns 12 vertices and 20 faces', () => {
    const poly = createIcosahedron(100)
    expect(poly.vertices).toHaveLength(12)
    expect(poly.faces).toHaveLength(20)
  })

  it('createIcosahedron vertices have correct radius', () => {
    const poly = createIcosahedron(80)
    for (const v of poly.vertices) {
      const len = Math.hypot(v[0], v[1], v[2])
      expect(len).toBeCloseTo(80, 5)
    }
  })

  it('createIcosahedron faces are triangles', () => {
    const poly = createIcosahedron(100)
    for (const face of poly.faces) {
      expect(face.indices).toHaveLength(3)
    }
  })

  it('createDodecahedron returns 20 vertices and 12 faces', () => {
    const poly = createDodecahedron(100)
    expect(poly.vertices).toHaveLength(20)
    expect(poly.faces).toHaveLength(12)
  })

  it('createDodecahedron vertices have correct radius', () => {
    const poly = createDodecahedron(60)
    for (const v of poly.vertices) {
      const len = Math.hypot(v[0], v[1], v[2])
      expect(len).toBeCloseTo(60, 4)
    }
  })

  it('createDodecahedron faces are pentagons', () => {
    const poly = createDodecahedron(100)
    for (const face of poly.faces) {
      expect(face.indices).toHaveLength(5)
    }
  })

  it('createDodecahedron faces have normals', () => {
    const poly = createDodecahedron(100)
    for (const face of poly.faces) {
      const len = Math.hypot(face.normal[0], face.normal[1], face.normal[2])
      expect(len).toBeCloseTo(1, 5)
    }
  })

  it('zero radius creates degenerate polyhedron', () => {
    const poly = createTetrahedron(0)
    for (const v of poly.vertices) {
      expect(Math.abs(v[0])).toBe(0)
      expect(Math.abs(v[1])).toBe(0)
      expect(Math.abs(v[2])).toBe(0)
    }
  })
})
