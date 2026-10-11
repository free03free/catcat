#!/usr/bin/env python3
"""
يولّد مسبقًا أصوات كل الحروف والحركات والمدود والكلمات والألوان والأرقام (1..1000) من tools/lessons.json
لكل الأصوات العشرة (0..9) بجودة عالية، ويضغطها بصيغة m4a (AAC) ويضعها في app/src/main/assets/tts-pre/v<رقم>/
فتدخل داخل الـ APK وتُنطق فورًا من أول ضغطة بأي صوت يختاره المستخدم، بلا تجهيز على الجهاز.
يعمل تلقائيًا أثناء البناء من fetch-engine.sh، ويُستأنف إن انقطع (يتخطى ما تم توليده).
الاستعمال اليدوي:  python3 tools/pregen.py --steps 8 --voices 0,9 --jobs 2
"""
import argparse, json, os, re, shutil, subprocess, sys, time, unicodedata
import numpy as np
from multiprocessing import get_context

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
ap = argparse.ArgumentParser()
ap.add_argument("--model", default=os.path.join(root, "app/src/main/assets/models/tts-ar"))
ap.add_argument("--out", default=os.path.join(root, "app/src/main/assets/tts-pre"))
ap.add_argument("--voices", default="0,1,2,3,4,5,6,7,8,9")
ap.add_argument("--steps", type=int, default=8)
ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
ap.add_argument("--bitrate", default="48k")
ap.add_argument("--budget-min", type=float, default=0, help="أقصى مدة بالدقائق في هذه الدورة (0 = بلا حد)")
ap.add_argument("--limit", type=int, default=0, help="للتجربة فقط")
a = ap.parse_args()

FF = shutil.which("ffmpeg")
if not FF:
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()

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

items = json.load(open(os.path.join(here, "lessons.json"), encoding="utf-8"))
if a.limit: items = items[:a.limit]
T0 = time.time()
DEADLINE = T0 + a.budget_min * 60 if a.budget_min else 0

def encode(pcm, path):
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "s16le", "-ar", "22050", "-ac", "1", "-i", "-",
                    "-c:a", "aac", "-b:a", a.bitrate, "-movflags", "+faststart", path], input=pcm, check=True)

def work(voice):
    import sherpa_onnx
    from scipy.signal import resample_poly
    d = a.model
    cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
            duration_predictor=f"{d}/duration_predictor.int8.onnx", text_encoder=f"{d}/text_encoder.int8.onnx",
            vector_estimator=f"{d}/vector_estimator.int8.onnx", vocoder=f"{d}/vocoder.int8.onnx",
            tts_json=f"{d}/tts.json", unicode_indexer=f"{d}/unicode_indexer.bin", voice_style=f"{d}/voice.bin"),
        num_threads=1))
    tts = sherpa_onnx.OfflineTts(cfg)
    od = os.path.join(a.out, f"v{voice}"); os.makedirs(od, exist_ok=True)
    ip = os.path.join(od, "index.json")
    index = {"rate": 22050, "format": "m4a", "steps": a.steps, "voice": voice, "items": {}}
    if os.path.exists(ip):
        try:
            old = json.load(open(ip, encoding="utf-8"))
            if old.get("steps") == a.steps and old.get("format") == "m4a": index["items"] = old.get("items", {})
        except Exception: pass
    def save(): json.dump(index, open(ip, "w", encoding="utf-8"), ensure_ascii=False)
    made = 0; stopped = False
    for n, (text, sp) in enumerate(items):
        c = clean(text); key = f"{int(sp * 100 + 0.5)}|{c}"
        fn = f"{n:05d}.m4a"
        if key in index["items"] and os.path.exists(os.path.join(od, index["items"][key])): continue
        if DEADLINE and time.time() > DEADLINE: stopped = True; break
        g = sherpa_onnx.GenerationConfig(); g.sid = voice; g.speed = float(sp); g.num_steps = a.steps; g.extra = {"lang": "ar"}
        r = tts.generate(c, g)
        s = trim(np.asarray(r.samples, dtype=np.float32), r.sample_rate)
        if r.sample_rate != 22050: s = resample_poly(s, 22050, r.sample_rate).astype(np.float32)
        pk = float(np.abs(s).max()) or 1.0
        encode((s / pk * 0.95 * 32767).astype("<i2").tobytes(), os.path.join(od, fn))
        index["items"][key] = fn; made += 1
        if made % 25 == 0:
            save(); print(f"صوت {voice}: {len(index['items'])}/{len(items)}  ({int(time.time()-T0)}s)", flush=True)
    save()
    print(f"صوت {voice}: {'توقّف مؤقتًا' if stopped else 'اكتمل'} {len(index['items'])}/{len(items)}", flush=True)
    return voice, (not stopped)

if __name__ == "__main__":
    voices = [int(x) for x in a.voices.split(",") if x.strip() != ""]
    os.makedirs(a.out, exist_ok=True)
    done_mark = os.path.join(a.out, ".complete")
    if os.path.exists(done_mark): os.remove(done_mark)
    with get_context("fork").Pool(max(1, min(a.jobs, len(voices)))) as pool:
        res = pool.map(work, voices, chunksize=1)
    size = 0
    for v in voices:
        vd = os.path.join(a.out, f"v{v}")
        if os.path.isdir(vd): size += sum(os.path.getsize(os.path.join(vd, f)) for f in os.listdir(vd))
    ok = all(r[1] for r in res)
    if ok and not a.limit:
        open(done_mark, "w").write("ok")
        print(f"اكتمل: {len(voices)} أصوات ({round(size/1e6,1)} MB)")
    else:
        print(f"توقّف مؤقتًا بسبب حدّ الوقت ({round(size/1e6,1)} MB حتى الآن). أعد البناء لإكمال الباقي.")
