import json, os, urllib.request
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.expanduser("~/india-persona/flex-round/images"); os.makedirs(OUT, exist_ok=True)
HU = json.load(open(os.path.expanduser("~/india-persona/hosted_urls.json")))
W, H = 1080, 1350
DARK = (11, 11, 13); AMBER = (245, 196, 81); WHITE = (242, 242, 240); GREY = (140, 140, 146)

_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
_FONTS_R = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]

def font(sz, bold=True):
    for p in (_FONTS if bold else _FONTS_R):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

def wrap(d, text, fnt, maxw):
    out, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= maxw: cur = t
        else: out.append(cur); cur = w
    if cur: out.append(cur)
    return out

def dl(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    open(dest, "wb").write(urllib.request.urlopen(req, timeout=60).read())

def cover(im):
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)))
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))

def footer(d, price=True):
    if price:
        d.text((64, H - 250), "Rs 999", font=font(104), fill=AMBER)
        d.text((66, H - 132), "one-time  ·  buildaiempire.com", font=font(38, False), fill=WHITE)
    d.text((64, H - 60), "AI-generated creator · results vary · no income guarantee",
           font=font(22, False), fill=GREY)

def card(name, head, sub):
    img = Image.new("RGB", (W, H), DARK); d = ImageDraw.Draw(img)
    d.rectangle([64, 150, 210, 164], fill=AMBER)
    y = 300
    for ln in wrap(d, head, font(94), W - 128):
        d.text((64, y), ln, font=font(94), fill=WHITE); y += 108
    y += 26
    for ln in wrap(d, sub, font(46, False), W - 128):
        d.text((64, y), ln, font=font(46, False), fill=AMBER); y += 62
    footer(d)
    img.save(f"{OUT}/{name}.jpg", quality=90); print("card", name)

def photo(name, ref_key, head):
    tmp = f"{OUT}/_{name}.jpg"; dl(HU[ref_key], tmp)
    img = cover(Image.open(tmp).convert("RGB"))
    grad = Image.new("L", (1, H), 0)
    for yy in range(H):
        grad.putpixel((0, yy), int(255 * min(1, max(0, (yy - H * 0.42) / (H * 0.58)))))
    shade = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.composite(shade, img, grad.resize((W, H)))
    d = ImageDraw.Draw(img)
    y = H - 470
    for ln in wrap(d, head, font(80), W - 128):
        d.text((64, y), ln, font=font(80), fill=WHITE); y += 92
    footer(d)
    img.save(f"{OUT}/{name}.jpg", quality=90); os.remove(tmp); print("photo", name)

# 3 design cards
card("01-anti-guru", "Still buying Rs 50,000 guru courses?", "The actual working system is Rs 999.")
card("02-meta-proof", "This ad was made by the system.", "The creator, the store, the emails — all AI.")
card("03-cost-value", "One system. Six AI agents. Rs 999.", "Store, listings, ads, content, support, delivery.")
# 2 photo-led (Aanya hosted refs)
photo("04-hero", "ref1-hero-amber", "I'm AI. So is this business.")
photo("05-presenting", "ref4-presenting", "Can't code? Build it with AI.")
print("ALL 5 IMAGES DONE")
