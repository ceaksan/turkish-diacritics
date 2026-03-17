# turkish-diacritics

Claude Code plugin and global hook that automatically validates Turkish diacritics in content files. Catches missing **ç, ğ, ı, ö, ş, ü** characters using hunspell-based multi-layer detection with zero token cost.

## Problem

LLMs (including Claude) drop Turkish diacritics when generating long-form content:

- `ç` becomes `c`, `ğ` becomes `g`, `ı` becomes `i`, `ö` becomes `o`, `ş` becomes `s`, `ü` becomes `u`
- Prompt-level warnings ("use proper Turkish characters") are insufficient
- Manual proofreading is slow, expensive, and error-prone
- Errors are often caught only after publication

This plugin adds a deterministic quality gate that runs after every file edit, providing instant feedback so Claude can self-correct.

## How It Works

The plugin runs as a `PostToolUse` hook after every `Edit` or `Write` operation. If the edited file is a markdown file (`.md`, `.mdx` in global mode; `tr.mdx`, `tr.md` in plugin mode), it validates diacritics using a 4-layer detection system:

| Layer   | Method                                | Confidence | What It Catches            |
| ------- | ------------------------------------- | ---------- | -------------------------- |
| Layer 0 | Word dedup                            | -          | Reduces hunspell calls     |
| Layer 1 | hunspell suggestion matching          | HIGH       | Most diacritics errors     |
| Layer 2 | Brute-force variant generation        | HIGH       | Multi-character changes    |
| Layer 3 | Ambiguity lookup table (2944 entries) | MEDIUM     | Valid ASCII but wrong form |

**Performance**: 2 hunspell calls per file, ~5s average, zero timeouts on 200+ real posts.

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
# Should show suggestions including "özellik"
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
| `whitelist.dic`        | ~530    | Words to skip in all detection layers                               |
| `ambiguous-lookup.tsv` | 2944    | ASCII-to-diacritics mapping for Layer 3                             |
| `ambiguous-skip.dic`   | ~160    | Genuinely dual-use words to skip in Layer 3                         |

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

## Data Sources

The ambiguity lookup table was built from multiple sources:

- **[tdd-ai/hunspell-tr](https://github.com/tdd-ai/hunspell-tr)** - Turkish hunspell dictionary (75,910 words). Used for base spell checking and suggestion generation.
- **[CanNuhlar/Turkce-Kelime-Listesi](https://github.com/CanNuhlar/Turkce-Kelime-Listesi)** - 76K Turkish word list. Used to extract ambiguous ASCII/diacritics word pairs.
- **[erogluegemen/TDK-Dataset](https://github.com/erogluegemen/TDK-Dataset)** - TDK (Turkish Language Association) dataset with 92K words including `madde` and `madde_duz` columns. Used for cross-validation and ambiguous-skip curation.
- **[merfarukyce/turkish-words](https://www.kaggle.com/datasets/merfarukyce/turkish-words)** (Kaggle) - 18K Turkish words with root/suffix analysis. Evaluated: 94% of entries are already caught by hunspell (Layers 1-2), remaining 5% overlap mostly with existing lookup. Marginal contribution (~293 new entries) did not justify merge.
- **[google-research/turkish-morphology](https://github.com/AcademicDpt/turkish-morphology)** - 47K lexicon with morphological analyzer. Identified as potential future improvement for inflection gap coverage.

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

## Limitations

1. **hunspell suggestion quality**: Some corrections are partial (e.g., `karsilasilan` gets partially corrected). This is a hunspell limitation.
2. **Morphological gaps**: Not all inflected forms are in the lookup table. Simple suffix concatenation doesn't cover Turkish vowel harmony and stem changes.
3. **Prefix whitelist**: Short whitelist words (3-4 chars) only do exact matching to avoid false negatives on unrelated Turkish words.
4. **Source text typos**: The hook correctly flags source typos but the suggested correction may be wrong (e.g., `isiyorum` flagged but correction should be `istiyorum`, not `işiyorum`).

## License

MIT
