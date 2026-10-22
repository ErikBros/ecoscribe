"""Names fixed once stay fixed (dictado-1ph). Invented text only."""
import json

from ecoscribe import histfile, learn


def _s(old, new, vocab=(), reps=None):
    return learn.suggest(old, new, list(vocab), reps or {})


def test_a_misheard_name_is_offered_for_your_words():
    assert _s("Send it to Quinta Vell today.", "Send it to Quintavelle today.") == [{"kind": "word", "write": "Quintavelle"}]
    assert _s("Ask kwintavel about it.", "Ask Quintavelle about it.") == [{"kind": "word", "write": "Quintavelle"}]


def test_a_name_already_in_your_words_becomes_a_replace_rule():
    out = _s("We ship eco scribe on Monday.", "We ship Ecoscribe on Monday.", vocab=["Ecoscribe"])
    assert out == [{"kind": "replace", "heard": "eco scribe", "write": "Ecoscribe"}]
    assert _s("We ship eco scribe on Monday.", "We ship Ecoscribe on Monday.", vocab=["Ecoscribe"],
              reps={"eco scribe": "Ecoscribe"}) == []  # the rule is there already


def test_only_the_case_changed_counts_mid_sentence():
    assert _s("the new ecoscribe build", "the new Ecoscribe build") == [{"kind": "word", "write": "Ecoscribe"}]
    assert _s("thanks for that.", "Thanks for that.") == []  # a capital to start a sentence is grammar


def test_rewording_teaches_nothing():
    assert _s("Meet on Tuesday at six.", "Meet on Thursday at six.") == []  # a day, not a name
    assert _s("I think it is fine.", "I believe it's fine.") == []  # common words
    assert _s("Call the shop.", "Call Bob's Hardware on Main Street now please.") == []  # a rewrite, not a mishearing
    assert _s("Ping Anna later.", "Ping Marcus later.") == []  # a different name, not a respelling


def test_a_term_with_a_digit_counts_and_at_most_three_come_back():
    assert _s("Run the gpt five check.", "Run the GPT5 check.") == [{"kind": "word", "write": "GPT5"}]
    out = _s("Ana Bel met Kris Toff, then Dag Mar and Ole Sen came.", "Anabel met Kristoff, then Dagmar and Olesen came.")
    assert len(out) == 3


def _hist(tmp_path, *recs):
    p = tmp_path / "history.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return p


def test_histfile_edit_keeps_the_line_and_drops_old_scores(tmp_path):
    p = _hist(tmp_path, {"id": "a", "ts": "1", "text": "Quinta Vell", "clarity": 0.4}, {"id": "b", "ts": "2", "text": "other"})
    assert histfile.edit(p, "a", None, "Quintavelle")
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    assert rows[0] == {"id": "a", "ts": "1", "text": "Quintavelle", "edited": True} and rows[1]["text"] == "other"
    assert not histfile.edit(p, "zzz", None, "x")


def test_histfile_delete_still_works_through_the_shared_rewrite(tmp_path):
    p = _hist(tmp_path, {"ts": "1", "text": "old line without id"}, {"id": "b", "ts": "2", "text": "kept"})
    assert histfile.delete(p, None, "1")
    assert [json.loads(x)["text"] for x in p.read_text(encoding="utf-8").splitlines()] == ["kept"]


def test_the_edit_command_reaches_the_dictation_app():
    from ecoscribe import commands
    calls = []

    class App:
        def edit_dictation(self, rid, ts, text):
            calls.append((rid, ts, text))
            return {"ok": True}
    assert commands.handler_for(object(), None, app=App())("edit_dictation", {"id": "a", "text": "New"})["ok"]
    assert calls == [("a", None, "New")]


def test_window_edit_saves_and_offers_then_keep_learns(tmp_path):
    from ecoscribe import commands, config
    from ecoscribe.window import Api
    cfg_path = tmp_path / "cfg" / "config.toml"
    cfg_path.parent.mkdir()
    cfg_path.write_text('[text]\nvocabulary = ["Ecoscribe"]\n', encoding="utf-8")
    (tmp_path / "data").mkdir()
    _hist(tmp_path / "data", {"id": "a", "ts": "1", "text": "Send it to Quinta Vell and eco scribe."})
    api = Api(data_dir=tmp_path / "data", config_path=cfg_path, copy=lambda t: None, signal_reload=lambda: True,
              send_command=lambda *a, **k: {"ok": False, "error": commands.NOT_RUNNING})  # background app off
    out = api.edit_dictation("a", "", "Send it to Quintavelle and Ecoscribe.")
    assert out["ok"] and out["learn"] == [{"kind": "word", "write": "Quintavelle"},
                                          {"kind": "replace", "heard": "eco scribe", "write": "Ecoscribe"}]
    assert api.get_history()["items"][0]["text"] == "Send it to Quintavelle and Ecoscribe."
    assert api.learn_word("word", "Quintavelle")["ok"] and api.learn_word("replace", "Ecoscribe", "Eco Scribe")["ok"]
    c = config.load(cfg_path)
    assert "Quintavelle" in c.text.vocabulary and c.text.replacements["eco scribe"] == "Ecoscribe"
    assert not api.edit_dictation("a", "", "  ")["ok"] and not api.edit_dictation("gone", "", "x")["ok"]
