"""A question naming a document by its title ('Theo tài liệu “…”: …') is answered from that document: the title
is a preface to core_question(), so search never saw it. Matching runs under RLS: a title of a file the user may
not read finds nothing."""
from dr.core import answer, intent
from tests.test_gates import DEPS, env, items_cited  # noqa: F401


def test_named_titles():
    assert intent.named_titles('Theo tài liệu “Bảng giá SH 2024”: giá căn SH09?') == ["Bảng giá SH 2024"]
    assert intent.named_titles('Trong file "HDMB can A6.docx", ai là bên mua?') == ["HDMB can A6.docx"]
    assert intent.named_titles("Giá căn SH09 là bao nhiêu?") == []


def test_title_ending_in_a_date_is_the_whole_file_name():
    assert answer._fold_name("Bảng giá SH 01.03.2023") == answer._fold_name("Bảng giá SH 01.03.2023.pdf")
    assert answer._fold_name("HDMB can A6.docx") == "hdmb can a6"


def _named_step(res):
    return next((s for s in res["trace"] if s["step"].startswith("Câu hỏi nêu tên tài liệu")), None)


def test_question_naming_a_document_reads_that_document(env):
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-b1", ["Investor.AI"], "Theo tài liệu “c1”: doanh thu năm 2025 là bao nhiêu?", DEPS)
    st = _named_step(res)
    assert st and st["exact"] == 1
    assert not res["refused"] and items_cited(res) == {"c1"}


def test_title_of_a_file_the_user_may_not_read_finds_nothing(env):
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-b1", ["Investor.AI"], "Theo tài liệu “a1”: phí thu xếp là bao nhiêu?", DEPS)
    assert _named_step(res) is None
    assert not items_cited(res) & {"a1", "a2", "i1"}
