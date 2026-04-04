#!/usr/bin/env python3
"""
Sentence-level benchmark for Turkish diacritics disambiguation.

Tests context-dependent words where the same ASCII form maps to different
diacritics forms depending on meaning. This is where ML models should
outperform rule-based lookup.

Each test case: (ascii_sentence, correct_sentence, ambiguous_word, note)
"""

import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DICTS_DIR = os.path.join(PROJECT_DIR, "hooks", "dicts")
MODEL_PATH = "/tmp/byt5-turkish-diacritics"

# Sentence pairs: ASCII input -> correct output
# Each tuple: (ascii_sentence, correct_sentence, target_word, note)
# "keep" = word should stay ASCII, "change" = word needs diacritics
TEST_SENTENCES = [
    # --- Context-dependent ambiguous words (skip list) ---
    # These words exist in both ASCII and diacritics forms with different meanings.
    # The correct form depends on sentence context.
    #
    # kur: kur (exchange rate, set up) vs kür (cure)
    ("doviz kuru yukseldi", "döviz kuru yükseldi", "kur", "keep kur: exchange rate"),
    ("kaplica kuru basladik", "kaplıca kürü başladık", "kur", "change kür: spa cure"),
    # sac: sac (sheet metal) vs saç (hair)
    ("sacini kestirdi", "saçını kestirdi", "sac", "change saç: hair"),
    ("sac levha bukuldü", "sac levha büküldü", "sac", "keep sac: sheet metal"),
    # tas: taş (stone) vs tas (bowl)
    (
        "yolda buyuk bir tas vardi",
        "yolda büyük bir taş vardı",
        "tas",
        "change taş: stone",
    ),
    ("hamam tasi getir", "hamam tası getir", "tas", "keep tas: bowl"),
    # bas: baş (head) vs bas (press/step)
    ("bas agrisi cekiyorum", "baş ağrısı çekiyorum", "bas", "change baş: headache"),
    ("dugmeye bas", "düğmeye bas", "bas", "keep bas: press the button"),
    # tur: tür (type/species) vs tur (tour)
    (
        "bu tur hayvanlar nadir bulunur",
        "bu tür hayvanlar nadir bulunur",
        "tur",
        "change tür: species",
    ),
    ("sehir turu yapacagiz", "şehir turu yapacağız", "tur", "keep tur: city tour"),
    # kor: kör (blind) vs kor (ember)
    ("kor atesde kozu pisirdik", "kor ateşte közü pişirdik", "kor", "keep kor: ember"),
    # omur: ömür (life) vs omur (vertebra)
    ("omur boyu devam eder", "ömür boyu devam eder", "omur", "change ömür: lifetime"),
    # koy: köy (village) vs koy (put)
    (
        "koy meydaninda toplandi",
        "köy meydanında toplandı",
        "koy",
        "change köy: village",
    ),
    ("cantayi masaya koy", "çantayı masaya koy", "koy", "keep koy: put"),
    # --- Full sentence restoration (unambiguous diacritics) ---
    (
        "turkce ogrenmek istiyorum",
        "Türkçe öğrenmek istiyorum",
        "turkce",
        "change: all diacritics",
    ),
    ("bu urun cok guzel", "bu ürün çok güzel", "urun", "change: all diacritics"),
    (
        "ozellikle bu konuda hassasiz",
        "özellikle bu konuda hassasız",
        "ozellikle",
        "change: all diacritics",
    ),
    (
        "gelistirici araci kullaniyoruz",
        "geliştirici aracı kullanıyoruz",
        "gelistirici",
        "change: all diacritics",
    ),
    (
        "gunluk calisma rutini",
        "günlük çalışma rutini",
        "gunluk",
        "change: all diacritics",
    ),
    (
        "cocuklarin gozleri parliyordu",
        "çocukların gözleri parlıyordu",
        "gozleri",
        "change: all diacritics",
    ),
    (
        "ogretmen ogrencilere sordu",
        "öğretmen öğrencilere sordu",
        "ogretmen",
        "change: all diacritics",
    ),
    (
        "gunes batida batiyordu",
        "güneş batıda batıyordu",
        "gunes",
        "change: all diacritics",
    ),
    (
        "kucuk cocuk aglamaya basladi",
        "küçük çocuk ağlamaya başladı",
        "kucuk",
        "change: all diacritics",
    ),
    (
        "ulke ekonomisi buyuyor",
        "ülke ekonomisi büyüyor",
        "ulke",
        "change: all diacritics",
    ),
    (
        "gercekten cok guzel bir yer",
        "gerçekten çok güzel bir yer",
        "gercekten",
        "change: all diacritics",
    ),
    (
        "ucak saat beste kalkiyor",
        "uçak saat beşte kalkıyor",
        "ucak",
        "change: all diacritics",
    ),
    # --- Mixed: English/tech loanwords should stay ---
    (
        "bu test basarili gecti",
        "bu test başarılı geçti",
        "test",
        "keep test, change rest",
    ),
    ("role tanimi yapildi", "role tanımı yapıldı", "role", "keep role, change rest"),
    (
        "rust programlama dili hizli",
        "rust programlama dili hızlı",
        "rust",
        "keep rust, change rest",
    ),
    # --- Ambiguous loanwords in Turkish context ---
    (
        "nisan ayinda tatile cikacagiz",
        "nisan ayında tatile çıkacağız",
        "nisan",
        "keep nisan: April",
    ),
    ("mac sonucu aciklandi", "maç sonucu açıklandı", "mac", "change maç: match"),
]


def load_lookup():
    lookup = {}
    path = os.path.join(DICTS_DIR, "ambiguous-lookup.tsv")
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) == 2:
                lookup[parts[0].lower()] = parts[1].split(",")[0].strip()
    return lookup


def load_skip():
    skip = set()
    path = os.path.join(DICTS_DIR, "ambiguous-skip.dic")
    with open(path, encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if w:
                skip.add(w.lower())
    return skip


def rule_based_restore(sentence, lookup, skip):
    """Word-by-word lookup restoration (simulates Layer 3)."""
    words = sentence.split()
    result = []
    for w in words:
        wl = w.lower()
        if wl in skip:
            result.append(w)
        elif wl in lookup:
            result.append(lookup[wl])
        else:
            result.append(w)
    return " ".join(result)


def load_model():
    try:
        from transformers import T5ForConditionalGeneration, AutoTokenizer
    except ImportError:
        print("ERROR: pip install transformers torch")
        sys.exit(1)

    path = (
        MODEL_PATH if os.path.isdir(MODEL_PATH) else "ceaksan/byt5-turkish-diacritics"
    )
    print(f"Loading model from: {path}")
    tokenizer = AutoTokenizer.from_pretrained(path)
    model = T5ForConditionalGeneration.from_pretrained(path)
    model.eval()
    return model, tokenizer


def model_restore(sentence, model, tokenizer):
    import torch

    inputs = tokenizer("restore: " + sentence, return_tensors="pt")
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=len(sentence) * 2,
            num_beams=1,
            do_sample=False,
        )
    return tokenizer.decode(outputs[0], skip_special_tokens=True).strip()


def score_restoration(predicted, expected):
    """Score how well the predicted sentence matches expected."""
    pred_words = predicted.lower().split()
    exp_words = expected.lower().split()

    if predicted.lower() == expected.lower():
        return "exact", 1.0

    if len(pred_words) != len(exp_words):
        return "length_mismatch", 0.0

    matches = sum(1 for p, e in zip(pred_words, exp_words) if p == e)
    ratio = matches / len(exp_words)
    if ratio >= 0.8:
        return "partial", ratio
    return "wrong", ratio


def run():
    print("=" * 70)
    print("Sentence-Level Diacritics Benchmark")
    print("=" * 70)
    print(f"Test sentences: {len(TEST_SENTENCES)}")

    lookup = load_lookup()
    skip = load_skip()

    # Rule-based
    print(f"\n{'─' * 70}")
    print("RULE-BASED (word-level lookup)")
    print(f"{'─' * 70}")

    rb_results = []
    for ascii_s, correct_s, target, note in TEST_SENTENCES:
        predicted = rule_based_restore(ascii_s, lookup, skip)
        category, score = score_restoration(predicted, correct_s)
        rb_results.append(
            (ascii_s, correct_s, predicted, target, note, category, score)
        )

    rb_exact = sum(1 for r in rb_results if r[5] == "exact")
    rb_partial = sum(1 for r in rb_results if r[5] == "partial")
    print(
        f"  Exact: {rb_exact}/{len(TEST_SENTENCES)} ({rb_exact / len(TEST_SENTENCES) * 100:.1f}%)"
    )
    print(f"  Partial: {rb_partial}/{len(TEST_SENTENCES)}")

    # ByT5
    print(f"\n{'─' * 70}")
    print("BYT5 MODEL (sentence-level)")
    print(f"{'─' * 70}")

    model, tokenizer = load_model()

    ml_results = []
    t0 = time.time()
    for i, (ascii_s, correct_s, target, note) in enumerate(TEST_SENTENCES):
        predicted = model_restore(ascii_s, model, tokenizer)
        category, score = score_restoration(predicted, correct_s)
        ml_results.append(
            (ascii_s, correct_s, predicted, target, note, category, score)
        )
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i + 1}/{len(TEST_SENTENCES)}...")
    ml_time = time.time() - t0

    ml_exact = sum(1 for r in ml_results if r[5] == "exact")
    ml_partial = sum(1 for r in ml_results if r[5] == "partial")
    print(
        f"  Exact: {ml_exact}/{len(TEST_SENTENCES)} ({ml_exact / len(TEST_SENTENCES) * 100:.1f}%)"
    )
    print(f"  Partial: {ml_partial}/{len(TEST_SENTENCES)}")
    print(
        f"  Time: {ml_time:.1f}s ({ml_time / len(TEST_SENTENCES) * 1000:.0f}ms/sentence)"
    )

    # Comparison
    print(f"\n{'=' * 70}")
    print("COMPARISON")
    print(f"{'=' * 70}")
    print(f"{'Metric':<25} {'Rule-based':>15} {'ByT5':>15}")
    print(f"{'─' * 55}")
    print(
        f"{'Exact match':<25} {rb_exact / len(TEST_SENTENCES) * 100:>14.1f}% {ml_exact / len(TEST_SENTENCES) * 100:>14.1f}%"
    )

    # Detailed per-sentence comparison
    print(f"\n{'─' * 70}")
    print("DETAILED RESULTS")
    print(f"{'─' * 70}")
    print(f"{'#':<3} {'RB':>4} {'ML':>4}  Input -> Expected")
    print(f"{'─' * 70}")

    for i, (rb, ml) in enumerate(zip(rb_results, ml_results)):
        ascii_s, correct_s, rb_pred, target, note, rb_cat, _ = rb
        _, _, ml_pred, _, _, ml_cat, _ = ml

        rb_mark = "OK" if rb_cat == "exact" else "X"
        ml_mark = "OK" if ml_cat == "exact" else "X"

        print(f"{i + 1:<3} {rb_mark:>4} {ml_mark:>4}  [{note}]")
        if rb_cat != "exact" or ml_cat != "exact":
            print(f"{'':>13}IN:  {ascii_s}")
            print(f"{'':>13}EXP: {correct_s}")
            if rb_cat != "exact":
                print(f"{'':>13}RB:  {rb_pred}")
            if ml_cat != "exact":
                print(f"{'':>13}ML:  {ml_pred}")


if __name__ == "__main__":
    run()
