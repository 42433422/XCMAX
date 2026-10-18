/**
 * 推送后开 PR：auto_merge≠true 的代码任务 push 成功后，设备代理自己开一个带 hold-merge 的 PR。
 * 背景：工单 40 的 fix 推到 devfleet/codex/sub-1-adc0ac 后，auto_merge=0 路径没有任何消费者
 * （merge-worker 只处理 auto_merge=true），导致无 PR、无 CI，只能人工开 #2410。
 * 约束：不开 auto-merge、不加 risk 标签；合并仍须 CI 全绿 + 终极员工裁决。失败只记日志，不回滚已推送的分支。
 */

export const PUSHED_PR_LABELS = Object.freeze(['hold-merge']);

export function parseGithubRepoFull(repoUrl) {
  const m = String(repoUrl || '').trim().match(/github\.com[:/]([^/\s]+)\/([^/\s]+?)(?:\.git)?\/?$/i);
  return m ? `${m[1]}/${m[2]}` : '';
}

export function pushedPrBaseBranch(task) {
  const base = String(task?.base_branch || '').trim();
  // 40 位 SHA 是交接校验基线，不是可开 PR 的分支。
  return !base || /^[0-9a-f]{40}$/i.test(base) ? 'main' : base;
}

export function shouldOpenPrForPushedTask(task, env = process.env) {
  if (env.DEVFLEET_OPEN_PR_ON_PUSH === '0') return { open: false, reason: 'disabled_by_env' };
  if (task?.auto_merge === true) return { open: false, reason: 'auto_merge_handled_by_merge_worker' };
  if (!String(task?.work_branch || '').trim()) return { open: false, reason: 'no_work_branch' };
  if (!parseGithubRepoFull(task?.repo_url)) return { open: false, reason: 'not_github_repo' };
  return { open: true, reason: '' };
}

export function buildPushedPrRequest(task) {
  const branch = String(task.work_branch).trim();
  const base = pushedPrBaseBranch(task);
  // 标题只用任务标题前 80 字；正文不带任务描述，避免把工单原文/客户内容写进 PR。
  const title = `devfleet: ${String(task.title || branch).replace(/\s+/g, ' ').trim()}`.slice(0, 90);
  const body = [
    '## Para 派工产物（push 后自动开 PR）',
    '',
    `- 任务 ID：\`${task.task_id || ''}\``,
    `- 子任务 ID：\`${task.subtask_id || ''}\``,
    `- 工作分支：\`${branch}\` → 目标：\`${base}\``,
    '- 策略：auto_merge=0，已标 `hold-merge`；未开 auto-merge。',
    '- 合入条件：CI 全绿 + 终极员工判断符合发展方向后人工合入；超级员工不得自动合入或部署。',
  ].join('\n');
  return { repoFull: parseGithubRepoFull(task.repo_url), branch, base, title, body };
}

/** execGh(args) → Promise<stdout>。幂等：分支已有 open PR 直接复用。 */
export async function ensurePullRequestForPushedBranch(request, execGh) {
  const { repoFull, branch, base, title, body } = request;
  const listed = await execGh(['pr', 'list', '--repo', repoFull, '--head', branch, '--state', 'open',
    '--json', 'number,url', '--limit', '1']);
  const existing = JSON.parse(String(listed || '[]').trim() || '[]')[0];
  if (existing?.url) return { url: existing.url, number: String(existing.number || ''), created: false };
  const out = String(await execGh(['pr', 'create', '--repo', repoFull, '--head', branch, '--base', base,
    '--title', title, '--body', body, '--label', PUSHED_PR_LABELS.join(',')]) || '').trim();
  const url = (out.match(/https:\/\/github\.com\/\S+\/pull\/\d+/) || [''])[0];
  if (!url) throw new Error(`gh pr create 未返回 PR 地址: ${out.slice(0, 200)}`);
  return { url, number: url.split('/').pop(), created: true };
}

export function describePushedPrFailure(err) {
  const text = String(err?.stderr || err?.message || err || '').slice(0, 400);
  if (/ENOENT/.test(text)) return `gh CLI 不存在：${text}`;
  if (/HTTP 401|authentication|gh auth login|Bad credentials/i.test(text)) {
    return `GitHub 认证失败（gh auth status 检查设备账号）：${text}`;
  }
  return text;
}
