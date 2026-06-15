import api from './core';

export type EnterpriseDeployCheck = {
  update_hub: {
    version?: string | null;
    git_sha?: string | null;
    sha256?: string | null;
    built_at?: string | null;
    has_vue_dist?: boolean;
    reachable?: boolean;
  };
  enterprise: {
    deploy_root?: string;
    deployed_sha256?: string | null;
    has_vue_dist?: boolean;
  };
  flags: {
    needs_update: boolean;
    up_to_date: boolean;
    hub_has_frontend?: boolean;
  };
};

export type DeployJobStep = {
  id: string;
  label: string;
  status: 'pending' | 'running' | 'done' | 'error' | 'skipped';
  detail?: string;
};

export type DeployJobData = {
  job_id: string;
  status: 'queued' | 'running' | 'done' | 'error';
  steps: DeployJobStep[];
  error?: string;
};

export const xcmaxDeployApi = {
  checkEnterpriseUpdates() {
    return api.get<{ success?: boolean; data?: EnterpriseDeployCheck }>('/api/xcmax/deploy/check');
  },
  applyEnterpriseUpdate(body: {
    include_backend?: boolean;
    include_frontend?: boolean;
    force?: boolean;
  } = {}) {
    return api.post<{ success?: boolean; data?: DeployJobData; message?: string }>(
      '/api/xcmax/deploy/apply',
      body,
    );
  },
  getEnterpriseJob(jobId: string) {
    return api.get<{ success?: boolean; data?: DeployJobData }>(
      `/api/xcmax/deploy/jobs/${encodeURIComponent(jobId)}`,
    );
  },
};
