import pytest
import yaml

from skillgate.skills import FrontmatterError, parse_frontmatter, render_frontmatter


def test_body_is_preserved_byte_for_byte():
    body = "\n# Title\r\n\n---\nnot frontmatter\n"
    _, parsed_body = parse_frontmatter(f"---\nname: a\n---\n{body}")
    assert parsed_body == body


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("# no frontmatter\n", "does not start"),
        ("---\nname: a\n", "never closed"),
        ("---\nname: [unclosed\n---\n", "not valid YAML"),
        ("---\n- a list\n---\n", "not a key/value mapping"),
    ],
)
def test_parse_errors(text, message):
    with pytest.raises(FrontmatterError, match=message):
        parse_frontmatter(text)


def test_closing_fence_must_be_exact():
    # A '----' rule or '---x' inside the block must not close it.
    data, body = parse_frontmatter("---\nname: a\ndescription: x ---y\n---\nbody\n")
    assert data == {"name": "a", "description": "x ---y"}
    assert body == "body\n"


@pytest.mark.parametrize(
    "description",
    [
        "Plain text.",
        "Colons: quotes ' \" hashes # and [brackets] {braces} & *stars*.",
        "A very long description that mentions sql-review and changelog-writer "
        "many times so that it has to wrap: sql-review, changelog-writer, "
        "markdown-tables, commit-message, release-notes, sql-review.",
        "- starts like a list item",
        "unicode: café naïve résumé",
    ],
)
def test_render_round_trips(description):
    data = {"name": "a", "description": description, "triggers": ["x", "y"], "n": 3}
    rendered = render_frontmatter(data)
    assert rendered.startswith("---\n") and rendered.endswith("---\n")
    assert yaml.safe_load(rendered.strip("-\n")) == data


def test_render_never_breaks_hyphenated_names():
    description = "Use sql-review " * 20
    rendered = render_frontmatter({"description": description.strip()})
    for line in rendered.splitlines()[2:-1]:
        assert not line.rstrip().endswith("sql-")


def test_render_puts_managed_keys_first():
    rendered = render_frontmatter({"license": "MIT", "owner": "o", "name": "a"})
    keys = [line.split(":")[0] for line in rendered.splitlines()[1:-1]]
    assert keys == ["name", "owner", "license"]
