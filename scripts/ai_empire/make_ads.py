"""Compositor matching the Jordan ad style: full-bleed cinematic scene + bottom
gradient + two-tone headline (white line / amber line) + grey subline + amber pill CTA."""
import os
from PIL import Image, ImageDraw, ImageFont

BG = os.path.expanduser("~/india-persona/flex-round/images/bg")
OUT = os.path.expanduser("~/india-persona/flex-round/images")
W, H = 1080, 1920
AMBER = (245, 190, 66); WHITE = (246, 246, 244); GREY = (198, 198, 204); DARK = (10, 10, 12)
BOLD = ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
REG = ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
       "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]

def F(sz, bold=True):
    for p in (BOLD if bold else REG):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

def cover(im):
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)))
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))

def grad(img):
    m = Image.new("L", (1, H), 0)
    for y in range(H):
        t = (y - H * 0.40) / (H * 0.60)
        m.putpixel((0, y), int(240 * max(0.0, min(1.0, t)) ** 1.1))
    return Image.composite(Image.new("RGB", (W, H), (6, 6, 8)), img, m.resize((W, H)))

PAD = 78

def pill(d, x, y, text):
    f = F(36); tw = d.textlength(text, font=f); h = 84; w = int(tw + 72)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=AMBER)
    d.text((x + 36, y + (h - 46) // 2), text, font=f, fill=DARK)

def fit(d, lines, maxw, start=116, mn=58):
    s = start
    while s > mn:
        f = F(s)
        if max(d.textlength(l, font=f) for l in lines) <= maxw:
            return f, s
        s -= 3
    return F(mn), mn

def ad(name, scene, l1, l2, sub):
    p = f"{BG}/{scene}.jpg"
    if not os.path.exists(p):
        print("MISSING bg", scene); return
    img = grad(cover(Image.open(p).convert("RGB"))); d = ImageDraw.Draw(img)
    d.text((PAD, H - 52), "Aanya is an AI-generated creator - results vary",
           font=F(21, False), fill=(120, 120, 126))
    pill_y = H - 178
    pill(d, PAD, pill_y, "buildaiempire.com")
    fnt, sz = fit(d, [l1, l2], W - 2 * PAD)
    lh = int(sz * 1.06)
    sub_y = pill_y - 72
    d.text((PAD, sub_y), sub, font=F(38, False), fill=GREY)
    y2 = sub_y - 44 - lh
    d.text((PAD, y2 - lh), l1, font=fnt, fill=WHITE)
    d.text((PAD, y2), l2, font=fnt, fill=AMBER)
    img.save(f"{OUT}/{name}.jpg", quality=92); print("ad", name)

ADS = [
 ("ad-01-built-by-ai", "wire", "BUILT BY AI.", "SOLD BY AI.", "Even this ad. The system is Rs 999."),
 ("ad-02-store-runs-itself", "desk", "MY STORE", "RUNS ITSELF.", "Six AI agents. Run it from home."),
 ("ad-03-whole-system", "wall", "THE WHOLE", "SYSTEM. Rs 999.", "No course. No upsells. Yours forever."),
 ("ad-04-skip-guru", "cafe", "SKIP THE", "Rs 50,000 COURSE.", "The real working system is Rs 999."),
 ("ad-05-cant-code", "present", "CAN'T CODE?", "BUILD IT WITH AI.", "Plain language. Your own store."),
]
for a in ADS:
    ad(*a)
print("DONE ads")
