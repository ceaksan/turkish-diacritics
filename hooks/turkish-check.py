#!/usr/bin/env python3
"""
Turkish Diacritics Validator - Claude Code Plugin

Validates Turkish diacritics (ç, ğ, ı, ö, ş, ü) in content files.
Runs as a PostToolUse hook after Edit/Write operations.

Architecture (batch hunspell, 2 calls total):
  Layer 0: Word dedup + normalization
  Layer 1: Hunspell suggestion-based (misspelled -> diacritics suggestion)
  Layer 2: Brute-force variant with batch validation (misspelled -> generate combos)
  Layer 3: Ambiguity lookup table (valid ASCII -> known diacritics form)

Exit 0 = pass, Exit 2 = errors found (feedback to Claude via stderr).

Configuration (environment variables):
  TURKISH_CHECK_FILES  - Comma-separated basenames to check (default: tr.mdx,tr.md)
  TURKISH_CHECK_LANG   - Hunspell dictionary language (default: tr_TR)
"""

import json
import os
import re
import subprocess
import sys
from itertools import product

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DICTS_DIR = os.path.join(SCRIPT_DIR, "dicts")

TECH_DIC = os.path.join(DICTS_DIR, "tech.dic")
WHITELIST_DIC = os.path.join(DICTS_DIR, "whitelist.dic")
AMBIGUOUS_LOOKUP = os.path.join(DICTS_DIR, "ambiguous-lookup.tsv")
AMBIGUOUS_SKIP = os.path.join(DICTS_DIR, "ambiguous-skip.dic")

CHECK_FILES = set(
    f.strip()
    for f in os.environ.get("TURKISH_CHECK_FILES", "tr.mdx,tr.md").split(",")
    if f.strip()
)
HUNSPELL_LANG = os.environ.get("TURKISH_CHECK_LANG", "tr_TR")

DIACRITICS_MAP = {
    "ç": "c",
    "Ç": "C",
    "ğ": "g",
    "Ğ": "G",
    "ı": "i",
    "İ": "I",
    "ö": "o",
    "Ö": "O",
    "ş": "s",
    "Ş": "S",
    "ü": "u",
    "Ü": "U",
}

SWAP_MAP = {
    "c": ["ç"],
    "g": ["ğ"],
    "i": ["ı"],
    "o": ["ö"],
    "s": ["ş"],
    "u": ["ü"],
    "C": ["Ç"],
    "G": ["Ğ"],
    "I": ["İ"],
    "O": ["Ö"],
    "S": ["Ş"],
    "U": ["Ü"],
}

RE_IDENTIFIER = re.compile(
    r"[a-zA-Z]+[A-Z][a-zA-Z]*"
    r"|[a-zA-Z]+_[a-zA-Z_]+"
    r"|[A-Z]{2,}"
    r"|[a-zA-Z]+-[a-zA-Z-]+"
)


def ascii_fold(s: str) -> str:
    return "".join(DIACRITICS_MAP.get(c, c) for c in s)


def count_diacritics(s: str) -> int:
    return sum(1 for c in s if c in DIACRITICS_MAP)


def is_identifier(word: str) -> bool:
    return bool(RE_IDENTIFIER.fullmatch(word))


def load_word_set(path: str) -> set[str]:
    words = set()
    if not os.path.isfile(path):
        return words
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if w and not w.isdigit():
                words.add(w.lower())
    return words


def load_ambiguous_lookup(path: str) -> dict[str, str]:
    lookup = {}
    if not os.path.isfile(path):
        return lookup
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            ascii_form, diacritics_forms = line.split("\t", 1)
            best = diacritics_forms.split(",")[0].strip()
            lookup[ascii_form.lower()] = best
    return lookup


# ---------------------------------------------------------------------------
# Text stripping (Markdown / MDX)
# ---------------------------------------------------------------------------


def strip_non_prose(text: str) -> str:
    def _blank(m: re.Match) -> str:
        return "\n" * m.group(0).count("\n")

    text = re.sub(r"^---\n.*?\n---\n", _blank, text, count=1, flags=re.DOTALL)
    text = re.sub(r"```[\s\S]*?```", _blank, text)
    text = re.sub(r"~~~[\s\S]*?~~~", _blank, text)
    text = re.sub(r"`[^`]+`", " ", text)
    text = re.sub(r"^(?:import|export)\s+.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\{[^}]*\}", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\^[^\]]+\]", " ", text)
    text = re.sub(r"\[/?(?:bdi|var)\]", " ", text)
    text = re.sub(r"<!--.*?-->", _blank, text, flags=re.DOTALL)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}|_{1,3}", "", text)
    return text


# ---------------------------------------------------------------------------
# Hunspell batch interface
# ---------------------------------------------------------------------------


def _hunspell_cmd() -> list[str]:
    cmd = ["hunspell", "-d", HUNSPELL_LANG, "-a"]
    if os.path.isfile(TECH_DIC):
        cmd.extend(["-p", TECH_DIC])
    return cmd


def hunspell_check_text(text: str) -> dict[str, list[str]]:
    """Run hunspell -a on text. Returns {misspelled_word: [suggestions]}."""
    try:
        proc = subprocess.run(
            _hunspell_cmd(), input=text, capture_output=True, text=True, timeout=15
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}

    results = {}
    for line in proc.stdout.splitlines():
        if line.startswith("&"):
            parts = line.split(":", 1)
            word = parts[0].split()[1]
            suggestions = (
                [s.strip() for s in parts[1].split(",")] if len(parts) > 1 else []
            )
            results[word] = suggestions
        elif line.startswith("#"):
            word = line.split()[1] if len(line.split()) > 1 else ""
            if word:
                results[word] = []
    return results


def hunspell_batch_valid(words: list[str]) -> set[str]:
    """Check which words are valid. Returns set of VALID words."""
    if not words:
        return set()
    cmd = ["hunspell", "-d", HUNSPELL_LANG, "-l"]
    if os.path.isfile(TECH_DIC):
        cmd.extend(["-p", TECH_DIC])
    try:
        proc = subprocess.run(
            cmd, input="\n".join(words), capture_output=True, text=True, timeout=15
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()
    misspelled = set(proc.stdout.strip().split("\n")) if proc.stdout.strip() else set()
    return set(words) - misspelled


# ---------------------------------------------------------------------------
# Detection layers
# ---------------------------------------------------------------------------


def layer1_suggestion(word: str, suggestions: list[str]) -> str | None:
    """Layer 1: Diacritics-only correction from hunspell suggestions."""
    folded = ascii_fold(word).lower()
    word_dc = count_diacritics(word)
    for s in suggestions:
        if ascii_fold(s).lower() == folded and s.lower() != word.lower():
            if count_diacritics(s) > word_dc:
                return s
    return None


def generate_variants(word: str) -> list[str]:
    """Generate diacritics variants for a word (max 64)."""
    if not any(c in SWAP_MAP for c in word):
        return []

    positions = [
        (i, [c] + SWAP_MAP[c]) if c in SWAP_MAP else (i, [c])
        for i, c in enumerate(word)
    ]
    swappable = sum(1 for _, opts in positions if len(opts) > 1)
    if swappable > 6:
        return []

    word_dc = count_diacritics(word)
    variants = []
    count = 0
    for combo in product(*(opts for _, opts in positions)):
        candidate = "".join(combo)
        if candidate == word:
            continue
        count += 1
        if count > 64:
            break
        if count_diacritics(candidate) > word_dc:
            variants.append(candidate)
    return variants


def layer3_ambiguity(
    word: str,
    amb_lookup: dict[str, str],
    amb_skip: set[str],
    whitelist: set[str],
) -> str | None:
    wl = word.lower()
    if wl in whitelist or any(
        wl.startswith(w) and len(wl) - len(w) <= 5 for w in whitelist if len(w) >= 5
    ):
        return None
    if wl in amb_skip:
        return None
    if wl in amb_lookup:
        return amb_lookup[wl]
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool_name not in ("Edit", "Write"):
        sys.exit(0)

    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    basename = os.path.basename(file_path)
    if basename not in CHECK_FILES:
        sys.exit(0)

    if not os.path.isfile(file_path):
        sys.exit(0)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    prose = strip_non_prose(content)

    # Load dictionaries
    whitelist = load_word_set(WHITELIST_DIC)
    amb_lookup = load_ambiguous_lookup(AMBIGUOUS_LOOKUP)
    amb_skip = load_word_set(AMBIGUOUS_SKIP)

    # -------------------------------------------------------------------
    # Layer 0: Extract unique words, dedup
    # -------------------------------------------------------------------
    word_locations: dict[str, list[int]] = {}
    for line_num, line in enumerate(prose.splitlines(), 1):
        for word in re.findall(r"\b[a-zA-ZçğıöşüÇĞİÖŞÜ]+\b", line):
            if len(word) < 2:
                continue
            word_locations.setdefault(word, []).append(line_num)

    unique_words = set(word_locations.keys())

    # -------------------------------------------------------------------
    # hunspell call #1: Check all unique words (one per line)
    # -------------------------------------------------------------------
    words_text = "\n".join(sorted(unique_words))
    misspellings = hunspell_check_text(words_text)

    errors: list[dict] = []
    seen_lower: set[str] = set()

    # -------------------------------------------------------------------
    # Pass 1: Layer 1 - suggestion-based + Layer 2 candidate collection
    # -------------------------------------------------------------------
    layer2_candidates: dict[str, list[str]] = {}

    for word, suggestions in misspellings.items():
        wl = word.lower()
        if wl in seen_lower or len(word) < 3:
            continue
        if is_identifier(word) or wl in whitelist:
            continue

        correction = layer1_suggestion(word, suggestions)
        if correction:
            lines = word_locations.get(word, [])
            errors.append(
                {
                    "word": word,
                    "correction": correction,
                    "lines": lines,
                    "confidence": "high",
                    "layer": 1,
                }
            )
            seen_lower.add(wl)
        else:
            variants = generate_variants(word)
            if variants:
                layer2_candidates[word] = variants

    # -------------------------------------------------------------------
    # hunspell call #2: Batch validate ALL Layer 2 variants at once
    # -------------------------------------------------------------------
    if layer2_candidates:
        all_variants = []
        variant_to_word: dict[str, str] = {}
        for word, variants in layer2_candidates.items():
            for v in variants:
                all_variants.append(v)
                variant_to_word[v] = word

        valid_variants = hunspell_batch_valid(all_variants)

        word_valid: dict[str, list[str]] = {}
        for v in valid_variants:
            src = variant_to_word[v]
            word_valid.setdefault(src, []).append(v)

        for word, valid_list in word_valid.items():
            wl = word.lower()
            if wl in seen_lower:
                continue
            best = min(valid_list, key=lambda v: count_diacritics(v))
            lines = word_locations.get(word, [])
            errors.append(
                {
                    "word": word,
                    "correction": best,
                    "lines": lines,
                    "confidence": "high",
                    "layer": 2,
                }
            )
            seen_lower.add(wl)

    # -------------------------------------------------------------------
    # Pass 2: Layer 3 - ambiguity lookup (no hunspell needed)
    # -------------------------------------------------------------------
    LAYER3_BRAKE = 15
    layer3_count = 0

    for word in sorted(unique_words):
        wl = word.lower()
        if wl in seen_lower:
            continue
        if is_identifier(word) or len(word) < 3:
            continue
        if not any(c in SWAP_MAP for c in word):
            continue
        if word in misspellings:
            continue

        correction = layer3_ambiguity(word, amb_lookup, amb_skip, whitelist)
        if correction and correction.lower() != wl:
            lines = word_locations.get(word, [])
            errors.append(
                {
                    "word": word,
                    "correction": correction,
                    "lines": lines,
                    "confidence": "medium",
                    "layer": 3,
                }
            )
            seen_lower.add(wl)
            layer3_count += 1
            if layer3_count >= LAYER3_BRAKE:
                break

    if not errors:
        sys.exit(0)

    # -------------------------------------------------------------------
    # Output
    # -------------------------------------------------------------------
    high = [e for e in errors if e["confidence"] == "high"]
    medium = [e for e in errors if e["confidence"] == "medium"]

    lines_out = [
        f"Turkish diacritics errors in {file_path} ({len(errors)} found):",
        "",
    ]

    if high:
        lines_out.append(f"[HIGH confidence - {len(high)} errors]")
        for e in high:
            loc = f" (line {e['lines'][0]})" if e["lines"] else ""
            lines_out.append(f"  '{e['word']}' -> '{e['correction']}'{loc}")
        lines_out.append("")

    if medium:
        lines_out.append(f"[MEDIUM confidence - {len(medium)} errors]")
        for e in medium:
            loc = f" (line {e['lines'][0]})" if e["lines"] else ""
            lines_out.append(f"  '{e['word']}' -> '{e['correction']}'{loc}")
        lines_out.append("")

    lines_out.append("Fix these Turkish character errors using Edit tool.")

    sys.stderr.write("\n".join(lines_out) + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
