"""Influencer pipeline orchestrator — the end-to-end spine.

Ties the brand-scoped content plan (core.influencer_post_plan) to
discovery → generation → posting → engagement. Each tick is idempotent
and safe to run on a timer; the plan-row status is the state machine.

  discovery_tick : top up the plan with fresh idea rows (status=idea)
  generation_tick: lease an approved row, generate the persona-consistent
                   asset, write asset_url, status -> ready
  posting_tick   : take a due ready row, publish via Upload-Post,
                   write post_url/platform_post_id, status -> posted
  engagement_tick: plan owned-surface replies (sanctioned only)

Status flow: idea → approved (operator) → generating → ready → posted.
next_approved() atomically flips approved→generating so concurrent
workers never double-pick.
"""
from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from typing import Any

import structlog

from glitch_signal.influencer import content_plan, discovery, generate, posting
from glitch_signal.influencer.persona import load_persona

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class TickResult:
    stage: str
    persona_id: str | None
    plan_id: int | None
    status: str
    detail: str = ""


async def discovery_tick(persona_id: str, *, per_pillar: int = 2,
                         products: list[str] | None = None) -> TickResult:
    ids = await discovery.discover(persona_id, per_pillar=per_pillar, products=products)
    return TickResult("discovery", persona_id, None, "ok", f"{len(ids)} ideas written")


async def generation_tick(brand_id: str, *, persona_id: str | None = None) -> TickResult:
    """Generate the next approved row. Returns status='idle' if none queued."""
    row = await content_plan.next_approved(brand_id, persona=persona_id)
    if row is None:
        return TickResult("generation", persona_id, None, "idle", "no approved rows")
    try:
        persona = load_persona(row.persona_id)
        res = await generate.generate_asset(row.data, persona=persona)
        note = f"gen:{res.model} kind:{res.kind} dog:{res.featured_dog} refs:{res.reference_count}"
        if res.video_pending:
            # Still saved + kept; video deferred (e.g. out of credits). The
            # row stays 'ready' on the still so the paid asset is never lost;
            # a later retry reuses this still to animate (no re-pay).
            note += f" | video_pending: {res.video_error}"
        await content_plan.write_back(row.id, {
            "asset_url": res.asset_url,
            "status": "ready",
            "notes": note,
        })
        log.info("influencer.pipeline.generated", plan_id=row.id, persona=row.persona_id, kind=res.kind)
        return TickResult("generation", row.persona_id, row.id, "ready", res.asset_url)
    except Exception as e:  # noqa: BLE001
        await content_plan.write_back(row.id, {"status": "failed", "notes": f"gen_error: {str(e)[:240]}"})
        log.error("influencer.pipeline.gen_failed", plan_id=row.id, error=str(e)[:240])
        return TickResult("generation", row.persona_id, row.id, "failed", str(e)[:240])


async def posting_tick(brand_id: str, *, persona_id: str | None = None,
                       now: _dt.datetime | None = None) -> TickResult:
    """Publish the next due 'ready' row (scheduled_for <= now, or unscheduled)."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    rows = await content_plan.fetch_rows(brand_id, status="ready", persona=persona_id)
    due = [
        r for r in rows
        if not r.data.get("scheduled_for") or r.data["scheduled_for"] <= now
    ]
    if not due:
        return TickResult("posting", persona_id, None, "idle", "no due ready rows")
    row = due[0]
    asset_url = row.data.get("asset_url")
    if not asset_url:
        await content_plan.write_back(row.id, {"status": "failed", "notes": "ready but no asset_url"})
        return TickResult("posting", row.persona_id, row.id, "failed", "no asset_url")
    try:
        kind = "video" if (row.data.get("format") or "").lower() in {
            "reel", "video", "short", "talking_head", "tiktok"} else "image"
        platform = (row.data.get("platform") or "instagram").lower()

        # Compose a publish-ready caption + hashtags + AI disclosure in the
        # persona's voice (keeps an operator-authored caption if present).
        persona = load_persona(row.persona_id, validate=False)
        from glitch_signal.influencer import caption as caption_mod
        caption = await caption_mod.final_caption(persona, row.data)

        # ── Meta-native path (Instagram + Facebook) ──────────────────────────
        # We publish DIRECTLY via Graph API. No Upload-Post reseller for
        # Instagram or Facebook — if the persona lacks credentials we fail
        # loud so the operator knows to connect the account.
        meta = (persona.raw.get("accounts") or {}).get("meta") or {}
        ig_user_id = meta.get("ig_user_id")
        fb_page_id = meta.get("fb_page_id", "")

        if platform in ("instagram", "instagram_reels"):
            if not ig_user_id:
                raise RuntimeError(
                    f"persona {row.persona_id} has no accounts.meta.ig_user_id — "
                    f"connect the Instagram account (scripts/influencer_connect_meta.py) "
                    f"or remove 'instagram' from posting_cadence.platforms"
                )
            from glitch_signal.influencer import meta_publish
            r = await meta_publish.publish_ig(
                brand_id=brand_id, persona_id=row.persona_id, ig_user_id=ig_user_id,
                asset_url=asset_url, caption=caption, kind=kind,
                page_id=fb_page_id,
            )
            # Cross-post to the attached Facebook Page (best-effort — an FB
            # failure must not undo the IG post).
            fb_note = ""
            if fb_page_id and not r.dry_run:
                try:
                    fb = await meta_publish.publish_fb_page(
                        brand_id=brand_id, persona_id=row.persona_id, page_id=fb_page_id,
                        ig_user_id=ig_user_id, asset_url=asset_url,
                        caption=caption, kind=kind,
                    )
                    fb_note = f" + fb:{fb.post_id}"
                except Exception as e:  # noqa: BLE001
                    fb_note = f" (fb failed: {str(e)[:80]})"
                    log.warning("influencer.pipeline.fb_failed", plan_id=row.id, error=str(e)[:160])
            await content_plan.write_back(row.id, {
                "status": "posted",
                "caption": caption,
                "platform_post_id": r.media_id,
                "post_url": r.permalink,
                "notes": f"posted via instagram_graph_api{' (dry_run)' if r.dry_run else ''}{fb_note}",
            })
            log.info("influencer.pipeline.posted", plan_id=row.id, platform="instagram_native", dry=r.dry_run)
            return TickResult("posting", row.persona_id, row.id, "posted", r.media_id)

        if platform == "facebook":
            if not fb_page_id:
                raise RuntimeError(
                    f"persona {row.persona_id} has no accounts.meta.fb_page_id — "
                    f"connect the Facebook Page (scripts/influencer_connect_meta.py) "
                    f"or remove 'facebook' from posting_cadence.platforms"
                )
            from glitch_signal.influencer import meta_publish
            fb = await meta_publish.publish_fb_page(
                brand_id=brand_id, persona_id=row.persona_id, page_id=fb_page_id,
                ig_user_id=ig_user_id or "", asset_url=asset_url,
                caption=caption, kind=kind,
            )
            await content_plan.write_back(row.id, {
                "status": "posted",
                "caption": caption,
                "platform_post_id": fb.post_id,
                "post_url": fb.permalink,
                "notes": f"posted via facebook_graph_api{' (dry_run)' if fb.dry_run else ''}",
            })
            log.info("influencer.pipeline.posted", plan_id=row.id, platform="facebook_native", dry=fb.dry_run)
            return TickResult("posting", row.persona_id, row.id, "posted", fb.post_id)

        # ── Non-Meta platforms: Upload-Post reseller path ────────────────────
        res = posting.post_asset(
            brand_id=brand_id, platform=platform,
            asset_url=asset_url, caption=caption, kind=kind,
        )
        await content_plan.write_back(row.id, {
            "status": "posted",
            "caption": caption,
            "platform_post_id": res.request_id,
            "notes": f"posted via upload_post/{res.platform}{' (dry_run)' if res.dry_run else ''}",
        })
        log.info("influencer.pipeline.posted", plan_id=row.id, platform=res.platform, dry=res.dry_run)
        return TickResult("posting", row.persona_id, row.id, "posted", res.request_id)
    except Exception as e:  # noqa: BLE001
        await content_plan.write_back(row.id, {"status": "failed", "notes": f"post_error: {str(e)[:240]}"})
        log.error("influencer.pipeline.post_failed", plan_id=row.id, error=str(e)[:240])
        return TickResult("posting", row.persona_id, row.id, "failed", str(e)[:240])


async def engagement_tick(brand_id: str, *, persona_id: str | None = None,
                          window_minutes: int = 20, do_send: bool = True) -> list[TickResult]:
    """Sanctioned engagement on each persona's OWN recent IG posts: fetch
    comments, apply the persona engagement_policy (auto-reply after the
    grace window; questions get a reply + DM-funnel), and log every action
    to core.influencer_engagement_log (dedupe + cockpit activity feed).
    Comments still inside the window are 'held' and re-evaluated next tick."""
    from glitch_signal.influencer import engagement, meta_engage, meta_publish
    out: list[TickResult] = []
    targets = [persona_id] if persona_id else _brand_personas(brand_id)
    for pid in targets:
        persona = load_persona(pid, validate=False)
        meta = (persona.raw.get("accounts") or {}).get("meta") or {}
        ig, page = meta.get("ig_user_id"), meta.get("fb_page_id", "")
        if not ig:
            continue
        try:
            engagement.assert_no_outbound(persona)
            token = await meta_publish._resolve_page_token(brand_id, page, ig)
            if not token:
                out.append(TickResult("engagement", pid, None, "idle", "no token"))
                continue
            comments = await meta_engage.fetch_recent_comments(ig, token)
            pool = await content_plan._ensure_pool()
            sent = held = 0
            for cm in comments:
                async with pool.acquire() as conn:
                    prior = await conn.fetchval(
                        """SELECT status FROM core.influencer_engagement_log
                           WHERE persona_id=$1 AND surface='comment' AND target_id=$2""",
                        pid, cm.id)
                if prior in ("sent", "skipped", "failed"):
                    continue  # terminal — leave it
                action = await engagement.plan_comment_action(
                    persona, cm, window_minutes=window_minutes)
                if action.kind == "skip":
                    status = "skipped"
                elif action.auto_send and do_send:
                    try:
                        await meta_engage.reply_to_comment(cm.id, action.draft, token)
                        status = "sent"
                    except Exception as e:  # noqa: BLE001
                        status = "failed"
                        log.warning("influencer.engage.reply_failed", error=str(e)[:160])
                else:
                    status = "held"
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO core.influencer_engagement_log
                             (brand_id,persona_id,surface,target_id,media_id,author,
                              inbound_text,draft,status,reason,funnel_to_dm)
                           VALUES ($1,$2,'comment',$3,$4,$5,$6,$7,$8,$9,$10)
                           ON CONFLICT (persona_id,surface,target_id) DO UPDATE SET
                             draft=EXCLUDED.draft, status=EXCLUDED.status,
                             reason=EXCLUDED.reason, updated_at=NOW()""",
                        brand_id, pid, cm.id, cm.on_post_id, cm.author, cm.text,
                        action.draft, status, action.reason, action.funnel_to_dm)
                sent += status == "sent"
                held += status == "held"
            log.info("influencer.engage.tick", persona=pid, comments=len(comments), sent=sent, held=held)
            out.append(TickResult("engagement", pid, None, "ok",
                                  f"{len(comments)} comments: {sent} replied, {held} held"))
        except Exception as e:  # noqa: BLE001
            out.append(TickResult("engagement", pid, None, "failed", str(e)[:200]))
    return out


async def run_all(brand_id: str, *, persona_id: str | None = None,
                  discover: bool = False, per_pillar: int = 2,
                  products: list[str] | None = None) -> list[TickResult]:
    """One full sweep. Generation + posting always run; discovery opt-in."""
    out: list[TickResult] = []
    if discover:
        targets = [persona_id] if persona_id else _brand_personas(brand_id)
        for pid in targets:
            out.append(await discovery_tick(pid, per_pillar=per_pillar, products=products))
    if _auto_approve_enabled():
        out.append(await auto_approve_tick(
            brand_id, keep=_auto_approve_keep(), max_age_days=_auto_approve_max_age(),
            formats=_auto_approve_formats()))
    out.append(await generation_tick(brand_id, persona_id=persona_id))
    out.append(await posting_tick(brand_id, persona_id=persona_id))
    return out


def _brand_personas(brand_id: str) -> list[str]:
    """Persona ids whose bible declares this brand_id."""
    from glitch_signal.influencer.persona import list_personas
    out: list[str] = []
    for pid in list_personas():
        try:
            if load_persona(pid, validate=False).brand_id == brand_id:
                out.append(pid)
        except Exception:  # noqa: BLE001
            continue
    return out


def _postable_personas(brand_id: str) -> list[str]:
    """Brand personas that can actually publish: a Meta account is connected
    (an ig_user_id or fb_page_id is present). Auto-approval is scoped to
    these so it never queues content for a persona whose posting would fail
    loud at the Graph-API step (e.g. a paused / unconnected persona)."""
    out: list[str] = []
    for pid in _brand_personas(brand_id):
        try:
            meta = (load_persona(pid, validate=False).raw.get("accounts") or {}).get("meta") or {}
            if meta.get("ig_user_id") or meta.get("fb_page_id"):
                out.append(pid)
        except Exception:  # noqa: BLE001
            continue
    return out


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _auto_approve_enabled() -> bool:
    return _env_truthy("INFLUENCER_AUTO_APPROVE")


def _auto_approve_keep() -> int:
    try:
        return max(0, int(os.environ.get("INFLUENCER_AUTO_APPROVE_KEEP", "2")))
    except ValueError:
        return 2


def _auto_approve_max_age() -> int:
    try:
        return max(1, int(os.environ.get("INFLUENCER_AUTO_APPROVE_MAX_AGE_DAYS", "5")))
    except ValueError:
        return 5


def _auto_approve_formats() -> list[str]:
    """Optional format allow-list (comma-separated env). Empty = all formats.
    Use to skip formats whose engine is down, e.g. 'carousel,still' while
    HeyGen (video/reels) is out of credit."""
    raw = os.environ.get("INFLUENCER_AUTO_APPROVE_FORMATS", "").strip()
    return [f.strip() for f in raw.split(",") if f.strip()] if raw else []


async def auto_approve_tick(brand_id: str, *, keep: int = 2,
                            max_age_days: int = 5,
                            formats: list[str] | None = None) -> TickResult:
    """Hands-off approval tick: top up the approved buffer (to `keep` per
    connected persona) from the freshest idea rows. Replaces the operator
    gate when INFLUENCER_AUTO_APPROVE is set. No-op when no persona is
    connected, every buffer is full, or there are no fresh-enough ideas."""
    personas = _postable_personas(brand_id)
    if not personas:
        return TickResult("auto_approve", None, None, "idle", "no connected personas")
    promoted: list[int] = []
    for pid in personas:
        promoted += await content_plan.auto_approve(
            brand_id, [pid], keep=keep, max_age_days=max_age_days, formats=formats)
    if not promoted:
        return TickResult("auto_approve", None, None, "idle", "buffer full / no fresh ideas")
    log.info("influencer.pipeline.auto_approved", brand=brand_id, ids=promoted)
    return TickResult("auto_approve", None, None, "ok",
                      f"approved {len(promoted)}: {promoted}")
