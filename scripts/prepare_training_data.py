"""
Prepare training data for ByT5 diacritics model.

Usage:
    python prepare_training_data.py --content-dir /path/to/turkish/content --output training_data.tsv

Reads .md/.mdx files, extracts sentences, strips diacritics to create
(ASCII, correct) pairs for fine-tuning.
"""

import argparse
import re
import unicodedata
from pathlib import Path

# Turkish diacritics mapping
DIACRITICS_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiousCGIOUS")


def strip_diacritics(text: str) -> str:
    return text.translate(DIACRITICS_MAP)


def has_turkish_diacritics(text: str) -> bool:
    return any(c in text for c in "çğıöşüÇĞİÖŞÜ")


def extract_sentences(text: str) -> list[str]:
    # Remove frontmatter
    text = re.sub(r"^---.*?---", "", text, flags=re.DOTALL)
    # Remove code blocks
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # Remove inline code
    text = re.sub(r"`[^`]+`", "", text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove markdown links, keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove markdown headers
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Remove images
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)

    # Split into sentences
    sentences = re.split(r"[.!?]\s+|\n\n+|\n", text)

    result = []
    for s in sentences:
        s = s.strip()
        # Filter: must have Turkish diacritics, reasonable length
        if len(s) < 5 or len(s) > 200:
            continue
        if not has_turkish_diacritics(s):
            continue
        # Skip if mostly non-text (URLs, paths)
        if s.count("/") > 2 or s.count("http") > 0:
            continue
        result.append(s)

    return result


def load_negative_examples(dict_dir: Path) -> list[tuple[str, str]]:
    """Load tech.dic and whitelist.dic as negative examples (word stays same)."""
    negatives = []
    for filename in ["tech.dic", "whitelist.dic"]:
        filepath = dict_dir / filename
        if filepath.exists():
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    word = line.strip()
                    if word and not word.startswith("#"):
                        negatives.append((word, word))
    return negatives


def main():
    parser = argparse.ArgumentParser(
        description="Prepare ByT5 diacritics training data"
    )
    parser.add_argument(
        "--content-dir",
        type=str,
        required=True,
        help="Directory with Turkish .md/.mdx files",
    )
    parser.add_argument(
        "--dict-dir",
        type=str,
        default="hooks/dicts",
        help="Directory with tech.dic, whitelist.dic",
    )
    parser.add_argument(
        "--output", type=str, default="training_data.tsv", help="Output TSV file"
    )
    parser.add_argument(
        "--include-words",
        action="store_true",
        help="Also include word-level pairs from ambiguous-lookup.tsv",
    )
    args = parser.parse_args()

    pairs = []
    content_dir = Path(args.content_dir)
    dict_dir = Path(args.dict_dir)

    # 1. Sentence-level pairs from content
    sentence_count = 0
    for ext in ["tr.md", "tr.mdx"]:
        for filepath in content_dir.rglob(ext):
            text = filepath.read_text(encoding="utf-8")
            sentences = extract_sentences(text)
            for sentence in sentences:
                ascii_version = strip_diacritics(sentence)
                if (
                    ascii_version != sentence
                ):  # Only if diacritics were actually stripped
                    pairs.append((ascii_version, sentence))
                    sentence_count += 1

    print(f"Sentences from content: {sentence_count}")

    # 2. Word-level pairs from ambiguous-lookup.tsv
    if args.include_words:
        lookup_path = dict_dir / "ambiguous-lookup.tsv"
        if lookup_path.exists():
            word_count = 0
            with open(lookup_path, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) == 2:
                        ascii_form = parts[0]
                        for correct in parts[1].split(","):
                            pairs.append((ascii_form.strip(), correct.strip()))
                            word_count += 1
            print(f"Word pairs from lookup: {word_count}")

    # 3. Negative examples (words that should NOT change)
    negatives = load_negative_examples(dict_dir)
    pairs.extend(negatives)
    print(f"Negative examples: {len(negatives)}")

    # Deduplicate
    pairs = list(set(pairs))
    print(f"Total unique pairs: {len(pairs)}")

    # Write output
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        for src, tgt in sorted(pairs):
            f.write(f"{src}\t{tgt}\n")

    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
