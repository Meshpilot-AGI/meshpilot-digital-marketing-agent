"""Guard against asyncpg's AmbiguousParameterError, which unit tests structurally cannot catch.

A bind parameter used only in a bare `:p IS NULL` gives asyncpg nothing to infer its type from, so
it raises `could not determine data type of parameter $N` and the whole statement never runs. This
shipped: `mark_result`'s `submitted_at` CASE failed on EVERY publish, posts went out to Facebook and
nothing was recorded, and no test noticed — the FakeEngine used throughout the suite does not
type-check parameters, so it happily returned success.

A behavioural test cannot cover this without a live Postgres, so this is a static one: any bind
parameter compared against NULL must be CAST. Cheap, and it generalises to every statement we write.
"""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "glitch_signal"

# `:name IS NULL` / `:name IS NOT NULL`, capturing whether THIS SPECIFIC occurrence is wrapped in a
# CAST(...) immediately before it — not merely whether a cast of the same name appears anywhere on
# the line. A statement can legitimately use the same bind name twice, once cast and once bare (e.g.
# `CASE WHEN CAST(:x AS text) IS NULL THEN a ELSE b END OR :x IS NULL`), and a per-line "does this
# name appear cast somewhere" check would let the second, unsafe occurrence hide behind the first.
_PARAM_NULL_CHECK = re.compile(
    r"(?P<cast>CAST\s*\(\s*)?:(?P<name>\w+)(?(cast)\s+AS\s+\w+\s*\))\s+IS\s+(?:NOT\s+)?NULL",
    re.IGNORECASE)


def _sql_files():
    return [p for p in SRC.rglob("*.py") if "IS NULL" in p.read_text().upper()]


def test_no_bind_parameter_is_null_checked_without_a_cast():
    offenders: list[str] = []
    for path in _sql_files():
        text = path.read_text()
        for m in _PARAM_NULL_CHECK.finditer(text):
            if m.group("cast"):
                continue                      # this exact occurrence is cast — safe
            line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end())]
            if line.lstrip().startswith("#"):
                continue                      # prose about the rule, not SQL subject to it
            # The other legitimate way to give asyncpg a type: SQLAlchemy's own
            # `.bindparams(bindparam(name, type_=...))`, used in this file for exactly this reason
            # (see agent/memory/store.py's `qvec`/`ids_csv`) — that types the whole statement's
            # occurrences of `name`, not just one wrapped in a literal CAST(...).
            if re.search(rf'bindparam\(\s*[\'"]{m.group("name")}[\'"]\s*,\s*type_=', text):
                continue
            offenders.append(f"{path.relative_to(SRC)}: {line.strip()[:100]}")
    assert not offenders, (
        "bind parameter NULL-checked without CAST — asyncpg cannot infer its type and the "
        "statement will fail at runtime:\n  " + "\n  ".join(offenders))


def test_the_guard_actually_detects_the_shape_it_is_meant_to():
    """A guard that cannot fail is not a guard — prove the pattern matches the real bug."""
    bad = 'text("UPDATE t SET a = :x, b = CASE WHEN :x IS NULL THEN c ELSE d END")'
    good = 'text("UPDATE t SET a = :x, b = CASE WHEN CAST(:x AS text) IS NULL THEN c ELSE d END")'
    m_bad = _PARAM_NULL_CHECK.search(bad)
    assert m_bad and not m_bad.group("cast")
    m_good = _PARAM_NULL_CHECK.search(good)
    assert m_good and m_good.group("cast")


def test_the_guard_catches_a_bare_occurrence_hiding_behind_a_cast_one_on_the_same_line():
    """The bug this guards against: the same bind name used twice on one line, once cast (safe) and
    once bare (unsafe) — a line-level 'is this name cast anywhere here' check would let the second,
    unsafe occurrence pass because the first one satisfies it."""
    mixed = ('text("CASE WHEN CAST(:x AS text) IS NULL THEN a ELSE b END, '
             'c = CASE WHEN :x IS NULL THEN d ELSE e END")')
    matches = list(_PARAM_NULL_CHECK.finditer(mixed))
    assert len(matches) == 2
    assert matches[0].group("cast") and not matches[1].group("cast")
