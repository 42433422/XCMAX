"""Bind worker run writes to the durable queue claim that authorized execution."""


class WorkerLeaseLost(RuntimeError):
    pass


class ClaimedRunRepository:
    def __init__(self, repository, execution, owner_id):
        self._repository = repository
        self._execution = execution
        self._owner_id = owner_id

    def save(self, run):
        if run.run_id != self._execution.run_id:
            raise WorkerLeaseLost("worker attempted to save another run")
        return self._repository.save_claimed(
            run, owner_id=self._owner_id, execution_count=self._execution.execution_count
        )

    def __getattr__(self, name):
        return getattr(self._repository, name)
