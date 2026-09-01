#!/usr/bin/env python3
"""Render real Slack alert outputs (exact _fmt_company block structure) as PNG."""
import json
import time
from PIL import Image, ImageDraw, ImageFont

S = 2
W, H = 1280 * S, 860 * S
FD = "C:/Windows/Fonts/"
def F(size, bold=False, light=False):
    n = "segoeuib.ttf" if bold else ("segoeuil.ttf" if light else "segoeui.ttf")
    return ImageFont.truetype(FD + n, size * S)

TXT = (214, 218, 224)
DIM = (123, 128, 136)
LINK = (46, 162, 232)

def render_msg(d, draw_img_fn):
    pass

def fmt_company_block(c):
    """mirror slack_alert._fmt_company exactly"""
    name = c.get("name") or "Unknown"
    one = c.get("one_liner") or ""
    batch = c.get("batch") or "?"
    slug = c.get("slug") or ""
    url = c.get("website") or f"https://www.ycombinator.com/companies/{slug}"
    loc = c.get("all_locations") or ""
    industry = c.get("industry") or ""
    team = c.get("team_size")
    la = c.get("launched_at")
    la_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(la)) if isinstance(la, (int, float)) else ""
    head = f"{name}  ·  `{batch}`"
    if loc:
        head += f"  ·  🌍 {loc}"
    if isinstance(team, int) and team:
        head += f"  ·  👥 {team}"
    fields = [f for f in (one, f"*Industry:* {industry}" if industry else "",
                          f"*Launched:* {la_str}" if la_str else "") if f]
    return head, fields, url

data = json.load(open("examples_data.json"))
picks = ["aerogen-systems", "maritime", "quippy"]

img = Image.new("RGB", (W, H), (26, 29, 33))
d = ImageDraw.Draw(img)
d.text((30 * S, 22 * S), "#  yc-launches", font=F(26, bold=True), fill=(240, 242, 246))
d.text((30 * S, 64 * S), "Slack output — real alerts posted by YC Launch Monitor",
       font=F(19), fill=DIM)
d.line([30 * S, 100 * S, W - 30 * S, 100 * S], fill=(58, 64, 74), width=2 * S)

y = 124 * S
MX = 30 * S
n_msgs = 0
for slug in picks:
    c = data[slug]
    head, fields, url = fmt_company_block(c)
    # avatar
    d.rounded_rectangle([MX, y, MX + 40 * S, y + 40 * S], radius=9 * S, fill=(251, 101, 30))
    d.text((MX + 8 * S, y + 5 * S), "YC", font=F(18, bold=True), fill=(20, 16, 12))
    d.text((MX + 54 * S, y - 2 * S), "YC Launch Monitor", font=F(21, bold=True), fill=(240, 242, 246))
    rounded = d.rounded_rectangle([MX + 268 * S, y, MX + 316 * S, y + 25 * S], radius=6 * S,
                                  fill=(88, 101, 120))
    d.text((MX + 274 * S, y + 3 * S), "APP", font=F(14, bold=True), fill=(240, 242, 246))
    y += 52 * S
    # header block
    d.rounded_rectangle([MX, y, W - 30 * S, y + 42 * S], radius=9 * S, fill=(37, 41, 47))
    d.text((MX + 16 * S, y + 8 * S), "🚀 1 new YC company detected", font=F(21, bold=True),
           fill=(255, 244, 235))
    y += 54 * S
    # section block
    n_lines = len(fields)
    bh = 46 * S + n_lines * 34 * S
    d.rounded_rectangle([MX, y, W - 30 * S, y + bh], radius=9 * S, fill=(37, 41, 47))
    ty = y + 10 * S
    # name line — avoid emoji glyphs
    head_clean = head.replace("🌍", "·").replace("👥", "team").replace("  ·  team", "  ·  team")
    parts = head_clean.split("`")
    x = MX + 16 * S
    fnt_b = F(20, bold=True)
    for i, seg in enumerate(parts):
        col = (120, 170, 255) if i % 2 else (230, 232, 236)
        if i % 2 == 0 and i > 0:
            d.text((x, ty), "  ·  ", font=F(20), fill=DIM)
            x += d.textlength("  ·  ", font=F(20))
        d.text((x, ty), seg, font=fnt_b if i == 0 else F(20), fill=col if i else (120, 170, 255))
        x += d.textlength(seg, font=fnt_b if i == 0 else F(20))
    ty += 36 * S
    for j, fl in enumerate(fields):
        txt = fl.replace("*", "")
        d.text((MX + 16 * S, ty), txt, font=F(18, bold=(j == 0)), fill=TXT if j == 0 else DIM)
        ty += 34 * S
    d.text((MX + 16 * S, y + bh - 30 * S), url, font=F(16), fill=LINK)
    y += bh + 26 * S

img = img.resize((1280, 860), Image.LANCZOS)
img.save("examples_slack_output.png")
print("saved examples_slack_output.png")
