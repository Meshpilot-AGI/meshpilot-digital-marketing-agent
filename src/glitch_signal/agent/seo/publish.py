"""Publishing a post into the site repo (SEO-2), at stage S0.

The site is a Vite app on Cloudflare Pages, so publishing is a **code change**: insert a typed post
object into `src/data/blog.ts`, run the site's own verification gates, and open a PR. CF Pages builds
on merge.

**Stage S0 by default: the agent authors and opens a PR; a human merges.** Autonomy is earned, not
configured — the amended AI-SEO program grants S1 (agent merges its own PR) only after five
consecutive posts pass every gate with zero human edits to the body, measured as the diff between
what was proposed and what was merged. `stage` is therefore a parameter with a deliberately
conservative default rather than a flag someone flips early.

**The gates are the site's own**, not ones invented here — `typecheck`, `lint`, `schemas:validate`,
`links:audit`. Running the repo's real commands means the agent is held to the same bar as a human
contributor, and a gate that changes there changes here for free.

Everything that touches git, the shell or the filesystem is injectable, so the logic is testable
without a repo, a network, or an npm install.
"""
from __future__ import annotations

import asyncio
import pathlib
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog

from glitch_signal.agent.seo.contract import Violation, is_publishable
from glitch_signal.agent.seo.post import Post, to_typescript

log = structlog.get_logger(__name__)

# The site's own verification gates, in cheapest-first order: a typecheck failure should not wait
# behind a link audit. Overridable per brand — another brand's site will not be a Vite app.
DEFAULT_GATES: tuple[tuple[str, str], ...] = (
    ("typecheck", "npm run typecheck"),
    ("lint", "npm run lint"),
    ("schemas", "npm run schemas:validate"),
    ("links", "npm run links:audit"),
)

# Where the post object is inserted: immediately after the array opens, so newest reads first.
_ARRAY_OPEN = "export const blog: BlogPost[] = ["


@dataclass
class PublishResult:
    ok: bool
    stage: str
    slug: str
    reason: str = ""
    violations: list[Violation] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=dict)
    branch: str = ""
    pr_url: str = ""


def insert_post(source: str, post: Post) -> str:
    """Return `blog.ts` with the post inserted at the top of the array.

    Refuses rather than guesses if the anchor is missing or the slug already exists — silently
    writing a duplicate slug would break `blogBySlug`, which is built by `Object.fromEntries` and
    would simply drop one of them.
    """
    if _ARRAY_OPEN not in source:
        raise ValueError(f"anchor {_ARRAY_OPEN!r} not found — blog.ts layout changed")
    if f"slug: '{post.slug}'" in source or f'"slug": "{post.slug}"' in source:
        raise ValueError(f"slug {post.slug!r} already exists — would silently overwrite in blogBySlug")
    at = source.index(_ARRAY_OPEN) + len(_ARRAY_OPEN)
    return source[:at] + "\n" + to_typescript(post) + source[at:]


async def _run(cmd: str, cwd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *shlex.split(cmd), cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    return proc.returncode or 0, (out or b"").decode(errors="replace")[-4000:]


async def run_gates(repo: str, gates=DEFAULT_GATES, *, runner: Callable | None = None) -> tuple[dict, str]:
    """Run the site's verification gates. Returns `({name: passed}, first_failure_output)`.

    Stops at the first failure: the later gates run against a build the earlier one already said is
    broken, so their output is noise and their runtime is wasted.
    """
    runner = runner or _run
    results: dict[str, bool] = {}
    for name, cmd in gates:
        code, out = await runner(cmd, repo)
        results[name] = code == 0
        if code != 0:
            log.warning("seo.gate_failed", gate=name, cmd=cmd)
            return results, out
    return results, ""


async def publish(
    post: Post,
    *,
    repo: str,
    brand_id: str = "",
    stage: str | None = None,
    branch_prefix: str = "agent/blog",
    gates=DEFAULT_GATES,
    runner: Callable | None = None,
    writer: Callable[[str, str], None] | None = None,
    reader: Callable[[str], str] | None = None,
    blog_file: str = "src/data/blog.ts",
) -> PublishResult:
    """Author → verify → PR. Returns without touching git if anything fails.

    Order matters and is deliberate: the **contract is checked before the file is touched**. Writing
    a post that fails the editorial bar and then reverting leaves a dirty tree and a confusing
    branch; failing first leaves the repo untouched.
    """
    runner = runner or _run
    reader = reader or (lambda p: pathlib.Path(p).read_text())
    writer = writer or (lambda p, s: pathlib.Path(p).write_text(s))

    # The stage is EARNED, not passed in. An explicit `stage` is honoured only for tests and
    # dry-runs; in normal operation it is read from the track record, so autonomy cannot be granted
    # by a caller deciding it is time.
    if stage is None:
        from glitch_signal.agent.seo import track

        stage = await track.stage_for(brand_id) if brand_id else "S0"
    res = PublishResult(ok=False, stage=stage, slug=post.slug)

    ok, violations = is_publishable(post)
    if not ok:
        res.reason = "failed the editorial contract"
        res.violations = violations
        log.warning("seo.contract_failed", slug=post.slug,
                    violations=[str(v) for v in violations][:6])
        return res

    path = str(pathlib.Path(repo) / blog_file)
    try:
        updated = insert_post(reader(path), post)
    except ValueError as exc:
        res.reason = str(exc)
        return res
    writer(path, updated)

    res.gates, failure = await run_gates(repo, gates, runner=runner)
    if not all(res.gates.values()):
        res.reason = f"verification gate failed: {failure[:400]}"
        # Leave the working tree as the gate found it — a human debugging a typecheck failure needs
        # the file that produced it, not a reverted repo.
        return res

    branch = f"{branch_prefix}/{post.slug}"[:100]
    res.branch = branch
    for cmd in (f"git switch -c {branch}",
                f"git add {blog_file}",
                f"git commit -m {shlex.quote(f'content: {post.title}')}",
                f"git push -u origin {branch}"):
        code, out = await runner(cmd, repo)
        if code != 0:
            res.reason = f"git step failed ({cmd}): {out[:300]}"
            return res

    code, out = await runner(
        f"gh pr create --base main --title {shlex.quote(post.title)} "
        f"--body {shlex.quote(_pr_body(post, res.gates, stage))}", repo)
    if code != 0:
        res.reason = f"pr creation failed: {out[:300]}"
        return res
    res.pr_url = out.strip().splitlines()[-1] if out.strip() else ""
    res.ok = True

    if brand_id:
        from glitch_signal.agent.seo import track

        await track.record(brand_id, slug=post.slug, title=post.title, stage=stage,
                           gates=res.gates, pr_url=res.pr_url, branch=branch)

    if stage in ("S1", "S2"):
        # Earned self-merge. The gates already passed — that is what "all gates pass" means here —
        # so merging is the agreed behaviour rather than a shortcut.
        code, out = await runner(f"gh pr merge {shlex.quote(res.pr_url or branch)} "
                                 f"--squash --delete-branch", repo)
        if code != 0:
            res.reason = f"auto-merge failed, PR left open for review: {out[:200]}"
            log.warning("seo.auto_merge_failed", slug=post.slug, url=res.pr_url)
        else:
            log.info("seo.auto_merged", slug=post.slug, stage=stage, url=res.pr_url)
    else:
        log.info("seo.pr_opened_awaiting_human", slug=post.slug, url=res.pr_url)
    return res


def _pr_body(post: Post, gates: dict[str, bool], stage: str = "S0") -> str:
    passed = " · ".join(f"{k} {'✅' if v else '❌'}" for k, v in gates.items())
    return (
        f"Authored by the agent. **{post.reading_minutes} min read**, "
        f"{len(post.blocks)} blocks, {len(post.faq)} FAQ pairs.\n\n"
        f"{post.tldr}\n\n"
        f"**Editorial contract:** passed every clause (lede length, H2 count, primary-sourced "
        f"StatCallout, comparison table or ordered list, anti-pattern callout, FAQ count, internal "
        f"links across clusters, no unsourced figures).\n\n"
        f"**Site gates:** {passed}\n\n"
        f"Stage {stage}. Autonomy is earned per `ai-seo-program.md`: five consecutive posts merged "
        f"with no edits to the body promotes to S1 (self-merge). "
        f"{'Opened for human review.' if stage == 'S0' else 'Merged automatically after all gates passed.'}"
    )
