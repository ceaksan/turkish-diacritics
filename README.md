# turkish-diacritics

Claude Code plugin and global hook that validates Turkish diacritics in content files. Catches missing **c, g, i, o, s, u** characters using hunspell-based multi-layer detection with zero token cost.

## Problem

LLMs (including Claude) drop Turkish diacritics when generating long-form content:

- `c` becomes `c`, `g` becomes `g`, `i` becomes `i`, `o` becomes `o`, `s` becomes `s`, `u` becomes `u`
- Prompt-level warnings ("use proper Turkish characters") are insufficient
- Manual proofreading is slow, expensive, and error-prone
- Errors are often caught only after publication

This plugin adds a deterministic quality gate that runs after every file edit, providing instant feedback so Claude can self-correct.

## Who needs this

- **Turkish content creators using AI writing tools.** If you generate blog posts, documentation, or marketing copy with Claude, GPT, or Gemini in Turkish, diacritics errors are inevitable. This catches them before publication.
- **Developers building Turkish-language applications.** Any pipeline that processes LLM-generated Turkish text needs a validation layer. This is that layer.
- **Claude Code users writing in Turkish.** Install as a plugin, and every file edit is validated automatically. Zero manual intervention.

Validated against 134 real blog posts with 97% false positive reduction after dictionary tuning.

## How It Works

The plugin runs as a `PostToolUse` hook after every `Edit` or `Write` operation. If the edited file is a markdown file (`.md`, `.mdx` in global mode; `tr.mdx`, `tr.md` in plugin mode), it validates diacritics using a 4-layer detection system:

| Layer   | Method                                | Confidence | What It Catches            |
| ------- | ------------------------------------- | ---------- | -------------------------- |
| Layer 0 | Word dedup                            | -          | Reduces hunspell calls     |
| Layer 1 | hunspell suggestion matching          | HIGH       | Most diacritics errors     |
| Layer 2 | Brute-force variant generation        | HIGH       | Multi-character changes    |
| Layer 3 | Ambiguity lookup table (7,466 entries) | MEDIUM     | Valid ASCII but wrong form |

**Performance**: 2 hunspell calls per file, ~5s average, zero timeouts on 134 real posts.

When errors are found, the plugin reports them via stderr (exit code 2), and Claude automatically corrects them.

## Prerequisites

### hunspell + Turkish Dictionary

**macOS:**

```bash
brew install hunspell
```

**Linux (Debian/Ubuntu):**

```bash
sudo apt-get install hunspell hunspell-tr
```

**Verify installation:**

```bash
echo "ozellik" | hunspell -d tr_TR -a
# Should show suggestions including "ozellik"
```

If `tr_TR` dictionary is not found, download from [tdd-ai/hunspell-tr](https://github.com/tdd-ai/hunspell-tr) and place `tr_TR.dic` + `tr_TR.aff` in your hunspell dictionary path (`~/Library/Spelling/` on macOS, `/usr/share/hunspell/` on Linux).

## Installation

### As Claude Code Plugin (project-level)

Add the marketplace and install:

```
/plugin marketplace add ceaksan/turkish-diacritics
/plugin install turkish-diacritics
```

Plugin mode checks only `tr.mdx` and `tr.md` files by default.

### As Global Hook (all projects)

Copy the hook and dictionaries to your global Claude Code directory:

```bash
mkdir -p ~/.claude/hooks/dicts
cp hooks/turkish-check.py ~/.claude/hooks/turkish-check.py
cp hooks/dicts/* ~/.claude/hooks/dicts/
```

Add the hook to `~/.claude/settings.json` under the PostToolUse matcher for Edit|Write:

```json
{
  "type": "command",
  "command": "TURKISH_CHECK_GLOBAL=1 python3 ~/.claude/hooks/turkish-check.py",
  "statusMessage": "Checking Turkish characters..."
}
```

Global mode checks all `.md` and `.mdx` files across every project.

## Modes

| Mode             | File Filter            | Scope          | Install Method                    |
| ---------------- | ---------------------- | -------------- | --------------------------------- |
| Plugin (default) | `tr.mdx`, `tr.md` only | Single project | `/plugin install`                 |
| Global hook      | Any `.md` or `.mdx`    | All projects   | Manual copy to `~/.claude/hooks/` |

In global mode, non-Turkish files pass through cleanly since hunspell only flags words that should have Turkish diacritics.

## What Gets Checked

The plugin extracts prose text by stripping:

- YAML frontmatter
- Code blocks (fenced and inline)
- JSX/HTML tags and expressions
- Import/export statements
- URLs and markdown links/images
- Footnote references
- HTML comments
- Markdown formatting (headings, bold, italic)

What's **not** checked:

- Code identifiers (camelCase, snake_case, UPPER_CASE, kebab-case)
- Technical terms (API, React, frontend, cache, etc.)
- English words used in tech context (status, editor, suite, etc.)
- Known dual-use words (words valid in both ASCII and diacritics form)

## Dictionaries

The plugin ships with 4 curated dictionary files:

| File                   | Entries | Purpose                                                             |
| ---------------------- | ------- | ------------------------------------------------------------------- |
| `tech.dic`             | ~360    | hunspell personal dictionary: brands, acronyms, Turkish inflections |
| `whitelist.dic`        | ~560    | Words to skip in all detection layers                               |
| `ambiguous-lookup.tsv` | 7,466   | ASCII-to-diacritics mapping for Layer 3                             |
| `ambiguous-skip.dic`   | ~240    | Context-dependent words to skip in Layer 3                          |

### Adding Custom Words

**To prevent a false positive on an English/tech word:**
Add it to `hooks/dicts/whitelist.dic` (one word per line, case-insensitive).

**To teach hunspell a new word:**
Add it to `hooks/dicts/tech.dic` (one word per line).

**To skip a valid Turkish ASCII word:**
Add it to `hooks/dicts/ambiguous-skip.dic` (one word per line, case-insensitive).

## Example Output

```
Turkish diacritics errors in src/content/posts/2026/01/01.my-post/tr.mdx (5 found):

[HIGH confidence - 3 errors]
  'ozellik' -> 'özellik' (line 12)
  'gelistirme' -> 'geliştirme' (line 24)
  'Turkce' -> 'Türkçe' (line 8)

[MEDIUM confidence - 2 errors]
  'urun' -> 'ürün' (line 30)
  'sureci' -> 'süreci' (line 45)

Fix these Turkish character errors using Edit tool.
```

## Benchmarks

The rule-based system was benchmarked against a fine-tuned ByT5-small (300M params) model on the same test set:

| Metric | Rule-based | ByT5 |
| --- | --- | --- |
| Word accuracy (200 sample) | 100% | 96.5% |
| False positives (50 sample) | 0 | 6 |
| Speed | 0ms/word | 836ms/word |
| Context disambiguation (7 pairs) | N/A | 2/7 |

The rule-based system outperforms ML on word-level tasks. ML models may add value for sentence-level context disambiguation with larger training datasets and better architectures (token classification vs seq2seq). See `notebooks/` for experiment details.

## Data Sources

The ambiguity lookup table was built from multiple sources:

- **134 Turkish blog posts** from production content. Words with diacritics extracted, ASCII-folded, and validated with hunspell. Primary source for the 7,466-entry lookup table.
- **[tdd-ai/hunspell-tr](https://github.com/tdd-ai/hunspell-tr)** - Turkish hunspell dictionary (75,910 words). Used for base spell checking and suggestion generation.
- **[CanNuhlar/Turkce-Kelime-Listesi](https://github.com/CanNuhlar/Turkce-Kelime-Listesi)** - 76K Turkish word list. Used to extract ambiguous ASCII/diacritics word pairs.
- **[erogluegemen/TDK-Dataset](https://github.com/erogluegemen/TDK-Dataset)** - TDK (Turkish Language Association) dataset with 92K words including `madde` and `madde_duz` columns. Used for cross-validation and ambiguous-skip curation.

## Architecture

```
Claude Write/Edit tr.mdx
        |
        v
PostToolUse Hook (stdin JSON)
        |
        v
turkish-check.py
  1. File filter (.md/.mdx in global mode, tr.mdx/tr.md in plugin mode)
  2. Strip non-prose content
  3. Extract unique words
  4. hunspell -a: suggestions for misspelled words
  5. Layer 1: Diacritics-only suggestion matching
  6. Layer 2: Brute-force variant generation + batch validation
  7. hunspell -l: batch validate Layer 2 variants
  8. Layer 3: Ambiguity lookup (no hunspell)
  9. Structured output with confidence levels
  10. stderr + exit 2 -> Claude feedback loop
```

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/prepare_training_data.py` | Generate training pairs from Turkish content for ML experiments |
| `scripts/compare_benchmark.py` | Rule-based vs ML model comparison benchmark |
| `scripts/sentence_benchmark.py` | Sentence-level context disambiguation benchmark |

## Limitations

1. **No context disambiguation**: The rule-based system cannot distinguish between "bas" (press) and "bas" (head) based on sentence context. Context-dependent words are skipped to avoid false positives.
2. **hunspell suggestion quality**: Some corrections are partial (e.g., `karsilasilan` gets partially corrected). This is a hunspell limitation.
3. **Morphological gaps**: Not all inflected forms are in the lookup table. Simple suffix concatenation doesn't cover Turkish vowel harmony and stem changes.
4. **Prefix whitelist**: Short whitelist words (3-4 chars) only do exact matching to avoid false negatives on unrelated Turkish words.
5. **Source text typos**: The hook correctly flags source typos but the suggested correction may be wrong (e.g., `isiyorum` flagged but correction should be `istiyorum`, not `isiyorum`).

## License

MIT
