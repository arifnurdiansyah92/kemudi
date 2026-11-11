from pathlib import Path

import pytest

from kemudi_ai.documents import extract_text, normalize, split_sections

FIXTURE = (Path(__file__).parent / "fixtures" / "contract_text.txt").read_text(
    encoding="utf-8"
)


def test_normalize_fixes_ocr():
    assert normalize("lntegrasi Payment") == "Integrasi Payment"
    assert normalize("Tennin 2") == "Termin 2"
    assert normalize("Gateway (VA/ORIS)") == "Gateway (VA/QRIS)"
    assert normalize("Rp 30 .000.000") == "Rp 30.000.000"


def test_split_finds_scope_and_terms():
    sections = split_sections(normalize(FIXTURE))
    titles = [s.title for s in sections]
    assert "RUANG LINGKUP PEKERJAAN" in titles
    terms = next(s for s in sections if s.title == "KETENTUAN TAMBAHAN")
    assert "Change Request" in terms.text
    assert [s.ref for s in sections] == [f"S{i}" for i in range(1, len(sections) + 1)]


def test_page_headers_dropped():
    text = normalize(FIXTURE)
    assert all("Vendor Contoh" not in s.text.splitlines()[0:1][0]
               for s in split_sections(text) if s.text)


def test_rejects_unknown_type():
    with pytest.raises(ValueError):
        extract_text("contract.xlsx", b"")
