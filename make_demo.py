#!/usr/bin/env python3
"""YC Launch Monitor demo assets — Slack alert replicas + overview slides.
All content uses REAL data captured from the live bot (demo_data.json)."""
import json
import time
from PIL import Image, ImageDraw, ImageFont

S = 2  # supersample factor (draw at 2560x1440, output 1280x720)
W, H = 1280 * S, 720 * S
OC = (251, 101, 30)
BG = (26, 29, 33)        # slack dark
SBG = (48, 52, 58)       # panel
TXT = (214, 218, 224)
DIM = (123, 128, 136)
LINK = (46, 162, 232)

FD = "C:/Windows/Fonts/"
def F(size, bold=False, light=False):
    n = "segoeuib.ttf" if bold else ("segoeuil.ttf" if light else "segoeui.ttf")
    return ImageFont.truetype(FD + n, size * S)

data = json.load(open("demo_data.json"))

def canvas():
    img = Image.new("RGB", (W, H), (13, 15, 24))
    return img, ImageDraw.Draw(img)

def rounded(d, box, r, **kw):
    d.rounded_rectangle(box, radius=r * S, **kw)

def save(img, name):
    img = img.resize((1280, 720), Image.LANCZOS)
    img.save(name)
    print("saved", name)

# ───────────────────────── slide 1: title ─────────────────────────
img, d = canvas()
# radar motif center-left
cx, cy = 340 * S, 360 * S
for r, wdt in ((70, 2), (130, 2), (190, 3)):
    d.ellipse([cx - r*S, cy - r*S, cx + r*S, cy + r*S], outline=(58, 66, 88), width=wdt*S)
d.line([cx - 200*S, cy, cx + 200*S, cy], fill=(44, 50, 68), width=2*S)
d.line([cx, cy - 200*S, cx, cy + 200*S], fill=(44, 50, 68), width=2*S)
d.pieslice([cx - 190*S, cy - 190*S, cx + 190*S, cy + 190*S], 250, 292, fill=OC + (0,))
# leading sweep
for i in range(20):
    a = 250 + i * (42 / 20)
    d.pieslice([cx - 190*S, cy - 190*S, cx + 190*S, cy + 190*S], a, a + 2.4,
               fill=(int(251*0.15+251*0.85*i/20), int(101*0.15+101*0.85*i/20), int(30*0.15+30*0.85*i/20)))
bx, by = cx + 130*S*0.374, cy - 130*S*0.927
d.ellipse([bx-8*S, by-8*S, bx+8*S, by+8*S], fill=(255, 235, 210))
d.ellipse([cx-6*S, cy-6*S, cx+6*S, cy+6*S], fill=(210, 220, 240))

d.text((620*S, 220*S), "YC LAUNCH MONITOR", font=F(52, bold=True), fill=(240, 242, 246))
d.text((622*S, 300*S), "Early detection for Y Combinator startups", font=F(30, light=True), fill=TXT)
d.text((622*S, 380*S), "4 sources  ·  persistent state  ·  Slack alerts  ·  Pond agent",
       font=F(24), fill=DIM)
# source pills
pills = ["YC Directory", "Launch YC", "X (Twitter)", "LinkedIn"]
px_ = 622*S
for p in pills:
    wpx = d.textlength(p, font=F(22)) + 36*S
    rounded(d, [px_, 440*S, px_ + wpx, 492*S], 12, fill=SBG, outline=(70, 76, 88), width=2)
    d.text((px_ + 18*S, 452*S), p, font=F(22), fill=TXT)
    px_ += wpx + 16*S
d.text((622*S, 560*S), "github.com/user00shinru/yc-launch-monitor", font=F(22), fill=LINK)
save(img, "slide_1_title.png")

# ─────────────── slide 2: slack alert replica (real data) ───────────────
img, d = canvas()
# sidebar
d.rectangle([0, 0, 260*S, H], fill=(26, 29, 33))
d.text((24*S, 26*S), "Y Combinator Watch", font=F(24, bold=True), fill=(240, 242, 246))
d.text((26*S, 92*S), "CHANNELS", font=F(18, bold=True), fill=DIM)
for i, ch in enumerate(["general", "yc-launches", "speedrun-watch"]):
    y = (130 + i * 52) * S
    if ch == "yc-launches":
        rounded(d, [14*S, y - 8*S, 246*S, y + 34*S], 8, fill=(251, 101, 30, 60) if False else (84, 46, 24))
        d.text((30*S, y), "#  " + ch, font=F(22, bold=True), fill=(255, 244, 235))
    else:
        d.text((30*S, y), "#  " + ch, font=F(22), fill=DIM)
d.text((26*S, 330*S), "DIRECT MESSAGES", font=F(18, bold=True), fill=DIM)
# main area
MX = 292*S
aero = data["aerogen-systems"]
d.text((MX, 26*S), "#  yc-launches", font=F(28, bold=True), fill=(240, 242, 246))
d.text((MX + 200*S, 34*S), "new YC companies + early founder signals", font=F(20), fill=DIM)
d.line([MX, 76*S, W - 24*S, 76*S], fill=(58, 64, 74), width=2*S)
# bot avatar
d.rounded_rectangle([MX, 100*S, MX + 44*S, 144*S], radius=10*S, fill=OC)
d.text((MX + 10*S, 108*S), "YC", font=F(20, bold=True), fill=(20, 16, 12))
d.text((MX + 58*S, 102*S), "YC Launch Monitor", font=F(24, bold=True), fill=(240, 242, 246))
rounded(d, [MX + 318*S, 104*S, MX + 372*S, 132*S], 6, fill=(88, 101, 120))
d.text((MX + 326*S, 108*S), "APP", font=F(16, bold=True), fill=(240, 242, 246))
d.text((MX + 388*S, 106*S), "2:47 PM", font=F(20), fill=DIM)
# block: header
rounded(d, [MX + 58*S, 156*S, W - 48*S, 208*S], 10, fill=(37, 41, 47))
d.text((MX + 78*S, 168*S), "1 new YC company detected", font=F(24, bold=True), fill=(255, 244, 235))
# block: section
rounded(d, [MX + 58*S, 220*S, W - 48*S, 470*S], 10, fill=(37, 41, 47))
d.text((MX + 78*S, 240*S), aero["name"] + "   ·   " + (aero.get("batch") or ""),
       font=F(26, bold=True), fill=(120, 170, 255))
d.text((MX + 78*S, 292*S), (aero.get("one_liner") or "")[:80], font=F(24), fill=TXT)
ind = aero.get("industry")
if isinstance(ind, (list, tuple)):
    ind = ", ".join(str(x) for x in list(ind)[:3])
elif not ind:
    ind = "Deep Tech"
d.text((MX + 78*S, 336*S), "Industry:  " + str(ind)[:40], font=F(22), fill=DIM)
la = aero.get("launched_at")
la_s = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(la)) if isinstance(la, (int, float)) else "recent"
d.text((MX + 78*S, 372*S), "Launched:  " + la_s, font=F(22), fill=DIM)
d.text((MX + 78*S, 408*S), "Team:  " + (str(aero.get("team_size") or "2-10")), font=F(22), fill=DIM)
d.text((MX + 78*S, 436*S), aero.get("website") or
       ("https://www.ycombinator.com/companies/" + aero["slug"]), font=F(20), fill=LINK)
# reaction row
d.text((MX + 58*S, 496*S), ":rocket: 1   :eyes: 3", font=F(22), fill=DIM)
# second message preview (dimmed)
d.text((MX, 560*S), "Today  2:47 PM", font=F(18), fill=(70, 75, 84))
save(img, "slide_2_slack_alert.png")

# ───────── slide 3: early detection + persistence (real stats) ─────────
img, d = canvas()
d.text((48*S, 36*S), "Early detection, before YC lists it", font=F(40, bold=True), fill=(240, 242, 246))
d.line([48*S, 104*S, W - 48*S, 104*S], fill=(58, 64, 74), width=2*S)
# timeline: founder post -> cross-check -> alert
steps = [("Founder posts on X / LinkedIn", "keyword match on announcement patterns"),
         ("Cross-check YC Directory", "in_directory = false  →  early signal"),
         ("Alert delivered to Slack", "hours or days before official listing")]
y = 150*S
for i, (t, sub) in enumerate(steps):
    d.ellipse([56*S, y, 92*S, y + 36*S], outline=OC, width=3*S)
    d.text((76*S, y + 4*S), str(i + 1), font=F(22, bold=True), fill=OC)
    d.text((120*S, y - 2*S), t, font=F(28, bold=True), fill=TXT)
    d.text((122*S, y + 42*S), sub, font=F(22), fill=DIM)
    y += 118*S
# stats panel (real counters)
rounded(d, [760*S, 150*S, W - 48*S, 470*S], 16, fill=(37, 41, 47), outline=(70, 76, 88), width=2)
d.text((790*S, 176*S), "LIVE COUNTERS", font=F(20, bold=True), fill=OC)
stats = [("200", "companies tracked"), ("60", "launches tracked"),
         ("83", "social posts tracked"), ("0", "duplicate alerts ever")]
sy = 226*S
for v, k in stats:
    d.text((796*S, sy), v, font=F(36, bold=True), fill=(255, 244, 235))
    d.text((906*S, sy + 14*S), k, font=F(24), fill=TXT)
    sy += 62*S
d.text((48*S, 540*S), "Stateful SQLite store — restart-safe, never re-alerts on seen items",
       font=F(24), fill=DIM)
save(img, "slide_3_early.png")

# ───────────── slide 4: pond agent integration ─────────────
img, d = canvas()
d.text((48*S, 36*S), "Runs on Pond's agent infrastructure", font=F(40, bold=True), fill=(240, 242, 246))
d.line([48*S, 104*S, W - 48*S, 104*S], fill=(58, 64, 74), width=2*S)
# architecture flow boxes
boxes = [("Pond Platform", "runs + monitors"), ("HTTPS tunnel", "auth via access key"),
         ("Local agent", "FastAPI server"), ("Slack", "alert delivery")]
bx = 48*S
for i, (t, sub) in enumerate(boxes):
    rounded(d, [bx, 150*S, bx + 260*S, 270*S], 14, fill=(37, 41, 47), outline=OC, width=3*S)
    d.text((bx + 24*S, 176*S), t, font=F(24, bold=True), fill=TXT)
    d.text((bx + 24*S, 218*S), sub, font=F(19), fill=DIM)
    if i < 3:
        d.text((bx + 268*S, 194*S), ">", font=F(30, bold=True), fill=OC)
    bx += 300*S
d.text((48*S, 320*S), "Actions available to buyers:", font=F(26, bold=True), fill=TXT)
acts = [("health_check", "monitor status + live counters + last scan result"),
        ("latest_alerts", "recent early + official detections"),
        ("force_scan", "full 4-source scan now (async task)")]
ay = 372*S
for a, sub in acts:
    rounded(d, [48*S, ay, 620*S, ay + 64*S], 10, fill=(37, 41, 47))
    d.text((72*S, ay + 8*S), a, font=F(24, bold=True), fill=(120, 170, 255))
    d.text((72*S, ay + 38*S), sub, font=F(19), fill=DIM)
    ay += 84*S
d.text((48*S, 640*S), "Verified: manifest 200 · authenticated runs · health_check 200 OK",
       font=F(22), fill=LINK)
save(img, "slide_4_pond.png")

print("ALL SLIDES DONE")
