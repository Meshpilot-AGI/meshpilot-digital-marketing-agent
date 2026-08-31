from glitch_signal.config import Settings


def test_social_flags_default_off_and_capped():
    s = Settings()
    assert s.agent_social_enabled is False              # ships inert
    assert s.agent_social_max_posts_per_run == 5        # the five platforms
