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

# `:name IS NULL` / `:name IS NOT NULL` with no surrounding CAST(...)
_BARE_PARAM_NULL_CHECK = re.compile(r"(?<!AS\s\w)\B:(\w+)\s+IS\s+(?:NOT\s+)?NULL", re.IGNORECASE)


def _sql_files():
    return [p for p in SRC.rglob("*.py") if "IS NULL" in p.read_text().upper()]


def test_no_bind_parameter_is_null_checked_without_a_cast():
    offenders: list[str] = []
    for path in _sql_files():
        text = path.read_text()
        for m in _BARE_PARAM_NULL_CHECK.finditer(text):
            # allowed when the parameter is cast somewhere in the same statement line
            line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end())]
            if line.lstrip().startswith("#"):
                continue                      # prose about the rule, not SQL subject to it
            if re.search(rf"CAST\s*\(\s*:{m.group(1)}\b", line, re.IGNORECASE):
                continue
            offenders.append(f"{path.relative_to(SRC)}: {line.strip()[:100]}")
    assert not offenders, (
        "bind parameter NULL-checked without CAST — asyncpg cannot infer its type and the "
        "statement will fail at runtime:\n  " + "\n  ".join(offenders))


def test_the_guard_actually_detects_the_shape_it_is_meant_to():
    """A guard that cannot fail is not a guard — prove the pattern matches the real bug."""
    bad = 'text("UPDATE t SET a = :x, b = CASE WHEN :x IS NULL THEN c ELSE d END")'
    good = 'text("UPDATE t SET a = :x, b = CASE WHEN CAST(:x AS text) IS NULL THEN c ELSE d END")'
    assert _BARE_PARAM_NULL_CHECK.search(bad)
    m = _BARE_PARAM_NULL_CHECK.search(good)
    assert m is None or re.search(rf"CAST\s*\(\s*:{m.group(1)}\b", good, re.IGNORECASE)
