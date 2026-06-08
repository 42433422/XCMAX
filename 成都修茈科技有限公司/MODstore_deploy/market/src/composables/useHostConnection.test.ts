import { describe, expect, it } from 'vitest'
import { useHostConnection } from './useHostConnection'

describe('useHostConnection', () => {
  it('initializes as disconnected', () => {
    const { connected, statusText, statusClass } = useHostConnection()
    expect(connected.value).toBe(false)
    expect(statusText.value).toBe('未连接')
    expect(statusClass.value).toBe('pending')
  })

  it('setConnected updates state', () => {
    const { connected, statusText, statusClass, setConnected } = useHostConnection()
    setConnected('http://localhost:8765', { version: '1.0' })
    expect(connected.value).toBe(true)
    expect(statusText.value).toBe('已连接')
    expect(statusClass.value).toBe('ok')
  })

  it('setDisconnected resets state', () => {
    const { connected, statusText, setConnected, setDisconnected } = useHostConnection()
    setConnected('http://localhost:8765')
    setDisconnected()
    expect(connected.value).toBe(false)
    expect(statusText.value).toBe('未连接')
  })

  it('setConnected without info defaults to null', () => {
    const { hostInfo, setConnected } = useHostConnection()
    setConnected('http://localhost:8765')
    expect(hostInfo.value).toBeNull()
  })

  it('setConnected with info stores info', () => {
    const { hostInfo, setConnected } = useHostConnection()
    setConnected('http://localhost:8765', { version: '2.0' })
    expect(hostInfo.value).toEqual({ version: '2.0' })
  })

  it('setDisconnected clears hostInfo', () => {
    const { hostInfo, setConnected, setDisconnected } = useHostConnection()
    setConnected('http://localhost:8765', { version: '1.0' })
    setDisconnected()
    expect(hostInfo.value).toBeNull()
  })
})
