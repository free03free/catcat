حزمة الأصوات الجاهزة (app/src/main/assets/tts-pre)
- فيها 356 نطقًا: كل الحروف والحركات والمدود والكلمات والألوان والأرقام حتى 30 وعبارات التطبيق، بالصوت 10 وسرعة النطق الافتراضية 0.9.
- هذه تُنطق فورًا من أول ضغطة. أي شيء خارجها (صوت آخر، سرعة غير 0.9، أرقام فوق 30، ترديد كلامك) يُولَّد وقت الاستعمال ويُحفظ بعدها.
لتغيير الصوت داخل الحزمة:
    pip install sherpa-onnx numpy scipy
    bash fetch-engine.sh                      # ينزّل النموذج إلى app/src/main/assets/models/tts-ar
    rm -rf app/src/main/assets/tts-pre
    python tools/pregen.py --voice 6 --steps 6
ثم أعد بناء الـ APK.
