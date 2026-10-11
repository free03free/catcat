#!/usr/bin/env python3
"""
يولّد مسبقًا أصوات كل الحروف والحركات والمدود والكلمات والألوان والأرقام (1..1000) من tools/lessons.json
ويضعها في app/src/main/assets/tts-pre/ لتُنطق فورًا من أول ضغطة بلا تجهيز على الجهاز.
يعمل تلقائيًا أثناء البناء من fetch-engine.sh، ويُستأنف إن انقطع (يتخطى ما تم توليده).
الاستعمال اليدوي:  python3 tools/pregen.py --voice 9 --steps 8 --budget-min 20
"""
import argparse, json, os, re, sys, time, unicodedata
import numpy as np
import sherpa_onnx
from scipy.signal import resample_poly

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
ap = argparse.ArgumentParser()
ap.add_argument("--model", default=os.path.join(root, "app/src/main/assets/models/tts-ar"))
ap.add_argument("--out", default=os.path.join(root, "app/src/main/assets/tts-pre"))
ap.add_argument("--voice", type=int, default=9)
ap.add_argument("--steps", type=int, default=8)
ap.add_argument("--threads", type=int, default=os.cpu_count() or 2)
ap.add_argument("--budget-min", type=float, default=0, help="أقصى مدة بالدقائق في هذه الدورة (0 = بلا حد)")
ap.add_argument("--limit", type=int, default=0, help="للتجربة فقط")
a = ap.parse_args()

def clean(t):  # نفس clean() في EchoEngine.java
    t = "".join(" " if unicodedata.category(c) in ("So", "Cs", "Cn") else c for c in t)
    t = t.replace("\u0640", "")
    t = re.sub(r'["«»()\[\]*_#]', " ", t)
    return re.sub(r"\s+", " ", t).strip()

def trim(s, sr):  # نفس trim() في EchoEngine.java
    pk = float(np.abs(s).max()) if len(s) else 0
    if pk < 1e-4: return s
    th = max(0.012 * pk, 1e-4)
    idx = np.where(np.abs(s) >= th)[0]
    f = max(0, int(idx[0]) - sr * 100 // 1000); t = min(len(s), int(idx[-1]) + 1 + sr * 260 // 1000)
    return s[f:t] if t - f >= 16 else s

d = a.model
cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
        duration_predictor=f"{d}/duration_predictor.int8.onnx", text_encoder=f"{d}/text_encoder.int8.onnx",
        vector_estimator=f"{d}/vector_estimator.int8.onnx", vocoder=f"{d}/vocoder.int8.onnx",
        tts_json=f"{d}/tts.json", unicode_indexer=f"{d}/unicode_indexer.bin", voice_style=f"{d}/voice.bin"),
    num_threads=a.threads))
tts = sherpa_onnx.OfflineTts(cfg)
items = json.load(open(os.path.join(here, "lessons.json"), encoding="utf-8"))
if a.limit: items = items[:a.limit]
os.makedirs(a.out, exist_ok=True)
ip = os.path.join(a.out, "index.json")
index = {"rate": 22050, "voice": a.voice, "items": {}}
if os.path.exists(ip):
    try:
        old = json.load(open(ip, encoding="utf-8"))
        if old.get("voice") == a.voice: index["items"] = old.get("items", {})
    except Exception: pass

def save(): json.dump(index, open(ip, "w", encoding="utf-8"), ensure_ascii=False)

t0 = time.time(); done = 0; stopped = False
for n, (text, sp) in enumerate(items):
    c = clean(text); key = f"{int(sp * 100 + 0.5)}|{c}"
    fn = f"{n:05d}.pcm"
    if key in index["items"] and os.path.exists(os.path.join(a.out, index["items"][key])): continue
    if a.budget_min and time.time() - t0 > a.budget_min * 60: stopped = True; break
    g = sherpa_onnx.GenerationConfig(); g.sid = a.voice; g.speed = float(sp); g.num_steps = a.steps; g.extra = {"lang": "ar"}
    r = tts.generate(c, g)
    s = trim(np.asarray(r.samples, dtype=np.float32), r.sample_rate)
    if r.sample_rate != 22050: s = resample_poly(s, 22050, r.sample_rate).astype(np.float32)
    pk = float(np.abs(s).max()) or 1.0
    (s / pk * 0.95 * 32767).astype("<i2").tofile(os.path.join(a.out, fn))
    index["items"][key] = fn; done += 1
    if done % 25 == 0:
        save(); print(f"{len(index['items'])}/{len(items)}", flush=True)
save()
total = len(index["items"])
mb = round(sum(os.path.getsize(os.path.join(a.out, f)) for f in index["items"].values() if os.path.exists(os.path.join(a.out, f))) / 1e6, 1)
if stopped:
    print(f"توقّف مؤقتًا بسبب حدّ الوقت: {total}/{len(items)} ({mb} MB). أعد البناء لإكمال الباقي.")
else:
    open(os.path.join(a.out, ".complete"), "w").write("ok")
    print(f"اكتمل: {total} عنصرًا ({mb} MB)")
