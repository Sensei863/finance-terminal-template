from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.platypus.flowables import Flowable
from reportlab.lib.colors import HexColor
import datetime

# ── Colour palette (matches Faraglioni newsletter) ──────────────────────────
NAVY    = HexColor("#1a3a5c")
GOLD    = HexColor("#c9a84c")
SLATE   = HexColor("#64748b")
WHITE   = HexColor("#ffffff")
LIGHT   = HexColor("#f0f4f8")
RED     = HexColor("#8b2635")
GREEN   = HexColor("#2e7d5e")
BORDER  = HexColor("#dde3ea")

PAGE_W, PAGE_H = A4
MARGIN = 2 * cm

# ── Custom Flowables ─────────────────────────────────────────────────────────

class GoldRule(HRFlowable):
    def __init__(self, width="100%", thickness=1.5):
        super().__init__(width=width, thickness=thickness, color=GOLD,
                         spaceAfter=6, spaceBefore=6)

class NavyRule(HRFlowable):
    def __init__(self, width="100%", thickness=0.5):
        super().__init__(width=width, thickness=thickness, color=BORDER,
                         spaceAfter=4, spaceBefore=4)

class SectionLabel(Flowable):
    """Gold numbered section badge."""
    def __init__(self, number, title, width=None):
        super().__init__()
        self.number = number
        self.title = title
        self._width = width or (PAGE_W - 2 * MARGIN)
        self.height = 28

    def draw(self):
        c = self.canv
        # Badge circle
        c.setFillColor(GOLD)
        c.circle(10, 10, 10, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(10, 7, str(self.number))
        # Title
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(26, 7, self.title.upper())

    def wrap(self, availWidth, availHeight):
        return self._width, self.height


class CoverHeader(Flowable):
    def __init__(self, width):
        super().__init__()
        self._width = width
        self.height = 120

    def draw(self):
        c = self.canv
        # Navy banner
        c.setFillColor(NAVY)
        c.rect(0, 0, self._width, self.height, fill=1, stroke=0)
        # Gold accent line
        c.setFillColor(GOLD)
        c.rect(0, 0, self._width, 4, fill=1, stroke=0)
        # Title
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(24, 80, "FARAGLIONI & AEGIS")
        c.setFont("Helvetica", 13)
        c.setFillColor(GOLD)
        c.drawString(24, 58, "Market Intelligence Engine")
        c.setFillColor(WHITE)
        c.setFont("Helvetica", 10)
        c.drawString(24, 38, "Phase 1: Ingestion Feed Calibration & Architecture")
        c.setFont("Helvetica", 9)
        c.setFillColor(HexColor("#94a3b8"))
        c.drawString(24, 20, f"24 May 2026  |  Confidential — Internal Use Only")

    def wrap(self, availWidth, availHeight):
        return self._width, self.height


class InfoBox(Flowable):
    """Coloured callout box."""
    def __init__(self, text, width, bg=None, border=None, text_color=None):
        super().__init__()
        self.text = text
        self._width = width
        self.bg = bg or LIGHT
        self.border = border or GOLD
        self.text_color = text_color or NAVY
        self.height = 0  # computed in wrap

    def wrap(self, availWidth, availHeight):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        # Estimate height
        chars_per_line = int((self._width - 32) / 5.5)
        lines = max(2, len(self.text) // chars_per_line + 2)
        self.height = lines * 14 + 16
        return self._width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg)
        c.roundRect(0, 0, self._width, self.height, 4, fill=1, stroke=0)
        c.setFillColor(self.border)
        c.rect(0, 0, 3, self.height, fill=1, stroke=0)
        c.setFillColor(self.text_color)
        c.setFont("Helvetica", 9)
        # Simple text wrap
        words = self.text.split()
        line, lines_drawn = [], []
        max_w = self._width - 28
        for word in words:
            test = " ".join(line + [word])
            from reportlab.pdfbase.pdfmetrics import stringWidth
            if stringWidth(test, "Helvetica", 9) < max_w:
                line.append(word)
            else:
                lines_drawn.append(" ".join(line))
                line = [word]
        if line:
            lines_drawn.append(" ".join(line))
        y = self.height - 14
        for l in lines_drawn:
            c.drawString(12, y, l)
            y -= 13

    def wrap(self, availWidth, availHeight):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        words = self.text.split()
        line, lines_drawn = [], []
        max_w = self._width - 28
        for word in words:
            test = " ".join(line + [word])
            if stringWidth(test, "Helvetica", 9) < max_w:
                line.append(word)
            else:
                lines_drawn.append(" ".join(line))
                line = [word]
        if line:
            lines_drawn.append(" ".join(line))
        self.height = len(lines_drawn) * 13 + 20
        return self._width, self.height


# ── Styles ───────────────────────────────────────────────────────────────────

def build_styles():
    base = getSampleStyleSheet()
    s = {}

    s['body'] = ParagraphStyle('body', fontName='Helvetica', fontSize=9.5,
        leading=15, textColor=NAVY, alignment=TA_JUSTIFY,
        spaceAfter=8)

    s['body_left'] = ParagraphStyle('body_left', fontName='Helvetica', fontSize=9.5,
        leading=15, textColor=NAVY, alignment=TA_LEFT,
        spaceAfter=6)

    s['h2'] = ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=11,
        leading=16, textColor=NAVY, spaceBefore=14, spaceAfter=4)

    s['h3'] = ParagraphStyle('h3', fontName='Helvetica-Bold', fontSize=9.5,
        leading=14, textColor=GOLD, spaceBefore=10, spaceAfter=4,
        textTransform='uppercase')

    s['caption'] = ParagraphStyle('caption', fontName='Helvetica-Oblique',
        fontSize=8.5, leading=12, textColor=SLATE, spaceAfter=6)

    s['code'] = ParagraphStyle('code', fontName='Courier', fontSize=8,
        leading=12, textColor=NAVY, backColor=LIGHT,
        leftIndent=8, rightIndent=8, spaceBefore=4, spaceAfter=4,
        borderPad=6)

    s['bullet'] = ParagraphStyle('bullet', fontName='Helvetica', fontSize=9.5,
        leading=14, textColor=NAVY, leftIndent=14, spaceAfter=4,
        bulletIndent=4)

    s['tag_green'] = ParagraphStyle('tag_green', fontName='Helvetica-Bold',
        fontSize=8, textColor=WHITE, backColor=GREEN, alignment=TA_CENTER)

    s['tag_red'] = ParagraphStyle('tag_red', fontName='Helvetica-Bold',
        fontSize=8, textColor=WHITE, backColor=RED, alignment=TA_CENTER)

    s['footer'] = ParagraphStyle('footer', fontName='Helvetica', fontSize=7.5,
        textColor=SLATE, alignment=TA_CENTER)

    return s


# ── Table helpers ────────────────────────────────────────────────────────────

def header_table_style(extra=None):
    base = [
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR',  (0, 0), (-1, 0), WHITE),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 7),
        ('TOPPADDING',    (0, 0), (-1, 0), 7),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LIGHT]),
        ('FONTNAME',   (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',   (0, 1), (-1, -1), 8.5),
        ('TOPPADDING',    (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.4, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]
    if extra:
        base.extend(extra)
    return TableStyle(base)


def tick(text, color=GREEN):
    return Paragraph(f'<font color="#{color.hexval()[2:]}"><b>{text}</b></font>', 
                     ParagraphStyle('t', fontName='Helvetica-Bold', fontSize=8.5,
                                    textColor=color, alignment=TA_CENTER))


def p(text, style):
    return Paragraph(text, style)


# ── Page template ────────────────────────────────────────────────────────────

def on_page(canvas, doc, styles):
    canvas.saveState()
    # Footer bar
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PAGE_W, 18, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.rect(0, 18, PAGE_W, 1.5, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(MARGIN, 6, "Faraglioni & Aegis  ·  Market Intelligence Engine  ·  Phase 1 Specification")
    canvas.drawRightString(PAGE_W - MARGIN, 6, f"Page {doc.page}")
    canvas.restoreState()


# ── Content builder ──────────────────────────────────────────────────────────

def build_story(styles, avail_w):
    S = styles
    story = []

    # Cover
    story.append(CoverHeader(avail_w))
    story.append(Spacer(1, 14))

    # Executive Summary
    story.append(SectionLabel("", "Executive Summary", avail_w))
    story.append(Spacer(1, 6))
    story.append(GoldRule())

    summary_text = (
        "This report revises the Phase 1 ingestion architecture for the Faraglioni &amp; Aegis "
        "Market Intelligence Engine, incorporating a more honest assessment of available free data "
        "sources and the material advantage of an authenticated Bloomberg web subscription. "
        "The core design principle is <b>signal density over volume</b>: a small number of "
        "high-quality, pre-filtered text streams will outperform a raw firehose when the "
        "downstream consumer is a Gemini call with a ~35k-character context window. "
        "All calibration decisions flow from that constraint."
    )
    story.append(p(summary_text, S['body']))
    story.append(Spacer(1, 4))

    # Key findings box
    findings = [
        ["Finding", "Implication"],
        ["Bloomberg email alerts provide full-text, push-delivered, pre-curated articles", "Primary source — no scraping required"],
        ["Bloomberg web subscription enables authenticated full-text retrieval", "Clickthrough paywall is a non-issue; email alerts preferred for automation"],
        ["Reuters / FT RSS feeds deliver headline + ~150 chars only", "Insufficient substance for Gemini injection; excluded"],
        ["Google News RSS by ticker delivers ~400-char snippets, Google-ranked", "Useful secondary layer; free, stable, no auth"],
        ["Twitter / RSSHub is high-velocity but low reliability and low quality", "Excluded from core architecture; optional tier-3 overlay"],
        ["ECB / Fed / IMF releases redundant for 90% equity portfolio", "Covered by Bloomberg; excluded to reduce noise"],
    ]
    t = Table(findings, colWidths=[avail_w * 0.55, avail_w * 0.45])
    t.setStyle(header_table_style([
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 16))

    # ── Section 1 ──────────────────────────────────────────────────────────
    story.append(SectionLabel(1, "Source Landscape & Honest Assessment", avail_w))
    story.append(Spacer(1, 6))
    story.append(GoldRule())

    story.append(p("1.1  Bloomberg (Primary — High Signal, Full Text)", S['h2']))
    story.append(p(
        "An authenticated Bloomberg web subscription changes the calculus materially. "
        "The paywall is a non-issue for an authenticated session, making bloomberg.com a "
        "legitimate full-text source. However, <b>email alerts are the preferred mechanism</b> "
        "rather than browser scraping, for three reasons:",
        S['body']
    ))

    reasons = [
        ["Reason", "Detail"],
        ["Zero scraping fragility", "Bloomberg's alert HTML is stable, structured, and arrives push-style — no polling, no site layout changes to track"],
        ["Bloomberg does the curation", "Alert configuration maps your topics to Bloomberg's own editorial engine; you get only relevant items"],
        ["Automatic portfolio sync", "Alert topics can be generated from live holdings data; you update them only when holdings change materially"],
    ]
    t = Table(reasons, colWidths=[avail_w * 0.30, avail_w * 0.70])
    t.setStyle(header_table_style())
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(p(
        "Bloomberg web alerts cover the full article body (not a teaser), include charts and "
        "data tables in the HTML, and are timestamped precisely. They arrive in your Gmail "
        "inbox within minutes of publication. A simple IMAP reader routes them to the "
        "snapshots folder that the Finance Tool already monitors via <font face='Courier' size=8>"
        "_load_articles_raw()</font>.",
        S['body']
    ))

    story.append(p("Bloomberg Alert Topics — Recommended Configuration", S['h3']))

    alert_data = [
        ["Category", "Topics to Configure", "Alert Frequency"],
        ["ETF Holdings", "Each ticker you hold: SWDA.L, IUSA.L, SGLN.L, ERNS.L, IBCI.L, etc.", "As it happens"],
        ["Top Look-Through", "Top 5 constituents by effective portfolio weight (auto-generated)", "As it happens"],
        ["Macro — Equity", "S&P 500, MSCI World, Nasdaq, European equities, FTSE 100", "Daily digest"],
        ["Macro — Key Data", "US CPI, NFP, Fed decisions, BoE decisions (monthly)", "As it happens"],
        ["Sector Exposure", "Technology, Financials, Healthcare — per your look-through breakdown", "Daily digest"],
        ["FX (GBP-relevant)", "GBP/USD, GBP/EUR — relevant for NAV reporting", "Daily digest"],
    ]
    t = Table(alert_data, colWidths=[avail_w * 0.20, avail_w * 0.55, avail_w * 0.25])
    t.setStyle(header_table_style([
        ('FONTSIZE', (0, 1), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    story.append(p("1.2  Google News RSS (Secondary — Free Snippets, Portfolio-Specific)", S['h2']))
    story.append(p(
        "Google News RSS is the most underrated free financial data source available. "
        "It returns Google-curated, relevance-ranked results for arbitrary queries with "
        "~400-character snippets — enough substance for Gemini to work with. Google's own "
        "ranking algorithm pre-filters garbage, and the feeds are completely stable with no "
        "authentication required.",
        S['body']
    ))

    story.append(p("Feed format:", S['h3']))
    story.append(p(
        'https://news.google.com/rss/search?q={QUERY}+when:1d&amp;hl=en-GB&amp;gl=GB&amp;ceid=GB:en',
        ParagraphStyle('code2', fontName='Courier', fontSize=8.5, leading=14,
                       textColor=NAVY, backColor=LIGHT, leftIndent=8, spaceAfter=6,
                       borderPad=6)
    ))

    story.append(p(
        "The <font face='Courier' size=8>when:1d</font> parameter restricts to the last 24 hours. "
        "The <font face='Courier' size=8>hl=en-GB&amp;gl=GB</font> parameters bias results toward "
        "UK/European framing relevant to a GBP-denominated portfolio.",
        S['body']
    ))

    story.append(p("Per-holding query examples:", S['h3']))
    gnews_data = [
        ["Yahoo Ticker", "Google News Query", "Why"],
        ["SWDA.L", '"MSCI World" OR "global equities" OR "developed markets"', "Index-level coverage"],
        ["IUSA.L", '"S&P 500" OR "SPX" OR "US equities"', "Index-level coverage"],
        ["SGLN.L", '"gold price" OR "XAU" OR "bullion" OR "safe haven"', "Commodity-specific"],
        ["IBCI.L", '"inflation" OR "HICP" OR "inflation-linked bonds"', "Rates/inflation-specific"],
        ["ERNS.L", '"money market" OR "T-bills" OR "ultrashort bonds"', "Low-priority; small position"],
        ["[Look-through top 5]", 'Company name OR ticker', "Individual stock signals"],
    ]
    t = Table(gnews_data, colWidths=[avail_w * 0.18, avail_w * 0.52, avail_w * 0.30])
    t.setStyle(header_table_style([('FONTSIZE', (0, 1), (-1, -1), 8)]))
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(p("1.3  Sources Excluded — and Why", S['h2']))

    excl_data = [
        ["Source", "What you actually get", "Decision"],
        ["Reuters / FT / Bloomberg RSS (unauthenticated)", "Headline + ~150 chars teaser only", "EXCLUDED — insufficient substance"],
        ["Twitter / RSSHub", "High velocity, low quality; API access fragile since 2023 changes", "EXCLUDED — not worth the fragility"],
        ["ECB / Fed / IMF press releases", "Relevant for rates portfolios; covered exhaustively by Bloomberg", "EXCLUDED — redundant for 90% equity"],
        ["Seeking Alpha (free)", "Partial full text; degrades rapidly without subscription", "EXCLUDED — unreliable at free tier"],
        ["Finviz ticker news", "Aggregates MarketWatch / Yahoo Finance; moderate quality", "OPTIONAL — tier-3 fallback only"],
    ]
    t = Table(excl_data, colWidths=[avail_w * 0.30, avail_w * 0.42, avail_w * 0.28])
    t.setStyle(header_table_style([
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TEXTCOLOR', (2, 1), (2, -1), RED),
        ('FONTNAME', (2, 1), (2, -1), 'Helvetica-Bold'),
    ]))
    story.append(t)
    story.append(Spacer(1, 16))

    # ── Section 2 ──────────────────────────────────────────────────────────
    story.append(SectionLabel(2, "Final Architecture", avail_w))
    story.append(Spacer(1, 6))
    story.append(GoldRule())

    story.append(p(
        "The two-source architecture is deliberately minimal. Every additional source adds "
        "maintenance overhead and noise risk. The goal is a clean, high-confidence signal "
        "set — not comprehensive coverage.",
        S['body']
    ))

    arch_data = [
        ["Layer", "Source", "Mechanism", "Text Quality", "Volume/Day"],
        ["Primary", "Bloomberg Email Alerts", "IMAP reader → snapshots folder", "Full article", "10–25 items"],
        ["Secondary", "Google News RSS per ticker", "feedparser poll (3× daily)", "~400-char snippets", "15–30 items"],
        ["Override", "Manual PDF drop (existing)", "Existing _load_articles_raw()", "Full text", "As needed"],
    ]
    col_w = [avail_w * 0.12, avail_w * 0.25, avail_w * 0.30, avail_w * 0.18, avail_w * 0.15]
    t = Table(arch_data, colWidths=col_w)
    t.setStyle(header_table_style([
        ('BACKGROUND', (0, 1), (0, 1), HexColor("#e8f4f0")),
        ('BACKGROUND', (0, 2), (0, 2), HexColor("#eef2f8")),
        ('BACKGROUND', (0, 3), (0, 3), HexColor("#fdf8ee")),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(p(
        "The two layers are complementary: Bloomberg alerts provide depth on topics Bloomberg "
        "considers newsworthy (editorially curated); Google News RSS provides breadth on "
        "portfolio-specific queries (algorithmically curated). Together they cover both "
        "market-wide events and holding-specific developments without redundancy.",
        S['body']
    ))

    story.append(Spacer(1, 6))

    # Flow diagram as a table
    story.append(p("Data Flow", S['h3']))
    flow_data = [
        ["Bloomberg email alerts\n(IMAP reader)", "→", "news_ingestion.py\n(dedup, parse, store)", "→", "market_intelligence.db\n(news_items table)"],
        ["Google News RSS\n(feedparser, 3×/day)", "→", "", "", ""],
        ["Manual PDF drop\n(existing snapshots folder)", "→", "", "→", ""],
    ]
    # Simplified flow as prose
    story.append(p(
        "Bloomberg email alerts + Google News RSS feeds "
        "&#10132; <font face='Courier' size=8>news_ingestion.py</font> "
        "(dedup + parse + tag) &#10132; <font face='Courier' size=8>market_intelligence.db</font> "
        "&#10132; Phase 2 relevance engine &#10132; Gemini prompt injection "
        "&#10132; Daily digest HTML",
        ParagraphStyle('flow', fontName='Helvetica', fontSize=9, leading=14,
                       textColor=NAVY, backColor=LIGHT, leftIndent=8, rightIndent=8,
                       spaceAfter=8, borderPad=8)
    ))
    story.append(Spacer(1, 16))

    # ── Section 3 ──────────────────────────────────────────────────────────
    story.append(SectionLabel(3, "Database Schema", avail_w))
    story.append(Spacer(1, 6))
    story.append(GoldRule())

    story.append(p(
        "Market intelligence data lives in a <b>separate SQLite file</b> "
        "(<font face='Courier' size=8>market_intelligence.db</font>) alongside the existing "
        "<font face='Courier' size=8>portfolio_history.db</font> and "
        "<font face='Courier' size=8>holdings.db</font>. News data grows fast and must not "
        "bloat the portfolio DB or interfere with WAL-mode writes during recalculation.",
        S['body']
    ))

    story.append(p("3.1  news_items (Core Store)", S['h2']))

    schema1 = (
        "CREATE TABLE IF NOT EXISTS news_items (\n"
        "    id              INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "    source          TEXT NOT NULL,     -- 'bloomberg_email' | 'google_news' | 'manual_pdf'\n"
        "    source_url      TEXT,\n"
        "    headline        TEXT NOT NULL,\n"
        "    body_snippet    TEXT,              -- first 1500 chars for relevance scoring\n"
        "    full_text       TEXT,              -- full article (Bloomberg email only)\n"
        "    published_at    TEXT,              -- ISO-8601\n"
        "    fetched_at      TEXT NOT NULL,\n"
        "    tickers_mentioned TEXT,            -- JSON: [\"SWDA.L\", \"IUSA.L\"]\n"
        "    relevance_score REAL,              -- computed by Phase 2 engine\n"
        "    relevance_tier  INTEGER,           -- 1=critical, 2=relevant, 3=background\n"
        "    content_hash    TEXT UNIQUE,       -- SHA-256 prefix for deduplication\n"
        "    used_in_digest  INTEGER DEFAULT 0, -- 1 = consumed by a generated digest\n"
        "    digest_date     TEXT               -- date of digest that consumed this item\n"
        ");"
    )
    story.append(p(schema1, ParagraphStyle('schema', fontName='Courier', fontSize=7.5,
                                            leading=11, textColor=NAVY, backColor=LIGHT,
                                            leftIndent=8, rightIndent=8, spaceBefore=4,
                                            spaceAfter=8, borderPad=8)))

    story.append(p("3.2  tracked_constituents (Dynamic Keyword Registry)", S['h2']))
    story.append(p(
        "This is the critical calibration table. It maps live portfolio positions to the "
        "keyword strings used by the relevance engine. The table is auto-populated on each "
        "<b>Recalculate ALL</b> run — no manual maintenance required between rebalances.",
        S['body']
    ))

    schema2 = (
        "CREATE TABLE IF NOT EXISTS tracked_constituents (\n"
        "    yahoo_ticker         TEXT PRIMARY KEY,\n"
        "    asset_name           TEXT,\n"
        "    portfolio_weight     REAL,        -- live weight, updated on recalculate\n"
        "    portfolio_value_gbp  REAL,\n"
        "    keywords_ticker      TEXT,        -- JSON: [\"SWDA\", \"SWDA.L\"]\n"
        "    keywords_index       TEXT,        -- JSON: [\"MSCI World\", \"developed markets\"]\n"
        "    keywords_sector      TEXT,        -- JSON: [\"technology\", \"financials\"]\n"
        "    keywords_geography   TEXT,        -- JSON: [\"US equities\", \"Europe\"]\n"
        "    keywords_constituents TEXT,       -- JSON: top-5 look-through names\n"
        "    catalyst_coefficient REAL DEFAULT 1.0,  -- Phase 2 weight multiplier\n"
        "    updated_at           TEXT\n"
        ");"
    )
    story.append(p(schema2, ParagraphStyle('schema2', fontName='Courier', fontSize=7.5,
                                            leading=11, textColor=NAVY, backColor=LIGHT,
                                            leftIndent=8, rightIndent=8, spaceBefore=4,
                                            spaceAfter=8, borderPad=8)))

    story.append(p(
        "The keyword arrays are populated by reading from three existing sources in sequence: "
        "<font face='Courier' size=8>storage.load_latest_portfolio()</font> for weights and tickers, "
        "<font face='Courier' size=8>holdings_db.compute_top_holdings()</font> for look-through "
        "constituent names, and <font face='Courier' size=8>holdings_db.get_cached_metadata()</font> "
        "for sector and geography tags.",
        S['body']
    ))
    story.append(Spacer(1, 16))

    # ── Section 4 ──────────────────────────────────────────────────────────
    story.append(SectionLabel(4, "Keyword Calibration — The Critical Detail", avail_w))
    story.append(Spacer(1, 6))
    story.append(GoldRule())

    story.append(p(
        "Keyword calibration is the hardest problem in Phase 1. A Bloomberg article about an "
        "S&amp;P 500 rally is relevant to IUSA.L but will never mention the ticker 'IUSA.L'. "
        "The mapping must resolve through multiple layers of abstraction.",
        S['body']
    ))

    story.append(p("4.1  Resolution Hierarchy", S['h2']))

    hier_data = [
        ["Priority", "Key Type", "Example (SWDA.L)", "Match Type"],
        ["1 — Highest", "ETF ticker", "SWDA, SWDA.L", "Exact"],
        ["2", "ETF common name", "iShares Core MSCI World, BlackRock", "Fuzzy"],
        ["3", "Index tracked", "MSCI World Index, MSCI ACWI", "Fuzzy"],
        ["4", "Look-through constituents", "Apple, AAPL, Nvidia, NVDA, Microsoft", "Exact + fuzzy"],
        ["5", "Sector exposure", "technology, financials, healthcare", "Keyword"],
        ["6 — Lowest", "Geography exposure", "US equities, developed markets, Europe", "Keyword"],
    ]
    t = Table(hier_data, colWidths=[avail_w * 0.20, avail_w * 0.22, avail_w * 0.35, avail_w * 0.23])
    t.setStyle(header_table_style([
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TEXTCOLOR', (0, 1), (0, 1), HexColor("#8b2635")),
        ('FONTNAME', (0, 1), (0, 1), 'Helvetica-Bold'),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(p("4.2  Bloomberg-Specific Keyword Calibration", S['h2']))
    story.append(p(
        "Bloomberg articles use specific terminology that differs from common usage. "
        "The keyword arrays must be calibrated to Bloomberg's editorial vocabulary, "
        "not generic financial language.",
        S['body']
    ))

    bberg_kw = [
        ["Ticker", "Bloomberg Terms to Include in Keywords"],
        ["SWDA.L", '"global equities", "DM equities", "MSCI World", "developed markets", "world stocks"'],
        ["IUSA.L", '"SPX", "S&P 500", "US equities", "large cap US", "US stocks"'],
        ["SGLN.L", '"XAU", "gold prices", "bullion", "safe haven flows", "gold ETF"'],
        ["IBCI.L", '"inflation-linked", "HICP", "real yields", "breakeven inflation", "linkers"'],
        ["ERNS.L", '"money market", "T-bills", "ultrashort", "cash equivalent"'],
        ["Look-through top-5", "Company name (full), ticker (Yahoo format), common abbreviation"],
    ]
    t = Table(bberg_kw, colWidths=[avail_w * 0.18, avail_w * 0.82])
    t.setStyle(header_table_style([('FONTSIZE', (0, 1), (-1, -1), 8)]))
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(p("4.3  Alert Topic Auto-Generation", S['h2']))
    story.append(p(
        "Rather than manually maintaining Bloomberg alert topics, a script run after each "
        "<b>Recalculate ALL</b> generates a structured list of recommended alert topics "
        "from the live portfolio. This keeps the alert configuration in sync with your "
        "holdings without requiring manual updates between rebalances.",
        S['body']
    ))

    autogen = (
        "# bloomberg_alert_config.py — runs post-recalculate\n\n"
        "def generate_alert_topics(account='Consolidated') -> dict:\n"
        "    cached = storage.load_latest_portfolio(account)\n"
        "    positions = cached['positions']  # {ticker: shares}\n"
        "    last_px   = storage.load_last_prices(account)\n"
        "    top_holdings = compute_top_holdings(df_enriched)  # from lookahead engine\n\n"
        "    # ETF-level topics (exact tickers)\n"
        "    etf_topics = list(positions.keys())\n\n"
        "    # Index-level topics (from keyword map)\n"
        "    index_topics = [KEYWORD_MAP[t]['index'] for t in etf_topics\n"
        "                    if t in KEYWORD_MAP]\n\n"
        "    # Look-through top-5 by effective portfolio weight\n"
        "    constituent_topics = [\n"
        "        row['constituent_name'] for _, row\n"
        "        in top_holdings.head(5).iterrows()\n"
        "    ]\n"
        "    return {\n"
        "        'etf_tickers':   etf_topics,\n"
        "        'index_terms':   index_topics,\n"
        "        'constituents':  constituent_topics,\n"
        "        'generated_at':  datetime.utcnow().isoformat()\n"
        "    }"
    )
    story.append(p(autogen, ParagraphStyle('autogen', fontName='Courier', fontSize=7.5,
                                            leading=11, textColor=NAVY, backColor=LIGHT,
                                            leftIndent=8, rightIndent=8, spaceBefore=4,
                                            spaceAfter=8, borderPad=8)))
    story.append(Spacer(1, 16))

    # ── Section 5 ──────────────────────────────────────────────────────────
    story.append(SectionLabel(5, "Garbage Filtering — The Core Concern", avail_w))
    story.append(Spacer(1, 6))
    story.append(GoldRule())

    story.append(p(
        "This is the right question to optimise around. The two-stage funnel approach "
        "addresses garbage at source level before any relevance scoring is applied.",
        S['body']
    ))

    story.append(p("Stage 1 — Source-Level Filtering (Phase 1)", S['h2']))
    story.append(p(
        "Only collect from sources where the <i>baseline</i> quality is high. "
        "Bloomberg email alerts pass through Bloomberg's own editorial filter — "
        "if Bloomberg didn't think it was worth publishing, it won't arrive. "
        "Google News RSS uses Google's ranking algorithm as a pre-filter. "
        "Neither source requires you to evaluate individual items for relevance "
        "before ingestion.",
        S['body']
    ))

    story.append(p("Stage 2 — Relevance Scoring (Phase 2 Preview)", S['h2']))
    story.append(p(
        "The relevance score computed in Phase 2 uses portfolio weight as its primary "
        "input — an article about a 15% holding matters more than one about a 2% holding, "
        "regardless of content. The score formula is:",
        S['body']
    ))

    formula = "Score = (Portfolio Weight %) × (Keyword Match Depth 1–5) × (Catalyst Coefficient)"
    story.append(p(formula, ParagraphStyle('formula', fontName='Courier', fontSize=9,
                                            leading=14, textColor=NAVY, backColor=LIGHT,
                                            leftIndent=8, rightIndent=8, spaceBefore=4,
                                            spaceAfter=8, borderPad=8, alignment=TA_CENTER)))

    tier_data = [
        ["Relevance Tier", "Score Range", "Action", "Example"],
        ["Tier 1 — Critical", "> 30", "Always inject into Gemini prompt", "Bloomberg article on SWDA.L (15% weight) mentioning specific index rebalance"],
        ["Tier 2 — Relevant", "10–30", "Include if context window permits", "Google News snippet on US tech sector (major look-through exposure)"],
        ["Tier 3 — Background", "< 10", "Exclude from daily digest; archive only", "General market colour with no direct portfolio connection"],
    ]
    t = Table(tier_data, colWidths=[avail_w * 0.22, avail_w * 0.16, avail_w * 0.22, avail_w * 0.40])
    t.setStyle(header_table_style([
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BACKGROUND', (0, 1), (-1, 1), HexColor("#fdf0f0")),
        ('BACKGROUND', (0, 2), (-1, 2), HexColor("#f0f8f0")),
        ('BACKGROUND', (0, 3), (-1, 3), HexColor("#f5f5f5")),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(p(
        "The hard cap for Gemini injection is <b>top-10 Tier 1+2 items per session</b>. "
        "This fits comfortably within the ~35k-character context window even with full "
        "Bloomberg article text. Items beyond the cap are archived in "
        "<font face='Courier' size=8>news_items</font> with "
        "<font face='Courier' size=8>relevance_tier = 3</font> for historical reference "
        "but never reach the LLM.",
        S['body']
    ))
    story.append(Spacer(1, 16))

    # ── Section 6 ──────────────────────────────────────────────────────────
    story.append(SectionLabel(6, "Scheduling & Integration with Existing Tool", avail_w))
    story.append(Spacer(1, 6))
    story.append(GoldRule())

    story.append(p("6.1  Scheduling Windows", S['h2']))

    sched_data = [
        ["Window", "BST Time", "Market Context", "Priority Sources"],
        ["Pre-London open", "07:55", "Asian session wrap; ECB/Fed overnight", "Bloomberg emails (overnight batch); Google News refresh"],
        ["US pre-market", "14:25", "09:25 ET — key for US-driven portfolio", "Bloomberg real-time alerts; Google News refresh"],
        ["US open +1h", "17:30", "First hour US session digested", "Bloomberg breaking alerts; final Google News pull"],
    ]
    t = Table(sched_data, colWidths=[avail_w * 0.20, avail_w * 0.12, avail_w * 0.30, avail_w * 0.38])
    t.setStyle(header_table_style([('FONTSIZE', (0, 1), (-1, -1), 8)]))
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(p("6.2  Integration Points with Existing Codebase", S['h2']))
    story.append(p(
        "The ingestion module plugs into the existing Finance Tool with minimal disruption. "
        "Only two existing functions require modification:",
        S['body']
    ))

    integ_data = [
        ["File", "Function", "Change Required"],
        ["newsletter_ui.py", "assemble_newsletter_data()", "Replace _load_articles_from_folder() call with DB query returning top-N by relevance_score"],
        ["app.py", "_ensure_auto_refresh_running()", "Add news ingestion calls to existing scheduler thread at 07:55, 14:25, 17:30 BST"],
        ["newsletter_schedule.json", "Config schema", "Add ingestion_enabled, ingestion_windows[] fields"],
        ["news_ingestion.py", "New module", "FeedIngester class: Bloomberg IMAP reader + Google News RSS fetcher + dedup logic"],
        ["market_intelligence.db", "New database", "news_items, tracked_constituents, asset_benchmarks tables"],
    ]
    t = Table(integ_data, colWidths=[avail_w * 0.25, avail_w * 0.28, avail_w * 0.47])
    t.setStyle(header_table_style([
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BACKGROUND', (0, 4), (-1, 4), HexColor("#eef8f0")),
        ('BACKGROUND', (0, 5), (-1, 5), HexColor("#eef8f0")),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(p("6.3  Gemini Quota — Risk Mitigation", S['h2']))
    story.append(p(
        "Three ingestion sessions per day × the distillation call = up to 6 Gemini requests "
        "daily on the free tier. This is manageable but warrants monitoring. Mitigations:",
        S['body']
    ))

    for bullet in [
        "Cache distilled news briefs in <font face='Courier' size=8>market_intelligence.db</font> — reuse the same brief for the 14:25 and 17:30 sessions if no new Tier 1 items have arrived since 07:55",
        "The daily digest uses Gemini Flash (lowest quota consumption) — same model already used for newsletter generation",
        "Rate the ingestion as a separate quota bucket from the weekly newsletter; they use different prompt structures",
        "Add a <font face='Courier' size=8>last_gemini_call</font> timestamp guard: do not re-inject if called within 90 minutes with the same top-10 items",
    ]:
        story.append(p(f"&#8226;  {bullet}", S['bullet']))
    story.append(Spacer(1, 16))

    # ── Section 7 ──────────────────────────────────────────────────────────
    story.append(SectionLabel(7, "Implementation Checklist", avail_w))
    story.append(Spacer(1, 6))
    story.append(GoldRule())

    checklist = [
        ["#", "Task", "Effort", "Priority"],
        ["1", "Configure Bloomberg email alerts: top holdings + 5 macro topics", "1 hour", "P0 — do first"],
        ["2", "Set up Gmail filter: label bloomberg-alerts, skip inbox", "15 min", "P0"],
        ["3", "Create market_intelligence.db with 3-table schema", "2 hours", "P0"],
        ["4", "Write bloomberg_email_imap_reader() — IMAP → snapshots bridge", "3 hours", "P0"],
        ["5", "Write google_news_rss_fetcher() — feedparser + per-ticker queries", "2 hours", "P0"],
        ["6", "Write content_hash dedup logic — prevent duplicate items across sources", "1 hour", "P0"],
        ["7", "Write tracked_constituents auto-population from storage + holdings_db", "2 hours", "P0"],
        ["8", "Seed keyword arrays manually for top 8 holdings (first pass)", "2 hours", "P0"],
        ["9", "Wire ingestion into existing scheduler thread in app.py", "1 hour", "P1"],
        ["10", "Update assemble_newsletter_data() to query news_items instead of folder", "2 hours", "P1"],
        ["11", "Add ingestion status panel to Streamlit Diagnostics tab", "1 hour", "P2"],
        ["12", "Build bloomberg_alert_config.py auto-generator (post-recalculate)", "2 hours", "P2"],
    ]
    t = Table(checklist, colWidths=[avail_w * 0.06, avail_w * 0.58, avail_w * 0.14, avail_w * 0.22])
    t.setStyle(header_table_style([
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BACKGROUND', (3, 1), (3, 8), HexColor("#fff8ee")),
        ('BACKGROUND', (3, 9), (3, 10), HexColor("#f0f8ff")),
        ('BACKGROUND', (3, 11), (3, 12), HexColor("#f8f8f8")),
        ('TEXTCOLOR', (3, 1), (3, 8), HexColor("#c9a84c")),
        ('FONTNAME', (3, 1), (3, 8), 'Helvetica-Bold'),
        ('TEXTCOLOR', (3, 9), (3, 10), HexColor("#2e7d5e")),
        ('FONTNAME', (3, 9), (3, 10), 'Helvetica-Bold'),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(p(
        "P0 items (tasks 1–8) constitute a complete, working ingestion pipeline in approximately "
        "two weeks of part-time development. P1 items (9–10) connect the pipeline to the "
        "existing newsletter and daily digest flows. P2 items (11–12) add operational polish "
        "but are not required for Phase 2 to begin.",
        S['body']
    ))
    story.append(Spacer(1, 16))

    # ── Section 8 ──────────────────────────────────────────────────────────
    story.append(SectionLabel(8, "Risks & Mitigations", avail_w))
    story.append(Spacer(1, 6))
    story.append(GoldRule())

    risk_data = [
        ["Risk", "Likelihood", "Impact", "Mitigation"],
        ["Bloomberg email alert format changes", "Low", "Medium", "IMAP reader uses HTML body parsing with fallback to plain text; Bloomberg format is stable"],
        ["Google News RSS rate limiting", "Low", "Low", "3 requests/day per ticker is well within limits; add 2s delay between fetches"],
        ["Gemini daily quota exhausted by 3x digests", "Medium", "Medium", "Cache briefs; 90-min guard; Flash model; quota monitoring in Diagnostics tab"],
        ["Keyword false positives generating noise", "Medium", "Medium", "Tier 1 = exact ticker match only; broader keywords only reach Tier 2"],
        ["Bloomberg alert topics drift from portfolio", "Low", "Low", "Auto-generation script flags changes; manual update <10 min when rebalancing"],
        ["news_items table grows unbounded", "High (long term)", "Low", "Add retention policy: auto-delete items older than 30 days with used_in_digest=1"],
    ]
    t = Table(risk_data, colWidths=[avail_w * 0.30, avail_w * 0.13, avail_w * 0.10, avail_w * 0.47])
    t.setStyle(header_table_style([
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TEXTCOLOR', (1, 3), (1, 3), RED),
        ('FONTNAME', (1, 3), (1, 3), 'Helvetica-Bold'),
        ('TEXTCOLOR', (1, 6), (1, 6), RED),
        ('FONTNAME', (1, 6), (1, 6), 'Helvetica-Bold'),
    ]))
    story.append(t)
    story.append(Spacer(1, 16))

    # Closing note
    story.append(NavyRule())
    story.append(p(
        "<i>This report covers Phase 1 (Ingestion Feed Calibration &amp; Schema Architecture) only. "
        "Phase 2 (Exposure-Weighted Relevance Engine &amp; Prompt Injection) and Phase 3 "
        "(Finance Tool Integration &amp; Delivery Mechanics) are addressed in separate specifications. "
        "Phase 2 can begin once news_items has 3–5 days of data to calibrate the scoring weights against.</i>",
        S['caption']
    ))

    return story


# ── Build PDF ────────────────────────────────────────────────────────────────

def build_pdf(output_path: str):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=2.5 * cm,
        title="Faraglioni & Aegis — Market Intelligence Engine Phase 1",
        author="Faraglioni & Aegis",
    )

    styles = build_styles()
    avail_w = PAGE_W - 2 * MARGIN

    story = build_story(styles, avail_w)

    doc.build(
        story,
        onFirstPage=lambda c, d: on_page(c, d, styles),
        onLaterPages=lambda c, d: on_page(c, d, styles),
    )
    print(f"PDF written to {output_path}")


if __name__ == "__main__":
    build_pdf("C:/Users/divit/Desktop/Finance Tool/faraglioni_market_intelligence_phase1.pdf")

