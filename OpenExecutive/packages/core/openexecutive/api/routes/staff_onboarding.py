"""FastAPI routes for the staff-onboarding framework.

Surfaces CRUD for the three entities — templates (reusable blueprints), plans
(one per hire), and tasks (checklist items) — mirroring the shape of
``api.routes.talent``. All rows live in the shared ``episodic_memory.db`` via
``openexecutive.staff_onboarding.store``.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from openexecutive.staff_onboarding import service, store
from openexecutive.staff_onboarding.models import (
    OnboardingPhase,
    OnboardingPlan,
    OnboardingStatus,
    OnboardingTask,
    OnboardingTemplate,
    TaskSpec,
    TaskStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_SHORT_MAX = 200
_LONG_MAX = 8000


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #

class TemplateUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=_SHORT_MAX, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=_SHORT_MAX)
    description: str = Field(default="", max_length=_LONG_MAX)
    department: str = Field(default="", max_length=_SHORT_MAX)
    ramp_days: int = Field(default=0, ge=0, le=90)
    checkin_cadence: str = Field(default="", max_length=_SHORT_MAX)
    task_specs: list[TaskSpec] = Field(default_factory=list)
    brief_sections: list[str] = Field(default_factory=list)
    is_active: bool = True

    def to_template(self) -> OnboardingTemplate:
        """Build the domain model from the request body (fields are 1:1; the
        store stamps created_at/updated_at)."""
        return OnboardingTemplate(**self.model_dump())


@router.get("/onboarding-templates", response_model=list[OnboardingTemplate])
def list_templates(active_only: bool = True) -> list[OnboardingTemplate]:
    return store.list_templates(active_only=active_only)


@router.get("/onboarding-templates/{name}", response_model=OnboardingTemplate)
def get_template(name: str) -> OnboardingTemplate:
    template = store.get_template(name)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/onboarding-templates/{name}", response_model=OnboardingTemplate)
def upsert_template(name: str, body: TemplateUpsert) -> OnboardingTemplate:
    if body.name != name:
        raise HTTPException(status_code=400, detail="Body name must match path name")
    store.upsert_template(body.to_template())
    saved = store.get_template(name)
    if saved is None:
        raise HTTPException(status_code=500, detail="Template vanished after save")
    return saved


@router.delete("/onboarding-templates/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(name: str) -> Response:
    if not store.delete_template(name):
        raise HTTPException(status_code=404, detail="Template not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #

class PlanCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=_SHORT_MAX)
    start_date: str = Field(min_length=1, max_length=_SHORT_MAX)
    role: str = Field(default="", max_length=_SHORT_MAX)
    template_name: str = Field(default="", max_length=_SHORT_MAX)
    person_id: int | None = None
    manager_person_id: int | None = None
    buddy_person_id: int | None = None
    engagement_id: int | None = None
    candidate_id: int | None = None


class PlanPatch(BaseModel):
    person_id: int | None = None
    manager_person_id: int | None = None
    buddy_person_id: int | None = None
    status: OnboardingStatus | None = None
    current_phase: OnboardingPhase | None = None


@router.get("/onboarding-plans", response_model=list[OnboardingPlan])
def list_plans(
    status: OnboardingStatus | None = None, include_archived: bool = False
) -> list[OnboardingPlan]:
    return store.list_plans(status=status, include_archived=include_archived)


@router.get("/onboarding-plans/{plan_id}", response_model=OnboardingPlan)
def get_plan(plan_id: int) -> OnboardingPlan:
    plan = store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.post(
    "/onboarding-plans", response_model=OnboardingPlan, status_code=status.HTTP_201_CREATED
)
def create_plan(body: PlanCreate) -> OnboardingPlan:
    """Create a plan, instantiating tasks from the named template when given."""
    template: OnboardingTemplate | None = None
    if body.template_name:
        template = store.get_template(body.template_name)
        if template is None:
            raise HTTPException(
                status_code=404, detail=f"Template {body.template_name!r} not found"
            )
    plan_id = service.instantiate_plan(
        full_name=body.full_name,
        start_date=body.start_date,
        role=body.role,
        template=template,
        person_id=body.person_id,
        manager_person_id=body.manager_person_id,
        buddy_person_id=body.buddy_person_id,
        engagement_id=body.engagement_id,
        candidate_id=body.candidate_id,
    )
    plan = store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=500, detail="Plan vanished after insert")
    return plan


@router.patch("/onboarding-plans/{plan_id}", response_model=OnboardingPlan)
def patch_plan(plan_id: int, body: PlanPatch) -> OnboardingPlan:
    if store.get_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    store.update_plan(
        plan_id,
        person_id=body.person_id,
        manager_person_id=body.manager_person_id,
        buddy_person_id=body.buddy_person_id,
        status=body.status,
        current_phase=body.current_phase,
    )
    updated = store.get_plan(plan_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Plan vanished")
    return updated


@router.post("/onboarding-plans/{plan_id}/advance", response_model=OnboardingPlan)
def advance_plan(plan_id: int) -> OnboardingPlan:
    if store.get_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    service.advance_phase(plan_id)
    updated = store.get_plan(plan_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Plan vanished")
    return updated


@router.post("/onboarding-plans/{plan_id}/activate", response_model=OnboardingPlan)
def activate_plan(plan_id: int) -> OnboardingPlan:
    """Activate a plan (status → active) and enqueue its ramp drip. The drip
    only fires once the plan has a roster person_id + generated ramp segments."""
    if store.get_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    service.activate_plan(plan_id)
    updated = store.get_plan(plan_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Plan vanished")
    return updated


@router.post("/onboarding-plans/{plan_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_plan(plan_id: int) -> Response:
    if store.get_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    store.archive_plan(plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------------- #

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=_SHORT_MAX)
    phase: OnboardingPhase = OnboardingPhase.WEEK_1
    category: str = Field(default="general", max_length=_SHORT_MAX)
    owner_person_id: int | None = None
    due_date: str | None = Field(default=None, max_length=_SHORT_MAX)


class TaskStatusPatch(BaseModel):
    status: TaskStatus
    completed_by_person_id: int | None = None


@router.post(
    "/onboarding-plans/{plan_id}/tasks",
    response_model=OnboardingTask,
    status_code=status.HTTP_201_CREATED,
)
def add_task(plan_id: int, body: TaskCreate) -> OnboardingTask:
    if store.get_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    task_id = store.add_task(
        plan_id=plan_id,
        title=body.title,
        phase=body.phase,
        category=body.category,
        owner_person_id=body.owner_person_id,
        due_date=body.due_date,
    )
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=500, detail="Task vanished after insert")
    return task


@router.post("/onboarding-tasks/{task_id}/status", response_model=OnboardingTask)
def set_task_status(task_id: int, body: TaskStatusPatch) -> OnboardingTask:
    if store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    store.set_task_status(
        task_id, body.status, completed_by_person_id=body.completed_by_person_id
    )
    updated = store.get_task(task_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Task vanished")
    return updated


@router.delete("/onboarding-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int) -> Response:
    if not store.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
