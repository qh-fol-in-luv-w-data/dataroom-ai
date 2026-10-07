import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gen_attack_set as g  # noqa: E402


def _load(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]


def test_generate(tmp_path):
    g.generate(tmp_path, seed=13)
    tr, te = _load(tmp_path / "train.jsonl"), _load(tmp_path / "test.jsonl")
    ctr, cte = Counter(r["label"] for r in tr), Counter(r["label"] for r in te)
    assert 270 <= ctr["attack"] <= 330 and 270 <= ctr["benign"] <= 330
    assert 270 <= cte["attack"] <= 330 and 135 <= cte["benign"] <= 165
    assert set(ctr) == set(cte) == {"attack", "benign"}
    assert not {g.norm(r["text"]) for r in tr} & {g.norm(r["text"]) for r in te}
    assert {r["category"] for r in te if r["label"] == "attack"} == set(g.ATTACK_CATS)
    for recs in (tr, te):
        assert len({r["id"] for r in recs}) == len(recs)
        for r in recs:
            assert r["lang"] in {"vi", "vi_noaccent", "en", "mixed", "other"}
            assert r["obfuscation"] in {"none", "zero_width", "homoglyph", "spaced", "leet", "base64",
                                        "noaccent", "fullwidth", "case", "markdown"}
        ben = [r for r in recs if r["label"] == "benign"]
        assert sum(r["category"] == "benign_hard_negative" for r in ben) >= 0.4 * len(ben)


def test_deterministic(tmp_path):
    g.generate(tmp_path / "a", seed=13)
    g.generate(tmp_path / "b", seed=13)
    for f in ("train.jsonl", "test.jsonl"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes()


def test_norm():
    assert g.norm("Ｉｇｎｏｒｅ​  ALL\n") == "ignore all"
