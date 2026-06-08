import { describe, expect, it, vi } from 'vitest'
import { notifyParentModsDeployed } from './notifyParentModsDeployed'

describe('notifyParentModsDeployed', () => {
  it('posts message to parent window with deployed list', () => {
    const postMessageSpy = vi.fn()
    const originalParent = window.parent
    Object.defineProperty(window, 'parent', { value: { postMessage: postMessageSpy }, configurable: true })

    notifyParentModsDeployed(['mod1', 'mod2'])

    expect(postMessageSpy).toHaveBeenCalledWith(
      {
        source: 'xcagi-modstore',
        type: 'xcagi-mods-deployed',
        deployed: ['mod1', 'mod2'],
      },
      '*',
    )

    Object.defineProperty(window, 'parent', { value: originalParent, configurable: true })
  })

  it('converts non-array deployed to empty array', () => {
    const postMessageSpy = vi.fn()
    const originalParent = window.parent
    Object.defineProperty(window, 'parent', { value: { postMessage: postMessageSpy }, configurable: true })

    notifyParentModsDeployed(null)

    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({ deployed: [] }),
      '*',
    )

    Object.defineProperty(window, 'parent', { value: originalParent, configurable: true })
  })

  it('does nothing when window.parent equals window', () => {
    const postMessageSpy = vi.fn()
    const originalParent = window.parent
    Object.defineProperty(window, 'parent', { value: window, configurable: true })
    vi.spyOn(window, 'postMessage').mockImplementation(postMessageSpy)

    notifyParentModsDeployed(['mod1'])

    expect(postMessageSpy).not.toHaveBeenCalled()

    Object.defineProperty(window, 'parent', { value: originalParent, configurable: true })
  })

  it('handles undefined deployed', () => {
    const postMessageSpy = vi.fn()
    const originalParent = window.parent
    Object.defineProperty(window, 'parent', { value: { postMessage: postMessageSpy }, configurable: true })

    notifyParentModsDeployed(undefined)

    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({ deployed: [] }),
      '*',
    )

    Object.defineProperty(window, 'parent', { value: originalParent, configurable: true })
  })
})
