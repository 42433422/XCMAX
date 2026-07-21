export function isSelfMaintenanceTask(task) {
  const text = `${task?.title || ''}\n${task?.description || ''}`.toLowerCase();
  return text.includes('self-maintenance') || text.includes('modstore self-maintenance');
}

export function enqueueByPriority(queue, item) {
  if (!isSelfMaintenanceTask(item?.task)) {
    queue.push(item);
    return queue;
  }
  const firstNonMaintenance = queue.findIndex(
    (queued) => !isSelfMaintenanceTask(queued?.task),
  );
  if (firstNonMaintenance === -1) queue.push(item);
  else queue.splice(firstNonMaintenance, 0, item);
  return queue;
}

export function activeTaskId(runningTaskId, queue) {
  const running = String(runningTaskId || '').trim();
  if (running) return running;
  return String(queue?.[0]?.task?.task_id || '').trim();
}
