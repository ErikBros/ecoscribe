"""Auto tags (dictado-fnnr): a recurring meeting and a customer's meetings tag themselves once the user says so.
Invented names, titles and domains only."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from ecoscribe import autotags, sessions
from ecoscribe.window import Api


# ---------- naming a tag after a domain ----------

@pytest.mark.parametrize("domain,name", [
    ("customer-a.com", "Customer A"), ("mail.bosch.de", "Bosch"), ("eu.northwind-labs.co.uk", "Northwind Labs"),
    ("CUSTOMER-A.EXAMPLE", "Customer A"), ("acme.io", "Acme"), ("sub.acme.com.au", "Acme"),
])
def test_a_domain_names_a_tag(domain, name):
    assert autotags.tag_name(domain) == name


def test_a_tag_in_use_keeps_its_spelling():
    assert autotags.tag_name("customer-a.com", known=["Ops", "CUSTOMER A"]) == "CUSTOMER A"


def test_registrable_and_domain_of():
    assert autotags.domain_of(" Ana@Mail.Customer-A.com ") == "mail.customer-a.com"
    assert autotags.domain_of("no address") == ""
    assert autotags.registrable("mail.customer-a.com") == "customer-a.com"
    assert autotags.registrable("x.customer.co.uk") == "customer.co.uk"


@pytest.mark.parametrize("domain", ["gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
                                    "icloud.com", "me.com", "yahoo.com", "yahoo.co.uk", "yahoo.es", "proton.me",
                                    "protonmail.com", "gmx.de", "gmx.net", "hey.com", "aol.com"])
def test_free_mail_is_never_a_company(domain):
    assert autotags.is_free_mail(domain)


def test_a_company_is_not_free_mail():
    assert not autotags.is_free_mail("customer-a.com") and not autotags.is_free_mail("mail.bosch.de")


# ---------- the user's own company ----------

def cal(title="", *emails):
    return {"calendar": {"title": title, "attendees": [], "emails": list(emails)}}


def test_own_domain_from_the_calendar_owner():
    metas = [cal("A", "ana@customer-a.com"), cal("B", "ana@customer-a.com")]
    assert autotags.own_domains(metas, "me@mail.ownco.com") == {"ownco.com"}


def test_an_owner_on_free_mail_has_no_company():
    assert autotags.own_domains([cal("A", "ana@ownco.com")], "me@gmail.com") == set()


def test_without_an_owner_the_domain_in_most_meetings_is_own():
    metas = [cal("A", "kim@ownco.com", "ana@customer-a.com"), cal("B", "kim@ownco.com"),
             cal("C", "lee@ownco.com", "lee@ownco.com", "bo@northwind.com"), cal("D", "x@gmail.com"), cal("E")]
    assert autotags.own_domains(metas) == {"ownco.com"}


def test_free_mail_never_counts_as_own_and_a_tie_keeps_both():
    metas = [cal("A", "x@gmail.com", "ana@customer-a.com"), cal("B", "y@gmail.com", "kim@ownco.com")]
    assert autotags.own_domains(metas) == {"customer-a.com", "ownco.com"}
    assert autotags.own_domains([]) == set()


# ---------- the domain suggestion ----------

EMPTY = {"rules": [], "dismissed": []}


def test_suggests_the_customer_with_most_guests():
    m = cal("Sync", "kim@ownco.com", "ana@customer-a.com", "bo@customer-a.com", "lee@northwind.com", "x@gmail.com")
    assert autotags.suggestion(m, {"ownco.com"}, EMPTY) == {"domain": "customer-a.com", "tag": "Customer A"}


def test_no_suggestion_for_own_free_or_tagged():
    assert autotags.suggestion(cal("A", "kim@ownco.com", "x@gmail.com"), {"ownco.com"}, EMPTY) is None
    m = {**cal("A", "ana@customer-a.com"), "tags": ["customer a"]}
    assert autotags.suggestion(m, set(), EMPTY) is None
    assert autotags.suggestion({}, set(), EMPTY) is None


def test_a_dismissed_or_ruled_domain_gives_way_to_the_next():
    m = cal("A", "ana@customer-a.com", "bo@customer-a.com", "lee@northwind.com")
    gone = {"rules": [], "dismissed": [autotags.dismiss_key("domain", "customer-a.com")]}
    assert autotags.suggestion(m, set(), gone)["domain"] == "northwind.com"
    ruled = {"rules": [{"kind": "domain", "match": "customer-a.com", "tag": "Customer A"}], "dismissed": []}
    assert autotags.suggestion(m, set(), ruled)["tag"] == "Northwind"


def test_a_tag_removed_by_hand_is_not_suggested_again():
    m = {**cal("A", "ana@customer-a.com"), "tags_removed": ["Customer A"]}
    assert autotags.suggestion(m, set(), EMPTY) is None


# ---------- title match and the offer ----------

def test_title_match_ignores_case_and_spaces():
    rule = {"kind": "title", "match": autotags.title_key("  Weekly   Ops "), "tag": "Ops"}
    assert autotags.rule_matches(rule, cal("weekly ops"))
    assert not autotags.rule_matches(rule, cal("Weekly ops review"))
    assert not autotags.rule_matches(rule, {"title": "Weekly ops"})  # the meeting's own title doesn't count


def test_domain_rule_matches_any_address_at_that_company():
    rule = {"kind": "domain", "match": "customer-a.com", "tag": "Customer A"}
    assert autotags.rule_matches(rule, cal("x", "ana@eu.customer-a.com"))
    assert not autotags.rule_matches(rule, cal("x", "ana@customer-b.com"))


def test_offer_counts_the_others_without_the_tag():
    me = {**cal("Weekly ops"), "dir": "a", "tags": ["Ops"]}
    metas = [me, {**cal("weekly  OPS"), "dir": "b"}, {**cal("Weekly ops"), "dir": "c", "tags": ["ops"]},
             {**cal("Weekly ops"), "dir": "d", "tags_removed": ["Ops"]}, {**cal("Other"), "dir": "e"}]
    assert autotags.offer(me, "Ops", EMPTY, metas) == {"title": "Weekly ops", "tag": "Ops", "others": 1}


def test_no_offer_without_a_title_after_no_or_with_a_rule():
    assert autotags.offer({"title": "x"}, "Ops", EMPTY, []) is None
    m = cal("Weekly ops")
    no = {"rules": [], "dismissed": [autotags.dismiss_key("title", "weekly OPS", "ops")]}
    assert autotags.offer(m, "Ops", no, []) is None
    assert autotags.offer(m, "Other", no, []) is not None  # No was for that tag only
    ruled = {"rules": [{"kind": "title", "match": "weekly ops", "tag": "Ops"}], "dismissed": []}
    assert autotags.offer(m, "OPS", ruled, []) is None


# ---------- applying ----------

def test_apply_adds_once_and_respects_hand_removal_and_the_limit():
    rules = [{"kind": "title", "match": "weekly ops", "tag": "Ops"}, {"kind": "domain", "match": "customer-a.com", "tag": "Customer A"}]
    m = {**cal("Weekly ops", "ana@customer-a.com"), "tags": ["Hiring"]}
    assert autotags.apply(m, rules) == ["Hiring", "Ops", "Customer A"]
    assert autotags.apply({**m, "tags": ["ops", "customer a"]}, rules) is None
    assert autotags.apply({**m, "tags_removed": ["OPS"]}, rules) == ["Hiring", "Customer A"]
    assert autotags.apply({**m, "tags": [f"t{i}" for i in range(10)]}, rules) is None


def test_removals_remember_a_ruled_tag_taken_off_and_forget_one_put_back():
    rules = [{"kind": "title", "match": "weekly ops", "tag": "Ops"}]
    m = cal("Weekly ops")
    assert autotags.removals(m, ["Ops", "Hiring"], ["Hiring"], rules) == ["Ops"]  # Hiring: no rule, nothing kept
    assert autotags.removals({**m, "tags_removed": ["Ops"]}, [], ["ops"], rules) == []


# ---------- the file ----------

def test_rules_and_dismissals_round_trip(tmp_path):
    r = autotags.add_rule(tmp_path, "title", "  Weekly  Ops ", "Ops", now=datetime(2026, 10, 5, 9))
    assert r == {"kind": "title", "match": "weekly ops", "label": "Weekly Ops", "tag": "Ops", "made": "2026-10-05T09:00:00"}
    autotags.add_rule(tmp_path, "title", "weekly ops", "ops")  # the same rule again: still one
    autotags.add_rule(tmp_path, "domain", "mail.customer-a.com", "Customer A")
    autotags.dismiss(tmp_path, "domain", "northwind.com")
    autotags.dismiss(tmp_path, "domain", "northwind.com")
    st = autotags.load(tmp_path)
    assert [(x["kind"], x["match"], x["tag"]) for x in st["rules"]] == [("title", "weekly ops", "Ops"), ("domain", "customer-a.com", "Customer A")]
    assert st["dismissed"] == ["domain|northwind.com"]
    autotags.remove_rule(tmp_path, "title", "WEEKLY OPS", "OPS")
    assert [x["kind"] for x in autotags.load(tmp_path)["rules"]] == ["domain"]
    assert not list(tmp_path.glob("*.tmp"))


def test_a_broken_file_loads_empty(tmp_path):
    (tmp_path / autotags.STATE).write_text("{oops", encoding="utf-8")
    assert autotags.load(tmp_path) == EMPTY
    (tmp_path / autotags.STATE).write_text(json.dumps({"rules": [{"kind": "x"}, {"kind": "domain", "match": "a.com", "tag": " "}, 3],
                                                       "dismissed": [1, "domain|a.com"]}), encoding="utf-8")
    assert autotags.load(tmp_path) == {"rules": [], "dismissed": ["domain|a.com"]}


def test_owner_email_from_the_ical_copy(tmp_path):
    assert autotags.owner_email(tmp_path) == ""
    (tmp_path / "calendar.ics").write_text("BEGIN:VCALENDAR\r\nX-WR-CALNAME:Me@OwnCo.com\r\nEND:VCALENDAR\r\n", encoding="utf-8")
    assert autotags.owner_email(tmp_path) == "me@ownco.com"


# ---------- the window and a new meeting ----------

@pytest.fixture
def env(tmp_path):
    root = tmp_path / "transcripts"
    cfg_path = tmp_path / "cfg" / "config.toml"
    cfg_path.parent.mkdir()
    cfg_path.write_text(f'[transcribe]\nroot = "{root.as_posix()}"\n', encoding="utf-8")
    (tmp_path / "data").mkdir()
    api = Api(data_dir=tmp_path / "data", config_path=cfg_path, copy=lambda t: None, signal_reload=lambda: True,
              send_command=lambda d, cmd, args=None: {"ok": True})
    return api, root, tmp_path / "data"


def make(root, title, minute, cal_title=None, emails=(), tags=None, status="done"):
    d = sessions.create(title, "en", "meeting", root, now=datetime(2026, 10, 5, 14, minute))
    extra = {"tags": tags} if tags is not None else {}
    if cal_title is not None:
        extra["calendar"] = {"title": cal_title, "attendees": [], "emails": list(emails), "start": "", "end": ""}
    sessions.write_meta(d, status=status, duration_s=60.0, **extra)
    return d


def tags(d):
    return sessions.read_meta(d).get("tags", [])


def test_adding_a_tag_offers_the_series_and_yes_tags_past_and_future(env, tmp_path):
    api, root, data = env
    a = make(root, "Ops 1", 1, "Weekly ops")
    b = make(root, "Ops 2", 2, "weekly  ops")
    c = make(root, "Ops 3", 3, "Weekly ops", status="recording")
    make(root, "Other", 4, "Planning")
    out = api.set_tags(a.name, ["Ops"])
    assert out["offer"] == {"title": "Weekly ops", "tag": "Ops", "others": 2}
    assert api.set_tags(a.name, ["Ops"])["offer"] is None  # nothing new added
    yes = api.autotag_title(a.name, "Ops")
    assert yes["ok"] and yes["tags"] == ["Ops"] and yes["count"] == 1  # the recording one waits
    assert tags(b) == ["Ops"] and tags(c) == []
    sessions.write_meta(c, status="done")
    api.list_sessions()  # the catch-up when the list loads
    assert tags(c) == ["Ops"]
    assert api.autotag_rules()["rules"] == [{"kind": "title", "match": "weekly ops", "label": "Weekly ops", "tag": "Ops"}]
    # a future meeting: tagged when its calendar info is saved (meetings.Controller._create)
    from ecoscribe import meetings
    ctl = SimpleNamespace(root=root, data=data)
    ev = SimpleNamespace(title="WEEKLY OPS", attendees=[], emails=[], conference="", uid="", start=datetime(2026, 10, 12, 9),
                         end=datetime(2026, 10, 12, 10))
    d = meetings.Controller._create(ctl, "Meeting", "en", ev)
    assert tags(d) == ["Ops"]


def test_no_hides_the_offer_for_that_tag_and_title(env):
    api, root, _ = env
    a = make(root, "Ops 1", 1, "Weekly ops")
    make(root, "Ops 2", 2, "Weekly ops")
    assert api.dismiss_autotag("title", "Weekly ops", "Ops") == {"ok": True}
    assert api.set_tags(a.name, ["Ops"])["offer"] is None
    assert api.set_tags(a.name, ["Ops", "Hiring"])["offer"]["tag"] == "Hiring"
    assert api.dismiss_autotag("bogus", "x") == {"ok": False}


def test_a_tag_taken_off_by_hand_stays_off(env):
    api, root, _ = env
    a = make(root, "Ops 1", 1, "Weekly ops", tags=["Ops"])
    b = make(root, "Ops 2", 2, "Weekly ops")
    api.autotag_title(a.name, "Ops")
    assert tags(b) == ["Ops"]
    api.set_tags(b.name, [])
    assert sessions.read_meta(b)["tags_removed"] == ["Ops"]
    api.list_sessions()
    assert tags(b) == []
    api.set_tags(b.name, ["ops"])  # put back by hand: the removal is forgotten
    assert sessions.read_meta(b)["tags_removed"] == [] and tags(b) == ["Ops"]


def test_the_domain_suggestion_and_its_rule(env):
    api, root, data = env
    a = make(root, "Call 1", 1, "Customer A sync", ["kim@ownco.com", "ana@customer-a.com", "bo@customer-a.com"])
    b = make(root, "Call 2", 2, "Pricing", ["kim@ownco.com", "lee@mail.customer-a.com"])
    c = make(root, "Ops", 3, "Weekly ops", ["kim@ownco.com", "lee@ownco.com"])
    make(root, "Imported", 4)
    api.list_sessions()
    sug = api.get_session(a.name)["autotag"]
    assert sug == {"domain": "customer-a.com", "tag": "Customer A"}
    assert api.get_session(c.name)["autotag"] is None  # only the own company
    out = api.autotag_domain(a.name, sug["domain"], sug["tag"])
    assert out["ok"] and out["tags"] == ["Customer A"] and out["count"] == 1
    assert tags(b) == ["Customer A"] and tags(c) == []
    assert api.get_session(a.name)["autotag"] is None and api.get_live(b.name)["autotag"] is None
    rules = api.autotag_rules()["rules"]
    assert rules == [{"kind": "domain", "match": "customer-a.com", "label": "", "tag": "Customer A"}]
    # removing the rule keeps the tags, and a new meeting no longer gets it
    assert api.remove_autotag_rule("domain", "customer-a.com", "Customer A") == {"ok": True, "rules": []}
    assert tags(a) == ["Customer A"] and tags(b) == ["Customer A"]
    d = make(root, "Call 3", 5, "Customer A sync", ["ana@customer-a.com"])
    assert autotags.apply_one(d, data) is None and tags(d) == []


def test_a_dismissed_domain_is_not_suggested(env):
    api, root, _ = env
    a = make(root, "Call 1", 1, "Sync", ["kim@ownco.com", "ana@customer-a.com"])
    make(root, "Call 2", 2, "Ops", ["kim@ownco.com"])
    api.list_sessions()
    assert api.get_session(a.name)["autotag"]["tag"] == "Customer A"
    api.dismiss_autotag("domain", "customer-a.com")
    assert api.get_session(a.name)["autotag"] is None


def test_the_calendar_owner_decides_the_own_company(env):
    api, root, data = env
    (data / "calendar.ics").write_text("BEGIN:VCALENDAR\nX-WR-CALNAME:me@customer-a.com\nEND:VCALENDAR\n", encoding="utf-8")
    a = make(root, "Call", 1, "Sync", ["ana@customer-a.com", "lee@northwind.com"])
    api.list_sessions()
    assert api.get_session(a.name)["autotag"] == {"domain": "northwind.com", "tag": "Northwind"}


def test_rule_spelling_follows_a_tag_in_use(env):
    api, root, _ = env
    make(root, "Old", 1, tags=["CUSTOMER A"])
    make(root, "Ops", 2, "Ops", ["kim@ownco.com"])
    make(root, "Ops 2", 3, "Ops", ["kim@ownco.com"])
    a = make(root, "Call", 4, "Sync", ["ana@customer-a.com", "kim@ownco.com"])
    api.list_sessions()
    assert api.get_session(a.name)["autotag"]["tag"] == "CUSTOMER A"
