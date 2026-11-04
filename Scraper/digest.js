/**
 * Weekly Finance Digest Generator
 * =================================
 * Reads all MD snapshots from the scraper, sends them to Gemini API,
 * and produces a structured weekly update in your preferred format.
 *
 * Usage:
 *   node digest.js --snapshots ./snapshots [--output weekly_update.md]
 */

const fs = require("fs");
const path = require("path");
const https = require("https");

// ── CLI args ──────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const getArg = (flag) => { const i = args.indexOf(flag); return i !== -1 ? args[i + 1] : null; };

const SNAPSHOTS_DIR = getArg("--snapshots") || "./snapshots";
const OUTPUT_FILE   = getArg("--output") || `weekly_update_${new Date().toISOString().split("T")[0]}.md`;
const API_KEY       = process.env.GEMINI_API_KEY;

if (!API_KEY) {
  console.error("❌  Set GEMINI_API_KEY environment variable.");
  console.error("    $env:GEMINI_API_KEY=\"AIza...\"");
  process.exit(1);
}

// ── Load snapshots ─────────────────────────────────────────────────────────────
function loadSnapshots(dir) {
  if (!fs.existsSync(dir)) {
    console.error(`❌  Snapshots directory not found: ${dir}`);
    process.exit(1);
  }
  const files = fs.readdirSync(dir)
    .filter(f => f.endsWith(".md"))
    .sort();

  return files.map(f => ({
    filename: f,
    content: fs.readFileSync(path.join(dir, f), "utf8"),
  }));
}

// ── List available Gemini models (mirrors screener.py get_available_models) ───
function listModels() {
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: "generativelanguage.googleapis.com",
      path: `/v1beta/models?key=${API_KEY}`,
      method: "GET",
      headers: { "Content-Type": "application/json" },
    }, (res) => {
      let data = "";
      res.on("data", chunk => data += chunk);
      res.on("end", () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.error) return reject(new Error(parsed.error.message));
          // Filter to models that support generateContent, prefer flash
          const models = (parsed.models || [])
            .filter(m => (m.supportedGenerationMethods || []).includes("generateContent"))
            .map(m => m.name.replace("models/", ""));
          // Sort: flash first, then anything else
          models.sort((a, b) => {
            const aFlash = a.includes("flash") ? 0 : 1;
            const bFlash = b.includes("flash") ? 0 : 1;
            return aFlash - bFlash;
          });
          resolve(models);
        } catch (e) { reject(e); }
      });
    });
    req.on("error", reject);
    req.end();
  });
}

// ── Gemini API call ────────────────────────────────────────────────────────────
function callGemini(modelName, systemPrompt, userMessage) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      system_instruction: { parts: [{ text: systemPrompt }] },
      contents: [{ role: "user", parts: [{ text: userMessage }] }],
      generationConfig: { maxOutputTokens: 4096, temperature: 0.3 },
    });

    const apiPath = `/v1beta/models/${modelName}:generateContent?key=${API_KEY}`;

    const req = https.request({
      hostname: "generativelanguage.googleapis.com",
      path: apiPath,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
      },
    }, (res) => {
      let data = "";
      res.on("data", chunk => data += chunk);
      res.on("end", () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.error) reject(new Error(parsed.error.message));
          else resolve(parsed.candidates[0].content.parts[0].text);
        } catch (e) { reject(e); }
      });
    });

    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

// ── System prompt ──────────────────────────────────────────────────────────────
const SYSTEM_PROMPT = `You are a senior macro research analyst preparing a personal weekly market intelligence briefing.

Your output should be a polished Markdown document with three sections:

---

## 1. Weekly Narrative — Key Macro Calls
Write 3-5 paragraphs of flowing prose covering the dominant macro themes of the week. Lead with the biggest market-moving narrative (geopolitical, central bank, data surprises). Integrate cross-asset implications naturally. Use precise language — this is for a sophisticated reader.

## 2. Regional Snapshot
For each region below, write 3-5 bullet points covering: key data/events, central bank stance, and market implications. Regions: United States | Euro Area | United Kingdom | China | Japan | EEMEA/EM

## 3. Trade Ideas & Positioning
List the key directional views and trade ideas mentioned across the research. Format each as:
- **[Asset/Instrument]**: Direction (Long/Short/Underweight/Overweight) — Rationale (1 sentence) — Key risk

End with a brief "Risks to Watch" box listing the top 3 tail risks for the coming week.

---

Tone: Authoritative, concise. No fluff. Assume the reader knows what a bund is.
Date context: use the fetched dates in the source documents.`;

// ── Main ──────────────────────────────────────────────────────────────────────
(async () => {
  const snapshots = loadSnapshots(SNAPSHOTS_DIR);
  console.log(`\n📚  Loaded ${snapshots.length} article snapshots from ${SNAPSHOTS_DIR}/`);

  if (snapshots.length === 0) {
    console.error("❌  No .md files found. Run scraper.js first.");
    process.exit(1);
  }

  // Auto-discover best available model (same logic as screener.py)
  console.log("🔍  Fetching available Gemini models...");
  let modelName;
  try {
    const models = await listModels();
    if (!models.length) throw new Error("No models returned");
    modelName = models[0];
    console.log(`✅  Using model: ${modelName}`);
    console.log(`    (Available: ${models.slice(0, 5).join(", ")}${models.length > 5 ? "..." : ""})`);
  } catch (e) {
    console.error("❌  Could not list models:", e.message);
    process.exit(1);
  }

  const MAX_PER_ARTICLE = 3000;
  const knowledgeBank = snapshots.map(({ filename, content }, i) => {
    const trimmed = content.length > MAX_PER_ARTICLE
      ? content.slice(0, MAX_PER_ARTICLE) + "\n[... truncated ...]"
      : content;
    return `### Article ${i + 1}: ${filename}\n\n${trimmed}`;
  }).join("\n\n---\n\n");

  const userMessage = `Here are this week's Barclays research article snapshots. Please produce the weekly finance briefing as instructed.\n\n${knowledgeBank}`;

  console.log("\n🤖  Sending to Gemini for digest generation...\n");

  try {
    const digest = await callGemini(modelName, SYSTEM_PROMPT, userMessage);

    const weekOf = new Date().toLocaleDateString("en-GB", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
    const finalOutput = `# Weekly Macro Intelligence Briefing
**Week of ${weekOf}**
_Source: Barclays Live Research — Personal digest_

---

${digest}

---
_Generated from ${snapshots.length} Barclays research articles using ${modelName}. For personal use only._
`;

    fs.writeFileSync(OUTPUT_FILE, finalOutput, "utf8");
    console.log(`✅  Weekly digest saved → ${OUTPUT_FILE}`);
    console.log(`\n📄  Preview:\n`);
    console.log(finalOutput.slice(0, 800) + "\n[...]\n");
  } catch (err) {
    console.error("❌  Gemini API error:", err.message);
    process.exit(1);
  }
})();
