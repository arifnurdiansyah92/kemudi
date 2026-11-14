"""Text (or an extracted document) -> small user stories on the board."""

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..llm import LLM, LLMError
from .stories import INTAKE_SYSTEM, format_description
from .taiga import Taiga

TAG = "agent-ready"
MAX_CRITERIA = 4
# A story's area tag routes it to an agent role (`area-web`, `area-backend`).
AREA_PREFIX = "area-"
AREAS = ("web", "backend")
# A role area (and intake area) for work touching web and backend at once.
BOTH = "both"


def area_tag(area: str) -> str:
    return f"{AREA_PREFIX}{area}"


def story_areas(tags: list[str]) -> list[str]:
    """The areas a story's tags name; no area tag means `web` (iteration 1).

    `area-both` (intake's tag for a story touching web and backend) names
    both, so the worker routes it to a role with area `both` (Fullstack).
    """
    found = []
    for t in tags:
        area = t[len(AREA_PREFIX):] if t.startswith(AREA_PREFIX) else None
        if area == "both":
            found += AREAS
        elif area in AREAS:
            found.append(area)
    return sorted(set(found)) or ["web"]


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

    def auto_ready(self, enabled_areas: set[str] | None = None) -> tuple[bool, str]:
        """Whether Awak may pick it up without a PM, and why not.

        `enabled_areas` are the areas with an enabled agent role (`both` for a
        Fullstack role, which also serves single-area stories); None keeps
        iteration 1's rule (web only), which the CLI uses.
        """
        if not self.criteria:
            return False, "belum ada kriteria penerimaan"
        if enabled_areas is None:
            if self.area != "web":
                return False, "butuh perubahan backend, belum bisa diuji otomatis per branch"
        elif self.area == BOTH:
            if BOTH not in enabled_areas:
                return False, ("menyentuh web dan backend sekaligus; pecah per area atau "
                               "aktifkan peran Fullstack (area Frontend + backend)")
        elif self.area not in enabled_areas and BOTH not in enabled_areas:
            return False, f"tidak ada peran agen aktif untuk area {self.area}"
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


HELD_REASON = "ditahan oleh PM saat intake"


def create_stories(taiga: Taiga, project_slug: str, drafts: list[StoryDraft],
                   enabled_areas: set[str] | None = None,
                   hold: set[int] = frozenset()) -> list[dict]:
    """Create the stories; Ready + `agent-ready` only when `auto_ready` holds
    and the PM did not hold it back (indexes in `hold`). Every story gets its
    area tag."""
    project = taiga.project(project_slug)
    ready, new = project.status("ready"), project.status("new")
    created = []
    for i, d in enumerate(drafts):
        ok, why = d.auto_ready(enabled_areas)
        if ok and i in hold:
            ok, why = False, HELD_REASON
        story = taiga.create_story(
            project.id,
            subject=d.subject,
            description=format_description(d.description, d.criteria),
            status=ready if ok else new,
            tags=([TAG] if ok else []) + [area_tag(d.area)],
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
