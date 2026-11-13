"""Text (or an extracted document) -> small user stories on the board."""

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..llm import LLM, LLMError
from .stories import INTAKE_SYSTEM, format_description
from .taiga import Taiga

TAG = "agent-ready"
MAX_CRITERIA = 4


class StoryDraft(BaseModel):
    subject: str
    description: str = ""
    criteria: list[str] = Field(default_factory=list)
    area: Literal["web", "backend", "both"] = "web"

    @field_validator("criteria", mode="before")
    @classmethod
    def _list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [x.strip(" -•") for x in v.splitlines() if x.strip(" -•")]
        return [str(x) for x in v]

    @field_validator("description", mode="before")
    @classmethod
    def _text(cls, v):
        return "" if v is None else str(v)

    @field_validator("area", mode="before")
    @classmethod
    def _area(cls, v):
        v = str(v or "web").strip().lower()
        return v if v in ("web", "backend", "both") else "both"

    def auto_ready(self) -> tuple[bool, str]:
        """Whether Awak may pick it up without a PM, and why not."""
        if not self.criteria:
            return False, "belum ada kriteria penerimaan"
        if self.area != "web":
            return False, "butuh perubahan backend, belum bisa diuji otomatis per branch"
        if len(self.criteria) > MAX_CRITERIA:
            return False, f"lebih dari {MAX_CRITERIA} kriteria penerimaan; sebaiknya dipecah"
        return True, ""


def draft_stories(llm: LLM, text: str, lang: str = "id") -> list[StoryDraft]:
    reply = llm.json("awak.intake", INTAKE_SYSTEM.get(lang, INTAKE_SYSTEM["id"]), text)
    out = []
    for raw in reply.get("stories") or []:
        try:
            out.append(StoryDraft.model_validate(raw))
        except ValidationError:
            continue
    if not out:
        raise LLMError("intake returned no usable stories", str(reply))
    return out


def create_stories(taiga: Taiga, project_slug: str, drafts: list[StoryDraft]) -> list[dict]:
    project = taiga.project(project_slug)
    ready, new = project.status("ready"), project.status("new")
    created = []
    for d in drafts:
        ok, why = d.auto_ready()
        story = taiga.create_story(
            project.id,
            subject=d.subject,
            description=format_description(d.description, d.criteria),
            status=ready if ok else new,
            tags=[TAG] if ok else [],
        )
        if not ok:
            taiga.comment(
                story["id"],
                f"Awak: story ini tidak langsung dikerjakan karena {why}. "
                f"Pindahkan ke Ready dan beri tag `{TAG}` setelah ditinjau.",
            )
        created.append({"id": story["id"], "ref": story["ref"], "subject": d.subject,
                        "ready": ok, "reason": why})
    return created
