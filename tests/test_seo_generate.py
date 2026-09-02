"""SEO generation — grounding, the repair loop, and what it refuses to return."""
from __future__ import annotations

import json

from glitch_signal.agent.seo import generate
from glitch_signal.agent.seo.post import Post


def _valid_dict(slug="a-post", **over) -> dict:
    d = {
        "slug": slug, "title": "A title",
        "lede": "A short lede that answers the question directly.",
        "tldr": "The direct answer.", "publishedAt": "2026-09-02", "readingMinutes": 8,
        "tags": ["t"],
        "blocks": [
            {"type": "p", "text": "Prose citing 10% and $100,000."},
            {"type": "stat", "stat": "A 10% floor on $100,000 is $90,000.",
             "context": "Static floors do not move.",
             "sourceUrl": "https://example.com/ref", "sourceLabel": "Ref"},
            *[{"type": "h2", "text": t, "id": t} for t in ("a", "b", "c", "d")],
            {"type": "table", "headers": ["A", "B"], "rows": [["1", "2"]]},
            {"type": "antiPattern", "title": "Not this", "text": "What it does not solve."},
            {"type": "cite", "sources": [
                {"label": "t", "url": "/tools/x"}, {"label": "f", "url": "/prop-firms/"},
                {"label": "b", "url": "/brokers/overview"},
                {"label": "r", "url": "https://example.com/ref"}]},
        ],
        "faq": [{"q": f"Q{i}?", "a": f"A{i}."} for i in range(5)],
    }
    d.update(over)
    return d


class _LLM:
    """Returns each scripted response in turn, recording the prompts it was given."""

    def __init__(self, *responses):
        self.responses, self.prompts = list(responses), []

    async def __call__(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.responses[min(len(self.prompts) - 1, len(self.responses) - 1)]


# ── the happy path ──
async def test_a_valid_post_is_returned_first_time():
    llm = _LLM(json.dumps(_valid_dict()))
    post, problems = await generate.author("topic", audience="aud", complete=llm)
    assert post is not None and problems == []
    assert len(llm.prompts) == 1          # no wasted repair round


async def test_json_wrapped_in_prose_is_still_parsed():
    llm = _LLM("Here you go:\n" + json.dumps(_valid_dict()) + "\nHope that helps!")
    post, _ = await generate.author("t", audience="a", complete=llm)
    assert post is not None


# ── the repair loop ──
async def test_violations_are_fed_back_as_specific_instructions():
    """"3 H2 sections, need 4" is a far better repair signal than "try again" — and it is available
    only because the contract is structural."""
    bad = _valid_dict()
    bad["faq"] = []                                    # fails the FAQ clause
    llm = _LLM(json.dumps(bad), json.dumps(_valid_dict()))
    post, problems = await generate.author("t", audience="a", complete=llm)
    assert post is not None and problems == []
    assert "too_few_faq" in llm.prompts[1]             # the exact rule, not a vague retry
    assert "Fix EXACTLY these problems" in llm.prompts[1]


async def test_it_gives_up_rather_than_looping_forever():
    bad = _valid_dict()
    bad["faq"] = []
    llm = _LLM(json.dumps(bad))
    post, problems = await generate.author("t", audience="a", complete=llm, max_repairs=2)
    assert post is None                                # never returns a failing post
    assert any("too_few_faq" in p for p in problems)
    assert len(llm.prompts) == 3                       # initial + 2 repairs, then stop


async def test_unusable_response_is_survived_and_retried():
    llm = _LLM("I'm afraid I can't do that.", json.dumps(_valid_dict()))
    post, _ = await generate.author("t", audience="a", complete=llm)
    assert post is not None


async def test_a_returned_post_always_satisfies_the_contract():
    """The caller's guarantee: receiving a Post means it is structurally publishable."""
    from glitch_signal.agent.seo.contract import is_publishable

    llm = _LLM(json.dumps(_valid_dict()))
    post, _ = await generate.author("t", audience="a", complete=llm)
    assert is_publishable(post)[0]


# ── grounding: the failure this vertical cannot afford ──
def test_figures_absent_from_the_verified_facts_are_caught():
    """A model that invents "8%" for a real firm produces a post that looks perfectly cited and is
    false. The contract checks claims are SOURCED; this checks they are ours to make."""
    d = _valid_dict()
    d["blocks"][0]["text"] = "The trailing drawdown is 8% on this account."
    post = generate.to_post(d, author_slug="ryan")
    invented = generate.unsupported_figures(post, "FTMO: static max drawdown 10%")
    assert "8%" in invented and "10%" not in invented


def test_figures_present_in_the_facts_pass():
    d = _valid_dict()
    d["blocks"][0]["text"] = "The static max drawdown is 10%."
    post = generate.to_post(d, author_slug="ryan")
    assert generate.unsupported_figures(post, "FTMO: static max drawdown 10%") == []


def test_faq_answers_are_checked_for_invented_figures_too():
    """An invented number hidden in an FAQ answer is still published under the brand's name."""
    d = _valid_dict()
    d["faq"] = [{"q": "What is it?", "a": "It is 42% of the balance."}] * 5
    post = generate.to_post(d, author_slug="ryan")
    assert "42%" in generate.unsupported_figures(post, "FTMO: 10%")


def test_no_grounded_facts_means_no_figure_check():
    """With nothing to contradict, flagging every number would make the check meaningless."""
    d = _valid_dict()
    post = generate.to_post(d, author_slug="ryan")
    assert generate.unsupported_figures(post, "") == []


async def test_an_invented_figure_blocks_the_post_even_when_the_contract_passes():
    d = _valid_dict()
    d["blocks"][0]["text"] = "Their trailing drawdown is 8%."
    llm = _LLM(json.dumps(d))
    post, problems = await generate.author("FTMO rules", audience="a", complete=llm,
                                           facts_block="FTMO: static max drawdown 10%",
                                           max_repairs=0)
    assert post is None
    assert any("verified facts" in p for p in problems)


async def test_the_prompt_forbids_supplying_its_own_figures():
    llm = _LLM(json.dumps(_valid_dict()))
    await generate.author("t", audience="a", complete=llm, facts_block="FTMO: 10%")
    p = llm.prompts[0]
    assert "VERIFIED FACTS" in p and "Do NOT supply your own" in p
    assert "guaranteed pass" in p          # the program's own YMYL guardrail


async def test_absent_facts_are_stated_rather_than_left_blank():
    """Silence would invite the model to fill the gap; saying so explicitly does not."""
    llm = _LLM(json.dumps(_valid_dict()))
    await generate.author("t", audience="a", complete=llm, facts_block="")
    assert "do not cite firm-specific figures" in llm.prompts[0]


# ── mapping ──
def test_to_post_rejects_an_object_with_no_slug():
    assert generate.to_post({"title": "x"}, author_slug="ryan") is None


def test_to_post_lowercases_the_slug():
    p = generate.to_post(_valid_dict(slug="Mixed-Case-Slug"), author_slug="ryan")
    assert p.slug == "mixed-case-slug"


def test_author_slug_comes_from_the_caller_not_the_model():
    """The model does not get to pick a byline — authorship is a real person's attribution."""
    d = _valid_dict()
    d["authorSlug"] = "someone-else"
    p = generate.to_post(d, author_slug="lena")
    assert p.author_slug == "lena"
