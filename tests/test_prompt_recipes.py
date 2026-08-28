"""GROW-SOCIAL-RENDER-3 — prompt-recipe builders (pure, no I/O)."""
from glitch_signal.media import prompt_recipes as pr


def test_cinematic_video_prompt_uses_intent_directives():
    p = pr.cinematic_video_prompt(
        "a lone trader", "watching six monitors", "a dark home office", intent="tense"
    )
    assert "dutch-angle" in p              # framing from intent map
    assert "handheld" in p                 # movement from intent map
    assert "low-key" in p                  # lighting from intent map
    assert "lone trader" in p and "dark home office" in p
    assert "no on-image text" in p.lower() # text-free guardrail (diffusion)


def test_cinematic_unknown_intent_falls_back():
    p = pr.cinematic_video_prompt("x", "does y", "z", intent="nonsense")
    assert "drone flyover" in p            # majestic default


def test_ugc_hero_prompt_wearable_vs_held():
    worn = pr.ugc_hero_image_prompt("a woman in her 20s", "a teal beanie", "a city rooftop", wearable=True)
    held = pr.ugc_hero_image_prompt("a man", "a protein shake", "a gym", wearable=False)
    assert "wears the product" in worn
    assert "holds the product" in held
    assert "9:16" in worn and "legible" in worn


def test_illustrative_prompt_is_text_free():
    p = pr.illustrative_image_prompt("an abstract candlestick chart bursting into light")
    assert "candlestick chart" in p
    assert "no on-image text" in p.lower()  # reserve diffusion for text-free


def test_platform_video_spec_defaults():
    assert pr.platform_video_spec("tiktok") == ("9:16", 15)
    assert pr.platform_video_spec("x") == ("16:9", 12)
    assert pr.platform_video_spec("unknown") == ("9:16", 15)
