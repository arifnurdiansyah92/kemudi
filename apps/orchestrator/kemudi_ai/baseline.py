"""A draft baseline from contract sections. The PM edits and approves it."""

import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .documents import Section
from .llm import LLM

log = logging.getLogger(__name__)

Kind = Literal["epic", "story", "obligation", "term"]


class BaselineItem(BaseModel):
    ref: str = ""
    kind: Kind
    title: str
    description: str = ""
    acceptance: list[str] = Field(default_factory=list)
    clauses: list[str] = Field(default_factory=list)
    price_idr: int | None = None
    parent: str | None = None


SYSTEM = {
    "id": """Anda analis kontrak untuk vendor IT. Dari bagian-bagian kontrak (SPK/SOW) yang diberikan, susun baseline lingkup kerja.
Aturan:
- Setiap modul menjadi item kind "epic".
- Setiap fitur yang disebut di modul menjadi item kind "story", dengan "parent" berisi ref epic-nya. Tulis acceptance criteria singkat yang hanya bersumber dari kontrak; jangan menambah fitur yang tidak disebut.
- Setiap kewajiban para pihak yang memengaruhi lingkup (misalnya perbaikan bug selama garansi) menjadi kind "obligation".
- Setiap ketentuan tentang perubahan lingkup, Change Request, garansi, atau maintenance menjadi kind "term".
- "clauses" wajib diisi: ref bagian (misalnya "S5") diikuti kutipan pendek, misalnya "S5: Modul 3 Payment & Finance".
- "price_idr" diisi hanya jika kontrak menyebut harga untuk item itu.
- Teks kontrak berasal dari OCR dan bisa berisi salah ketik atau tabel yang berantakan; rekonstruksi dengan hati-hati.
Balas dengan satu objek JSON: {"items": [{"ref", "kind", "title", "description", "acceptance", "clauses", "price_idr", "parent"}]}. Gunakan bahasa Indonesia.""",
    "en": """You are a contract analyst for an IT vendor. From the contract sections given, build the scope baseline.
Rules:
- Each module becomes a kind "epic" item.
- Each feature listed under a module becomes a kind "story" with "parent" set to its epic's ref. Write short acceptance criteria taken only from the contract; never add features it does not name.
- Each party obligation that affects scope (for example fixing bugs during warranty) becomes kind "obligation".
- Each term about scope changes, Change Requests, warranty or maintenance becomes kind "term".
- "clauses" is required: the section ref (e.g. "S5") and a short quote, e.g. "S5: Module 3 Payment & Finance".
- Set "price_idr" only when the contract prices that item.
- The text comes from OCR and may contain typos or broken tables; reconstruct carefully.
Reply with one JSON object: {"items": [{"ref", "kind", "title", "description", "acceptance", "clauses", "price_idr", "parent"}]}. Write in English.""",
}


def sections_prompt(sections: list[Section]) -> str:
    return "\n\n".join(f"[{s.ref}] {s.title}\n{s.text}" for s in sections)


def draft_baseline(
    llm: LLM, sections: list[Section], lang: str = "id"
) -> list[BaselineItem]:
    reply = llm.json("baseline", SYSTEM.get(lang, SYSTEM["id"]), sections_prompt(sections))
    raw = reply.get("items") or []
    items: list[BaselineItem] = []
    old_to_new: dict[str, str] = {}
    for entry in raw:
        try:
            item = BaselineItem.model_validate(entry)
        except ValidationError as e:
            log.warning("dropping invalid baseline item %r: %s", entry, e)
            continue
        if not item.clauses:
            log.warning("dropping baseline item without clauses: %s", item.title)
            continue
        new_ref = f"B{len(items) + 1}"
        if item.ref:
            old_to_new[item.ref] = new_ref
        item.ref = new_ref
        items.append(item)
    for item in items:
        if item.parent:
            item.parent = old_to_new.get(item.parent)
    return items
