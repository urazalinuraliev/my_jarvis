"""Background scheduler that fires due `scheduled_actions` rows through the Executive."""
from openexecutive.scheduler.runner import run_scheduler

__all__ = ["run_scheduler"]
