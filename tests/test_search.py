"""Meeting search (dictado-8h8): accent-proof in every script, ranked, grouped by call, kept up to date.
The 12 questions below are the card's test set, over invented calls in four languages."""
import json
from datetime import datetime

import pytest

from ecoscribe import search, sessions

CALLS = {
    "Budget review": ("en", [
        "We need to cut the marketing budget by ten percent before Friday.",
        "I'll send the revised spreadsheet to finance tomorrow morning.",
        "The budget for the offsite stays as it is."]),
    "Flytten": ("sv", [
        "Vi flyttar kontoret till Göteborg i mars.",
        "Jag bokar flyttfirman på måndag, det är billigare då.",
        "Glöm inte att säga upp avtalet för parkeringen."]),
    "Cena del sábado": ("es", [
        "Quedamos el sábado a las nueve en la plaza.",
        "Yo compro las entradas del museo esta noche.",
        "¿Envíalo también a mi hermana, vale?"]),
    "Μάθημα": ("el", [
        "Καλημέρα, πώς είσαι σήμερα;",
        "Θα φέρω το βιβλίο την Τρίτη στο σπίτι.",
        "Η Αθήνα είναι μεγάλη πόλη."]),
    "Weekly sync": ("en", [
        "Quick update: the release moves to next week.",
        "Budget questions go to the finance channel."]),
}

QUESTIONS = [  # (query, the call it must rank first)
    ("marketing budget", "Budget review"),            # plain words
    ("BUDGET spreadsheet", "Budget review"),          # case
    ("goteborg", "Flytten"),                          # Swedish without å ä ö
    ("flyttfirman mandag", "Flytten"),
    ("parkering", "Flytten"),                         # a word start finds the longer word
    ("sabado plaza", "Cena del sábado"),              # Spanish without accents
    ("envialo", "Cena del sábado"),
    ("entrada museo", "Cena del sábado"),             # singular finds the plural
    ("καλημερα", "Μάθημα"),                           # Greek without tonos
    ("ΣΠΙΤΙ", "Μάθημα"),                              # Greek upper case
    ("αθηνα πολη", "Μάθημα"),
    ('"release moves"', "Weekly sync"),               # an exact phrase
]


@pytest.fixture
def root(tmp_path):
    for i, (title, (lang, lines)) in enumerate(CALLS.items()):
        d = sessions.create(title, lang, "meeting", tmp_path, now=datetime(2026, 10, 1 + i, 10, 0))
        sessions.write_meta(d, status="done", duration_s=300)
        segs = [{"t0": 30.0 * n, "t1": 30.0 * n + 5, "text": t, "speaker": "Me" if n % 2 else "Others"}
                for n, t in enumerate(lines)]
        (d / "transcript.json").write_text(json.dumps({"segments": segs}, ensure_ascii=False), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("query,want", QUESTIONS)
def test_the_twelve_questions_find_their_call_first(root, query, want):
    idx = search.open_index(root)
    res = idx.search(query)
    idx.close()
    assert res and res[0]["title"] == want, (query, [r["title"] for r in res])


def test_results_are_ranked_and_grouped_with_snippets(root):
    idx = search.open_index(root)
    res = idx.search("budget")
    assert [r["title"] for r in res][:2] == ["Budget review", "Weekly sync"]  # two lines beat one
    top = res[0]
    assert top["lines"] == 2 and [h["at"] for h in top["hits"]] == ["00:00:00", "00:01:00"]
    assert top["hits"][0]["speaker"] == "Others" and "marketing budget" in top["hits"][0]["text"]


def test_nothing_found_and_empty_queries(root):
    idx = search.open_index(root)
    assert idx.search("zebra") == [] and idx.search("  ¿? ") == []
    assert idx.search("budget zebra") == []  # every word must be in the call


def test_the_index_follows_new_changed_and_deleted_calls(root):
    idx = search.open_index(root)
    assert idx.search("tulpaner") == []
    d = sessions.create("Trädgården", "sv", "meeting", root, now=datetime(2026, 10, 20, 9, 0))
    (d / "transcript.json").write_text(json.dumps({"segments": [{"t0": 0, "t1": 2, "text": "Vi planterar tulpaner."}]}),
                                       encoding="utf-8")
    sessions.write_meta(d, status="done")
    assert idx.search("tulpaner")[0]["id"] == d.name
    sessions.delete(d)
    assert idx.search("tulpaner") == []


def test_a_broken_index_file_is_rebuilt(root):
    (root / search.FILE).write_bytes(b"not a database at all" * 100)
    idx = search.open_index(root)
    assert idx.search("goteborg")[0]["title"] == "Flytten"


def test_fold_and_query():
    assert search.fold("Ἀθῆναι ΣΠΊΤΙ Göteborg ¿Envíalo?") == "αθηναι σπιτι goteborg ¿envialo?"
    assert search.fts_query('budget "next week" ok') == '"next week" OR "budget"* OR "ok"*'
    assert search.fts_query("¿?") is None
