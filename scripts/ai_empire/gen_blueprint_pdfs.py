#!/usr/bin/env python3
"""Branded PDF deck generator for the AI Empire Blueprint bundle.
Outputs: START-HERE.pdf + per-folder GUIDE.pdfs into blueprint-content/."""
from fpdf import FPDF

BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
MONO = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"

DARK = (11, 15, 25)
AMBER = (245, 158, 11)
INK = (24, 24, 27)
GRAY = (82, 82, 91)
LIGHT = (244, 244, 245)
AMBER_BG = (254, 243, 199)

OUT = "/home/ubuntu/ai-empire-blueprint/blueprint-content"


class Deck(FPDF):
    def __init__(self, footer_text):
        super().__init__(format="A4")
        self.footer_text = footer_text
        self.add_font("B", "", BOLD)
        self.add_font("R", "", REG)
        self.add_font("M", "", MONO)
        self.set_auto_page_break(True, margin=22)
        self._body_page = False

    def footer(self):
        if not self._body_page:
            return
        self.set_y(-15)
        self.set_font("R", size=8)
        self.set_text_color(*GRAY)
        self.cell(0, 5, self.footer_text, align="L")
        self.cell(0, 5, f"{self.page_no()}", align="R")

    # ── building blocks ──────────────────────────────────────────────
    def cover(self, kicker, title_lines, subtitle):
        self._body_page = False
        self.add_page()
        self.set_fill_color(*DARK)
        self.rect(0, 0, 210, 297, "F")
        self.set_fill_color(*AMBER)
        self.rect(0, 0, 210, 3, "F")
        self.set_xy(18, 40)
        self.set_font("B", size=11)
        self.set_text_color(*AMBER)
        self.cell(0, 8, kicker.upper(), new_x="LMARGIN", new_y="NEXT")
        self.ln(6)
        self.set_font("B", size=34)
        self.set_text_color(255, 255, 255)
        for line in title_lines:
            self.set_x(18)
            self.cell(0, 15, line, new_x="LMARGIN", new_y="NEXT")
        self.ln(8)
        self.set_x(18)
        self.set_font("R", size=13)
        self.set_text_color(200, 200, 205)
        self.multi_cell(160, 7, subtitle)
        self.set_xy(18, 262)
        self.set_font("B", size=11)
        self.set_text_color(*AMBER)
        self.cell(0, 6, "AI EMPIRE BLUEPRINT", new_x="LMARGIN", new_y="NEXT")
        self.set_x(18)
        self.set_font("R", size=10)
        self.set_text_color(160, 160, 168)
        self.cell(0, 6, "buildaiempire.com")

    def body_page(self):
        self._body_page = True
        self.add_page()
        self.set_fill_color(*AMBER)
        self.rect(0, 0, 210, 2, "F")
        self.set_y(18)

    def h1(self, text):
        self.set_font("B", size=19)
        self.set_text_color(*INK)
        self.multi_cell(0, 9, text)
        self.set_draw_color(*AMBER)
        self.set_line_width(0.8)
        y = self.get_y() + 1.5
        self.line(10, y, 42, y)
        self.ln(7)

    def h2(self, text):
        self.ln(2)
        self.set_font("B", size=13)
        self.set_text_color(*INK)
        self.multi_cell(0, 7, text)
        self.ln(1.5)

    def p(self, text):
        self.set_font("R", size=10.5)
        self.set_text_color(*GRAY)
        self.multi_cell(0, 5.6, text)
        self.ln(2)

    def bullets(self, items):
        for it in items:
            self.set_font("B", size=10.5)
            self.set_text_color(*AMBER)
            self.cell(6, 5.6, ">")
            self.set_font("R", size=10.5)
            self.set_text_color(*GRAY)
            self.multi_cell(0, 5.6, it)
            self.ln(0.8)
        self.ln(1.5)

    def numbered(self, items):
        for i, it in enumerate(items, 1):
            self.set_font("B", size=10.5)
            self.set_text_color(*INK)
            self.cell(7, 5.6, f"{i}.")
            self.set_font("R", size=10.5)
            self.set_text_color(*GRAY)
            self.multi_cell(0, 5.6, it)
            self.ln(0.8)
        self.ln(1.5)

    def prompt_box(self, label, text):
        self.ln(1)
        x, y = self.get_x(), self.get_y()
        self.set_font("M", size=8.6)
        lines = self.multi_cell(184, 4.6, text, dry_run=True, output="LINES")
        h = len(lines) * 4.6 + 14
        if y + h > 272:
            self.body_page()
            x, y = self.get_x(), self.get_y()
        self.set_fill_color(*AMBER_BG)
        self.set_draw_color(*AMBER)
        self.set_line_width(0.4)
        self.rect(x, y, 190, h, "DF")
        self.set_xy(x + 4, y + 3)
        self.set_font("B", size=8)
        self.set_text_color(146, 64, 14)
        self.cell(0, 4, label.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_x(x + 4)
        self.set_font("M", size=8.6)
        self.set_text_color(*INK)
        self.multi_cell(182, 4.6, text)
        self.set_y(y + h + 4)

    def tip(self, text):
        self.set_font("B", size=9.5)
        self.set_text_color(*AMBER)
        self.cell(12, 5.4, "TIP")
        self.set_font("R", size=9.5)
        self.set_text_color(*GRAY)
        self.multi_cell(0, 5.4, text)
        self.ln(2)


F = "AI Empire Blueprint - buildaiempire.com"

# ═════════════════════════ START-HERE.pdf ═══════════════════════════
d = Deck(F)
d.cover("Welcome Deck", ["Build a business", "that runs itself."],
        "You now own the complete system: automation modules, ready agents, pipelines and the AI character machine. This deck shows you how to actually use it - starting tonight.")

d.body_page()
d.h1("What you just bought")
d.p("This is not a course. It is a working system delivered as files. Every folder is usable on its own; together they form one machine.")
d.bullets([
    "automation-blueprints/  -  7 complete systems. Business ops, content factory, research agents, no-code app building, Meta ads, packaging, testing. Start at 00-INDEX.md.",
    "prompts/agent-templates/  -  18 ready AI agents. Copy one, fill the [brackets], paste into your AI. Uniform skeleton: GOAL / INPUTS / OUTPUTS / RULES / TOOLS.",
    "templates/pipelines/  -  3 orchestration maps showing which agents chain into which systems, with the manual gates marked.",
    "prompts/character/ + image-consistency-bible.txt  -  the AI character lock system (how Jordan Hale stays the same person in every image).",
    "worksheets/  -  pricing calculator, content calendar, LoRA dataset recipe.",
    "examples/  -  a real generator script from live operations. Reference, not homework.",
])
d.p("Each folder has its own GUIDE.pdf - a two-minute read on how to work that folder.")

d.body_page()
d.h1("How to use .md files with AI")
d.p("Every playbook here is Markdown (.md) on purpose: Markdown is the native language of AI assistants. You do not read these files like a book - you FEED them to an AI and put it to work.")
d.h2("If you use Claude Code (or Cursor, or any AI coding tool)")
d.numbered([
    "Unzip this bundle into a folder and open that folder with the tool.",
    "The AI can now read every module, template and pipeline by itself.",
    "Ask for what you want in plain English - it will pull the right files.",
])
d.prompt_box("Copy-paste to Claude Code",
    "Read automation-blueprints/00-INDEX.md and the module that best fits my business: [describe your business in 2 lines]. Adapt that module's agent prompts from prompts/agent-templates/ to my niche - fill every bracket with my specifics and give me the exact prompts to run this week.")
d.h2("If you use a chat AI (Claude.ai, ChatGPT, Gemini)")
d.numbered([
    "Open the module .md, select all, copy.",
    "Paste it into the chat with an instruction on top (box below).",
    "For agents: paste the template as the FIRST message of a fresh chat - it becomes that chat's job description. One chat per agent.",
])
d.prompt_box("Copy-paste to any chat AI",
    "Below is a business automation module I own. Act as my implementation partner: 1) adapt it to my business: [your 2 lines], 2) rewrite the referenced agent template with all brackets filled for me, 3) give me a Day 1 checklist for tonight. MODULE: [paste the .md here]")
d.tip("Never edit an agent's OUTPUT to fix it. Edit its RULES and re-run. That is the difference between owning a system and babysitting a chatbot.")

d.body_page()
d.h1("Start tonight - the 45-minute path")
d.numbered([
    "Read automation-blueprints/00-INDEX.md (5 min).",
    "Pick the ONE module closest to money for you. Selling things? Module 01. Building an audience? Module 02.",
    "Open the module's first agent template, fill the brackets with your real business (10 min).",
    "Run it manually in your AI chat on REAL inputs - today's actual orders, today's actual product idea (20 min).",
    "Judge the output, tighten one rule, run again (10 min). That loop is the whole game.",
])
d.p("Rule that never changes: run every agent manually for days before you automate it. Module 07 gives you the promotion ladder - draft-only, then auto-with-review, then auto-with-caps. Money-touching steps keep their caps forever.")

d.body_page()
d.h1("Optional power-up: run it on Mesh Pilot")
d.p("Everything in this Blueprint works with nothing but an AI chat and your own accounts. But if you want the systems running against your REAL ad and social accounts without building the wiring yourself, there is a shortcut: Mesh Pilot - the operator platform these very systems were built and battle-tested on. This site, the ads that brought you here, and Jordan himself run on it.")
d.h2("What it gives you (free BYO-AI tier)")
d.numbered([
    "Sign in at app.meshpilot.app and connect your own accounts (Meta ads, socials, Shopify...).",
    "Mint your personal MCP key - a secure connection your AI can use.",
    "Add it to Claude, ChatGPT or Cursor - your AI can now read your real ad data and execute the automations from this Blueprint directly, live, on your accounts.",
])
d.p("Not mandatory. Not required for any module. It is simply the fastest path from 'prompts that describe the machine' to 'the machine actually running'. The manual path teaches you more; the Mesh Pilot path ships faster. Many owners do both.")
d.prompt_box("After connecting, tell your AI",
    "I have connected my accounts to Mesh Pilot and added the MCP. Using module [N] from my AI Empire Blueprint, run the weekly loop against my real data and show me the brief before executing anything.")

d.body_page()
d.h1("Your community + bonuses")
d.h2("AI Empire Builders (Discord)")
d.p("Owners get the Empire Builder role: module-by-module help in #blueprint-help, early template drops in #owner-updates, and a #wins wall of people building the same machine. Join: discord.gg/5N8aynHVPm - say you own the Blueprint when you arrive.")
d.h2("Bonus: the Nuraveda open-source agent suite")
d.p("Our lab open-sources production agents. They pair directly with your modules - free, MIT-flavored, yours to fork at github.com/Nuraveda-Labs:")
d.bullets([
    "ai-social-agent - multi-brand social content + posting pipeline (pairs with Module 02).",
    "ai-ugc-agent - script-to-render short-form video ads (pairs with Module 05).",
    "ai-ads-agent - cross-platform ad ops + ROAS rollups (pairs with Module 05).",
    "ai-seo-agent, ai-sales-agent, ai-voice-agent - when you expand past the core loop.",
])
d.h2("Support + guarantee")
d.p("Stuck? support@buildaiempire.com - real inbox, real replies. 30-day money-back guarantee, no questions inside the window. License: use everything in your own businesses; do not resell or redistribute the files themselves.")
d.output(f"{OUT}/START-HERE.pdf")
print("START-HERE.pdf")

# ═════════════════════ folder guides ═════════════════════════════════
def guide(path, kicker, title_lines, sub, build):
    g = Deck(F)
    g.cover(kicker, title_lines, sub)
    build(g)
    g.output(path)
    print(path.split("/blueprint-content/")[1])


def build_modules(g):
    g.body_page()
    g.h1("How to work this folder")
    g.p("Seven modules, one per system. They are playbooks, not chapters - you will live inside ONE at a time. 00-INDEX.md maps them and tells you the deploy rhythm: read once, run manually 3-5 days, wire the loop, log every run.")
    g.numbered([
        "Pick by outcome, not curiosity: 01 ops / 02 content / 03 research / 04 tool-building / 05 ads / 06 selling your system / 07 reliability.",
        "Each module names its agents - the actual files live in prompts/agent-templates/.",
        "Module 07 is the exception: read it whatever you pick. It is the discipline layer that keeps the others honest.",
    ])
    g.prompt_box("Copy-paste to your AI",
        "Here is module [N] from my Blueprint [paste .md]. My business: [2 lines]. Rewrite the module's build order as a 14-day plan for me specifically, with the exact agent template to deploy on each day.")
    g.tip("A module is 'running' when its log file has 7 straight days of entries. Not before.")


guide(f"{OUT}/automation-blueprints/GUIDE.pdf", "Folder Guide",
      ["The 7 automation", "modules"],
      "The systems library: business ops, content factory, research, no-code tools, ads, packaging, reliability.",
      build_modules)


def build_agents(g):
    g.body_page()
    g.h1("How to work this folder")
    g.p("18 agents, one file each, all the same skeleton: GOAL / INPUTS / OUTPUTS / RULES / TOOLS. The skeleton is the product - once you can read one, you can read (and write) them all.")
    g.numbered([
        "Open a template. Fill every [bracket] with your real specifics - vague brackets produce vague agents.",
        "Paste it as the FIRST message of a fresh AI chat (or a Claude Project). That chat is now that agent.",
        "Feed it the INPUTS it lists. Real ones. Judge outputs against the OUTPUTS spec.",
        "Fix problems by editing RULES, never by editing the output. Re-run.",
    ])
    g.prompt_box("Turn any template into YOUR agent",
        "Here is an agent template I own [paste .txt]. My business: [2 lines]. Fill every bracket for my case, tighten any rule that seems risky for my situation, and then introduce yourself as this agent and ask me for your first real inputs.")
    g.tip("One chat per agent. Mixing agents in one thread blurs their rules and ruins the logs.")


guide(f"{OUT}/prompts/agent-templates/GUIDE.pdf", "Folder Guide",
      ["18 ready", "AI agents"],
      "Copy, fill the brackets, run. Ops, content, research and builder agents in one uniform skeleton.",
      build_agents)


def build_pipelines(g):
    g.body_page()
    g.h1("How to work this folder")
    g.p("Pipeline JSONs are orchestration maps: which agents run, in what order, and where the MANUAL GATES are. The gates are the point - money never moves without you.")
    g.numbered([
        "Weeks 1-2: use the JSON as a checklist while you run the system by hand.",
        "Then wire it: n8n, Make, a small runner script your AI writes for you - or Mesh Pilot's MCP if you want your AI executing against live accounts (optional, see START-HERE).",
        "Keep the gates. Automating an approval gate is how accounts and budgets die.",
    ])
    g.prompt_box("Copy-paste to your AI",
        "Here is a pipeline JSON from my Blueprint [paste]. Write me the simplest possible runner for it on [your setup: laptop cron / n8n / etc], keeping every manual_gate as an explicit stop that asks me. Include a dry-run mode.")
    g.tip("These files become part of YOUR product if you ever package your system (Module 06). Keep them updated as you customize.")


guide(f"{OUT}/templates/pipelines/GUIDE.pdf", "Folder Guide",
      ["Pipelines +", "orchestration"],
      "The maps that chain your agents into systems - with the manual gates that keep them safe.",
      build_pipelines)


def build_character(g):
    g.body_page()
    g.h1("How to work these folders")
    g.p("The character system is what keeps an AI persona being the SAME person in every image, reel and caption - the difference between a brand face and a slideshow of strangers. Jordan Hale (the face of this product) runs on exactly these files.")
    g.numbered([
        "prompts/character/ - create the persona and lock a canonical face image. ONE image is the law; everything references it.",
        "prompts/image-consistency-bible.txt - the photoreal recipe + reference strength settings. Follow it verbatim; drift comes from improvising here.",
        "prompts/captions/ + prompts/video/ - voice-matched caption and reel prompt patterns.",
        "worksheets/loRA-dataset-recipe.txt - when you outgrow reference-image conditioning and want a trained lock.",
    ])
    g.prompt_box("Copy-paste to your AI",
        "Using the character creation system [paste prompts/character file] design a persona for my niche: [niche]. Then produce the locked base-subject string and the first 6 reference image prompts per the image consistency bible I will paste next.")
    g.tip("Never describe the face in scene prompts - the locked reference owns the face; scenes own everything else.")


guide(f"{OUT}/prompts/GUIDE.pdf", "Folder Guide",
      ["The character", "machine"],
      "Character lock, image consistency, captions and video prompts - the system behind Jordan Hale.",
      build_character)

print("ALL PDFS DONE")
