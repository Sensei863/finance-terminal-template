# Barclays Live Macro Scraper + Weekly Digest Generator

A two-step pipeline for personal use:
1. **`scraper.js`** — logs into Barclays Live with your session and downloads all linked articles as `.md` snapshots
2. **`digest.js`** — feeds those snapshots to Claude and produces your formatted weekly briefing

---

## Setup

### Prerequisites
- [Node.js](https://nodejs.org/) v18+
- An Anthropic API key (for the digest step): [console.anthropic.com](https://console.anthropic.com)
- A valid Barclays Live subscription

### Install

```bash
git clone <this-repo>  # or just copy the files
cd barclays-macro-scraper
npm install
npx playwright install chromium
```

---

## Step 1: Save the Macro Wrap as Markdown

Use the [MarkDownload](https://chrome.google.com/webstore/detail/markdownload-markdown-web/pcmpcfapbekmbjjkdalcgopdkipoggdi) Chrome extension to save the weekly Macro Wrap page as a `.md` file. Place it in this folder.

---

## Step 2: Run the Scraper

**First run (manual login):**
```bash
node scraper.js --input "Macro_Wrap.md"
```
A browser window will open. Log in to Barclays Live, then press ENTER in the terminal. Your session will be saved to `session.json` for future runs.

**Subsequent runs (headless, using saved session):**
```bash
node scraper.js --input "Macro_Wrap.md" --headless --cookies session.json
```

**Options:**
| Flag | Default | Description |
|------|---------|-------------|
| `--input` | `Macro_Wrap.md` | Path to your Macro Wrap markdown file |
| `--output` | `./snapshots` | Directory to save article snapshots |
| `--cookies` | _(none)_ | Path to saved session cookie file |
| `--headless` | false | Run browser without UI |
| `--delay` | `2000` | Milliseconds between requests (be polite) |

Articles are saved as numbered `.md` files in `./snapshots/`. A `_manifest.json` tracks what was fetched.

---

## Step 3: Generate Your Weekly Digest

```bash
export GEMINI_API_KEY=AIza...
node digest.js --snapshots ./snapshots
```

Output: `weekly_update_YYYY-MM-DD.md` in the current directory.

**Options:**
| Flag | Default | Description |
|------|---------|-------------|
| `--snapshots` | `./snapshots` | Directory containing article snapshots |
| `--output` | `weekly_update_<date>.md` | Output filename |

---

## One-liner (after first setup)

```bash
node scraper.js --input Macro_Wrap.md --headless --cookies session.json && \
export GEMINI_API_KEY=AIza... && \
node digest.js --snapshots ./snapshots
```

---

## Output Format

The digest is structured as:

1. **Weekly Narrative** — 3-5 paragraphs of prose covering dominant macro themes
2. **Regional Snapshot** — Bullet points for US, Euro Area, UK, China, Japan, EEMEA
3. **Trade Ideas & Positioning** — Directional views with rationale and key risks
4. **Risks to Watch** — Top 3 tail risks for the coming week

---

## Notes on Barclays ToS

This tool is designed for **personal use only** by a subscriber with a valid Barclays Live licence. It does not bypass authentication — it uses your legitimate session. It includes polite delays between requests. Do not redistribute downloaded content.

---

## Troubleshooting

- **Login page not loading**: Try without `--headless` so you can see what's happening
- **Articles showing login wall**: Your session has expired — delete `session.json` and re-run without `--cookies`
- **Rate limited**: Increase `--delay` to 5000 or higher
- **Gemini API errors**: Check your `GEMINI_API_KEY` is set correctly
