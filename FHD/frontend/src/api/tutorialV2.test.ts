import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('./core', () => ({ api: apiMock, default: apiMock }))

import { tutorialV2Api } from './tutorialV2'

const run = {
  id: 'run-1',
  workspace_id: 'workspace-1',
  course_id: 'master-data',
  version: 2,
  status: 'active',
  current_step_id: 'create-customer',
  attempt_count: 0,
  progress: 0,
  completed_steps: 0,
  total_steps: 1,
  generation: 1,
  teaching_space: true,
  steps: [],
  started_at: '2026-08-13T00:00:00',
  completed_at: null,
}

describe('tutorialV2Api', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads course, current-run, and team-report contracts', async () => {
    const courses = [{ id: 'master-data' }]
    const reports = [{ user_id: 2, course_id: 'master-data' }]
    apiMock.get
      .mockResolvedValueOnce({ data: courses })
      .mockResolvedValueOnce({ data: run })
      .mockResolvedValueOnce({ data: reports })

    await expect(tutorialV2Api.courses()).resolves.toEqual(courses)
    await expect(tutorialV2Api.current()).resolves.toEqual(run)
    await expect(tutorialV2Api.reports()).resolves.toEqual(reports)
    expect(apiMock.get.mock.calls).toEqual([
      ['/api/tutorial/v2/courses'],
      ['/api/tutorial/v2/runs/current'],
      ['/api/tutorial/v2/reports'],
    ])
  })

  it('uses the exact start, lifecycle, verification, and reset routes', async () => {
    const verification = {
      run,
      evidence: { status: 'passed', result_code: 'verification_passed' },
      hint: '验证通过。',
    }
    apiMock.post
      .mockResolvedValueOnce({ data: run })
      .mockResolvedValueOnce({ data: run })
      .mockResolvedValueOnce({ data: { ...run, status: 'paused' } })
      .mockResolvedValueOnce({ data: verification })
      .mockResolvedValueOnce({ data: { ...run, id: 'run-2', generation: 2 } })

    await expect(tutorialV2Api.start('master-data')).resolves.toEqual(run)
    await expect(tutorialV2Api.enter('run-1')).resolves.toEqual(run)
    await expect(tutorialV2Api.leave('run-1')).resolves.toMatchObject({ status: 'paused' })
    await expect(tutorialV2Api.verify('run-1', 'create-customer', {
      visited_route: 'customers',
    })).resolves.toEqual(verification)
    await expect(tutorialV2Api.reset('run-1')).resolves.toMatchObject({
      id: 'run-2',
      generation: 2,
    })

    expect(apiMock.post.mock.calls).toEqual([
      ['/api/tutorial/v2/runs', { course_id: 'master-data' }],
      ['/api/tutorial/v2/runs/run-1/enter'],
      ['/api/tutorial/v2/runs/run-1/leave'],
      ['/api/tutorial/v2/runs/run-1/steps/create-customer/verify', {
        context: { visited_route: 'customers' },
      }],
      ['/api/tutorial/v2/runs/run-1/reset'],
    ])
  })
})
