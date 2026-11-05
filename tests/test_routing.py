import json

import pytest

from skillgate.routing import (
    LockEntry,
    RoutingError,
    avoid_clause,
    compose,
    dump_lock,
    load_lock,
    load_routing,
    resolve_base,
)


@pytest.mark.parametrize(
    ("avoid", "expected"),
    [
        (None, ""),
        ([], ""),
        ("Never use   on Fridays.", "Never use on Fridays."),
        (["a (x)"], "Don't use for a (x)."),
        (["a (x)", "b (y)."], "Don't use for a (x) or b (y)."),
        (["a", "b", "c"], "Don't use for a, b, or c."),
    ],
)
def test_avoid_clause(avoid, expected):
    assert avoid_clause(avoid) == expected


def test_compose_adds_sentence_boundary_once():
    assert compose("Does a thing", "Don't use for x.") == "Does a thing. Don't use for x."
    assert compose("Does a thing.", "Don't use for x.") == "Does a thing. Don't use for x."
    assert compose("Does a\n  thing", "") == "Does a thing"


def test_resolve_base_uses_lock_when_description_unchanged():
    entry = LockEntry(base="Base text.", clause="Don't use for x.")
    assert resolve_base("Base text. Don't use for x.", entry, set()) == "Base text."


def test_resolve_base_strips_known_clause_without_lock():
    clause = "Don't use for x."
    assert resolve_base("Base. Don't use for x.", None, {clause}) == "Base."


def test_resolve_base_strips_a_doubled_clause():
    clause = "Don't use for x."
    assert resolve_base("Base. Don't use for x. Don't use for x.", None, {clause}) == "Base."


def test_resolve_base_only_strips_whole_trailing_clause():
    # The clause text appearing mid-description is the author's, not ours.
    clause = "Don't use for x."
    text = "Don't use for x. Base continues here."
    assert resolve_base(text, None, {clause}) == text
    assert resolve_base("NotDon't use for x.", None, {clause}) == "NotDon't use for x."


def test_load_routing_rejects_unknown_keys(tmp_path):
    path = tmp_path / "routing.json"
    path.write_text(json.dumps({"skills": {"a": {"categroy": "x"}}}))
    with pytest.raises(RoutingError, match="unknown key"):
        load_routing(path)


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        '{"skills": []}',
        '{"skills": {"a": "x"}}',
        '{"skills": {"a": {"avoid": 3}}}',
    ],
)
def test_load_routing_rejects_malformed(tmp_path, payload):
    path = tmp_path / "routing.json"
    path.write_text(payload)
    with pytest.raises(RoutingError):
        load_routing(path)


def test_load_routing_missing(tmp_path):
    with pytest.raises(RoutingError, match="not found"):
        load_routing(tmp_path / "nope.json")
    assert load_routing(tmp_path / "nope.json", required=False) == {}


def test_lock_round_trip(tmp_path):
    entries = {"b": LockEntry("B.", "c2"), "a": LockEntry("A.", "c1")}
    path = tmp_path / "lock.json"
    path.write_text(dump_lock(entries))
    assert load_lock(path) == (entries, None)


def test_corrupt_lock_is_a_note_not_an_error(tmp_path):
    path = tmp_path / "lock.json"
    path.write_text("{ broken")
    entries, note = load_lock(path)
    assert entries == {}
    assert "unreadable" in note
