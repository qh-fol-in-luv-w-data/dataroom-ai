"""Document search by file name and attributes (BRD mục 3 #2–#3, BR-02, UAT-01), through the real API.

A file found by its name obeys the same rights as one found by its content: readable by the user
on SharePoint AND usable with AI, then live-checked."""
from tests.test_api import client, login  # noqa: F401  (fixture)


def search(client, oid, **params):
    return client.get("/api/search", headers=login(client, oid), params=params).json()


def ids(r):
    return [x["item_id"] for x in r["results"]]


def test_part_of_the_file_name_finds_the_file(client):
    r = search(client, "inv-a1", q="a1.txt")
    top = r["results"][0]
    assert top["item_id"] == "a1" and "name" in top["match"]
    assert top["site_name"] == "Nhóm A" and top["path"] == "Tai-lieu" and top["ext"] == "txt"


def test_folder_name_matches_without_accents(client):
    assert "a2" in ids(search(client, "inv-a1", q="riêng"))          # folder Rieng-a1 (private to inv-a1)
    assert "a2" not in ids(search(client, "inv-b1", q="riêng"))


def test_name_search_stays_inside_the_ai_scope(client):
    assert "a1" not in ids(search(client, "inv-b1", q="a1.txt"))       # other group
    assert "i1" not in ids(search(client, "inv-a1", q="i1.txt"))       # internal
    assert "x1" not in ids(search(client, "staff-1", q="x1.txt"))      # readable but AI_Use = Excluded
    assert "b2" not in ids(search(client, "inv-c1", q="b2.txt"))       # shared by mistake, blocked by RAC


def test_filters_list_files_without_words(client):
    listed = search(client, "inv-a1", site="GRP-A")
    assert set(ids(listed)) == {"a1", "a2"} and all(x["match"] == [] for x in listed["results"])
    assert ids(search(client, "inv-b1", site="GRP-A")) == []
    assert ids(search(client, "inv-a1", kind="pdf")) == []            # the test files are all .txt
    assert ids(search(client, "inv-a1")) == []                        # neither words nor filter
