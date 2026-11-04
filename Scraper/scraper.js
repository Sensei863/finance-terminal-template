/**
 * Barclays Live Article Scraper
 * ==============================
 * Reads a Macro Wrap .md file, extracts all Barclays Live links,
 * logs in with your session, fetches each article, and saves MD snapshots.
 *
 * Usage:
 *   npm install
 *   node scraper.js --input "Macro_Wrap.md" [--headless] [--output ./snapshots]
 *
 * Auth: The script will open a browser for you to log in manually (default),
 *       OR you can supply a saved session cookie file (--cookies session.json).
 */

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const https = require("https");

// ── CLI args ──────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const getArg = (flag) => {
  const i = args.indexOf(flag);
  return i !== -1 ? args[i + 1] : null;
};

const INPUT_FILE   = getArg("--input")   || "Macro_Wrap.md";
const OUTPUT_DIR   = getArg("--output")  || "./snapshots";
const COOKIE_FILE  = getArg("--cookies") || null;
const HEADLESS     = args.includes("--headless");
const DELAY_MS     = parseInt(getArg("--delay") || "2000", 10); // polite delay between requests

// ── Helpers ───────────────────────────────────────────────────────────────────
function sanitizeFilename(str) {
  return str.replace(/[^a-z0-9_\-]/gi, "_").slice(0, 80);
}

function extractLinks(mdContent) {
  const linkRegex = /\[([^\]]+)\]\((https:\/\/(?:live\.barcap\.com|my\.barcapint\.com)[^)]+)\)/g;
  const links = [];
  let match;
  while ((match = linkRegex.exec(mdContent)) !== null) {
    links.push({ label: match[1].trim(), url: match[2].trim() });
  }
  // Deduplicate by URL
  const seen = new Set();
  return links.filter(({ url }) => {
    if (seen.has(url)) return false;
    seen.add(url);
    return true;
  });
}

function htmlToMarkdown(title, url, bodyText) {
  const date = new Date().toISOString().split("T")[0];
  return `---
title: "${title.replace(/"/g, "'")}"
source: ${url}
fetched: ${date}
---

# ${title}

${bodyText.trim()}
`;
}

async function extractArticleContent(page) {
  // Try multiple content selectors common to research portals
  const selectors = [
    "[class*='article-body']",
    "[class*='publication-body']",
    "[class*='research-content']",
    "main article",
    "main",
    "#content",
    "body",
  ];

  for (const sel of selectors) {
    try {
      const el = await page.$(sel);
      if (el) {
        const text = await el.innerText();
        if (text && text.length > 200) return text;
      }
    } catch (_) {}
  }
  return await page.innerText("body");
}

// ── Main ──────────────────────────────────────────────────────────────────────
(async () => {
  // 1. Read input file
  if (!fs.existsSync(INPUT_FILE)) {
    console.error(`❌  Input file not found: ${INPUT_FILE}`);
    process.exit(1);
  }
  const mdContent = fs.readFileSync(INPUT_FILE, "utf8");
  const links = extractLinks(mdContent);

  if (links.length === 0) {
    console.error("❌  No Barclays Live links found in the input file.");
    process.exit(1);
  }

  console.log(`\n📰  Found ${links.length} Barclays Live links to fetch.\n`);
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  // 2. Launch browser
  const browser = await chromium.launch({ headless: HEADLESS });
  const context = await browser.newContext({
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  });

  // 3. Auth: restore cookies OR manual login
  if (COOKIE_FILE && fs.existsSync(COOKIE_FILE)) {
    console.log(`🍪  Loading saved session from ${COOKIE_FILE}`);
    const cookies = JSON.parse(fs.readFileSync(COOKIE_FILE, "utf8"));
    await context.addCookies(cookies);
  } else {
    console.log("🔐  Opening browser for manual login...");
    console.log("    Please log in to Barclays Live, then press ENTER here.\n");

    const loginPage = await context.newPage();
    await loginPage.goto("https://live.barcap.com", { waitUntil: "domcontentloaded" });

    // Wait for user to press Enter
    await new Promise((resolve) => {
      process.stdin.once("data", resolve);
      process.stdout.write("    > Press ENTER once you are logged in: ");
    });

    await loginPage.close();

    // Save session for next time
    const cookies = await context.cookies();
    fs.writeFileSync("session.json", JSON.stringify(cookies, null, 2));
    console.log("\n✅  Session saved to session.json (use --cookies session.json next time)\n");
  }

  // 4. Fetch each article
  const results = [];
  const page = await context.newPage();

  for (let i = 0; i < links.length; i++) {
    const { label, url } = links[i];
    console.log(`[${i + 1}/${links.length}] Fetching: ${label}`);
    console.log(`            ${url}`);

    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForTimeout(1500); // let JS render

      const title = await page.title();
      const bodyText = await extractArticleContent(page);
      const currentUrl = page.url();

      const md = htmlToMarkdown(title || label, currentUrl, bodyText);
      const filename = `${String(i + 1).padStart(2, "0")}_${sanitizeFilename(label)}.md`;
      const outPath = path.join(OUTPUT_DIR, filename);

      fs.writeFileSync(outPath, md, "utf8");
      console.log(`   ✅  Saved → ${outPath}\n`);

      results.push({ label, url, filename, ok: true });
    } catch (err) {
      console.error(`   ⚠️   Failed: ${err.message}\n`);
      results.push({ label, url, filename: null, ok: false, error: err.message });
    }

    if (i < links.length - 1) {
      await page.waitForTimeout(DELAY_MS);
    }
  }

  await browser.close();

  // 5. Write manifest
  const manifest = {
    source_file: INPUT_FILE,
    fetched_at: new Date().toISOString(),
    total: links.length,
    success: results.filter((r) => r.ok).length,
    failed: results.filter((r) => !r.ok).length,
    articles: results,
  };
  fs.writeFileSync(path.join(OUTPUT_DIR, "_manifest.json"), JSON.stringify(manifest, null, 2));

  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log(`✅  Done. ${manifest.success}/${manifest.total} articles saved to ${OUTPUT_DIR}/`);
  if (manifest.failed > 0) {
    console.log(`⚠️   ${manifest.failed} failed (check _manifest.json for details)`);
  }
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
  console.log("👉  Next step: run the digest generator:");
  console.log(`    node digest.js --snapshots ${OUTPUT_DIR}\n`);
})();
