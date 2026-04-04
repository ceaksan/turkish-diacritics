#!/usr/bin/env python3
"""
Rule-based vs ByT5 Model Comparison Benchmark

Compares the hook's Layer 3 lookup table against the fine-tuned ByT5 model
on the same test set (ambiguous-lookup.tsv) and false positive sets.
"""

import os
import random
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DICTS_DIR = os.path.join(PROJECT_DIR, "hooks", "dicts")

AMBIGUOUS_LOOKUP = os.path.join(DICTS_DIR, "ambiguous-lookup.tsv")
WHITELIST_DIC = os.path.join(DICTS_DIR, "whitelist.dic")
TECH_DIC = os.path.join(DICTS_DIR, "tech.dic")

MODEL_PATH = "/tmp/byt5-turkish-diacritics"
SAMPLE_SIZE = 200
FP_SAMPLE_SIZE = 50


def load_lookup(path):
    lookup = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            ascii_form, diacritics_forms = line.split("\t", 1)
            all_forms = [f.strip() for f in diacritics_forms.split(",")]
            lookup[ascii_form.lower()] = all_forms
    return lookup


def load_word_set(path):
    words = set()
    if not os.path.isfile(path):
        return words
    with open(path, encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if w and not w.isdigit():
                words.add(w.lower())
    return words


def rule_based_predict(word, lookup):
    return lookup.get(word.lower(), [word])[0]


def load_model():
    try:
        from transformers import T5ForConditionalGeneration, AutoTokenizer
        import torch
    except ImportError:
        print("ERROR: transformers/torch not installed. pip install transformers torch")
        sys.exit(1)

    path = (
        MODEL_PATH if os.path.isdir(MODEL_PATH) else "ceaksan/byt5-turkish-diacritics"
    )
    print(f"Loading model from: {path}")
    tokenizer = AutoTokenizer.from_pretrained(path)
    model = T5ForConditionalGeneration.from_pretrained(path)
    model.eval()
    return model, tokenizer


def model_predict(word, model, tokenizer):
    import torch

    inputs = tokenizer("restore: " + word, return_tensors="pt")
    with torch.no_grad():
        outputs = model.generate(
            **inputs, max_new_tokens=len(word) + 10, num_beams=1, do_sample=False
        )
    return tokenizer.decode(outputs[0], skip_special_tokens=True).strip()


def run_benchmark():
    print("=" * 60)
    print("Rule-based vs ByT5 Comparison Benchmark")
    print("=" * 60)

    lookup = load_lookup(AMBIGUOUS_LOOKUP)
    whitelist = load_word_set(WHITELIST_DIC)
    tech = load_word_set(TECH_DIC)
    fp_words = list(whitelist | tech)

    all_pairs = [(k, v) for k, v in lookup.items()]
    print(f"\nTotal lookup pairs: {len(all_pairs)}")
    print(f"False positive pool: {len(fp_words)} words")

    random.seed(42)
    sample = random.sample(all_pairs, min(SAMPLE_SIZE, len(all_pairs)))
    fp_sample = random.sample(fp_words, min(FP_SAMPLE_SIZE, len(fp_words)))

    print(f"Test sample: {len(sample)} words")
    print(f"FP sample: {len(fp_sample)} words")

    # --- Rule-based benchmark ---
    print(f"\n{'─' * 60}")
    print("RULE-BASED (Layer 3 Lookup)")
    print(f"{'─' * 60}")

    rb_correct = 0
    rb_errors = []
    t0 = time.time()
    for ascii_w, expected_forms in sample:
        result = rule_based_predict(ascii_w, lookup)
        if result in expected_forms:
            rb_correct += 1
        else:
            rb_errors.append((ascii_w, expected_forms, result))
    rb_time = time.time() - t0

    rb_fp = 0
    rb_fp_errors = []
    for w in fp_sample:
        result = rule_based_predict(w, lookup)
        if result != w:
            rb_fp += 1
            rb_fp_errors.append((w, result))

    print(
        f"  Accuracy: {rb_correct}/{len(sample)} ({rb_correct / len(sample) * 100:.1f}%)"
    )
    print(f"  False positives: {rb_fp}/{len(fp_sample)}")
    print(f"  Time: {rb_time:.3f}s ({rb_time / len(sample) * 1000:.1f}ms/word)")

    # --- ByT5 benchmark ---
    print(f"\n{'─' * 60}")
    print("BYT5 MODEL")
    print(f"{'─' * 60}")

    model, tokenizer = load_model()

    ml_correct = 0
    ml_errors = []
    t0 = time.time()
    for i, (ascii_w, expected_forms) in enumerate(sample):
        result = model_predict(ascii_w, model, tokenizer)
        if result in expected_forms:
            ml_correct += 1
        else:
            ml_errors.append((ascii_w, expected_forms, result))
        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(sample)}...")
    ml_time = time.time() - t0

    ml_fp = 0
    ml_fp_errors = []
    t0_fp = time.time()
    for w in fp_sample:
        result = model_predict(w, model, tokenizer)
        if result.lower() != w.lower():
            ml_fp += 1
            ml_fp_errors.append((w, result))
    ml_fp_time = time.time() - t0_fp

    print(
        f"  Accuracy: {ml_correct}/{len(sample)} ({ml_correct / len(sample) * 100:.1f}%)"
    )
    print(f"  False positives: {ml_fp}/{len(fp_sample)}")
    print(f"  Time: {ml_time:.3f}s ({ml_time / len(sample) * 1000:.1f}ms/word)")

    # --- Comparison ---
    print(f"\n{'=' * 60}")
    print("COMPARISON")
    print(f"{'=' * 60}")
    print(f"{'Metric':<25} {'Rule-based':>15} {'ByT5':>15}")
    print(f"{'─' * 55}")
    print(
        f"{'Accuracy':<25} {rb_correct / len(sample) * 100:>14.1f}% {ml_correct / len(sample) * 100:>14.1f}%"
    )
    print(f"{'False positives':<25} {rb_fp:>14}  {ml_fp:>14} ")
    print(
        f"{'Speed (ms/word)':<25} {rb_time / len(sample) * 1000:>14.1f} {ml_time / len(sample) * 1000:>14.1f}"
    )

    # --- Disagreements ---
    rb_set = {e[0] for e in rb_errors}
    ml_set = {e[0] for e in ml_errors}
    only_rb_wrong = rb_set - ml_set
    only_ml_wrong = ml_set - rb_set
    both_wrong = rb_set & ml_set

    print(f"\n{'─' * 60}")
    print("DISAGREEMENTS")
    print(f"{'─' * 60}")
    print(f"  Only rule-based wrong: {len(only_rb_wrong)}")
    print(f"  Only ByT5 wrong:       {len(only_ml_wrong)}")
    print(f"  Both wrong:            {len(both_wrong)}")

    if only_ml_wrong:
        print(f"\n  ByT5 errors (rule-based got right):")
        for w in list(only_ml_wrong)[:10]:
            err = next(e for e in ml_errors if e[0] == w)
            print(f"    {w} -> {err[2]} (expected: {err[1][0]})")

    if only_rb_wrong:
        print(f"\n  Rule-based errors (ByT5 got right):")
        for w in list(only_rb_wrong)[:10]:
            err = next(e for e in rb_errors if e[0] == w)
            print(f"    {w} -> {err[2]} (expected: {err[1][0]})")

    if ml_fp_errors:
        print(f"\n  ByT5 false positives:")
        for w, r in ml_fp_errors[:10]:
            print(f"    {w} -> {r}")

    if rb_fp_errors:
        print(f"\n  Rule-based false positives:")
        for w, r in rb_fp_errors[:10]:
            print(f"    {w} -> {r}")


if __name__ == "__main__":
    run_benchmark()
