# Marvel & DC Comics RAG + Content Pipeline — Architecture & Roadmap

**Author:** Drafted for Sharath
**Date:** 2026-06-15
**Status:** Design proposal (no code yet — review before build)

---

## 1. What we're building

Four stages, one pipeline:

1. **Ingest** — Pull every Marvel and DC character page from Wikipedia and Fandom (Marvel Database + DC Database) using their MediaWiki APIs.
2. **Store** — Land raw text + metadata, then chunk and embed into a local vector store.
3. **Retrieve (RAG)** — Answer questions and assemble character "context packs" by retrieving the most relevant chunks and feeding them to an LLM.
4. **Create** — Turn a retrieved context pack into a ~30-second vertical video reel: script → voiceover → visuals → rendered MP4 with captions.

Stack target you chose: **local and free** for storage, embeddings, and TTS. The generation LLM can be local (Ollama) or an API — both wired in.

---

## 2. System diagram

```
                    ┌─────────────────────────────────────────────┐
                    │                INGEST LAYER                  │
   Wikipedia API ──▶│  character_discovery → page_fetcher →        │
   Fandom API    ──▶│  cleaner/parser → raw store (JSONL + SQLite) │
   (Marvel/DC DB)   └───────────────────────┬─────────────────────┘
                                             │
                    ┌────────────────────────▼─────────────────────┐
                    │                STORAGE LAYER                  │
                    │  raw/  (JSONL per source)                     │
                    │  catalog.sqlite  (character index, provenance)│
                    │  chunker → embedder (BGE) → ChromaDB          │
                    └───────────────────────┬──────────────────────┘
                                            │
                    ┌───────────────────────▼──────────────────────┐
                    │                  RAG LAYER                    │
                    │  query → embed → vector search → rerank →     │
                    │  context assembly → LLM answer / context pack │
                    └───────────────────────┬──────────────────────┘
                                            │
                    ┌───────────────────────▼──────────────────────┐
                    │             CONTENT LAYER (30s reel)          │
                    │  script gen (LLM) → TTS (Kokoro) →            │
                    │  visuals → MoviePy/ffmpeg → captioned MP4     │
                    └──────────────────────────────────────────────┘
```

---

## 3. Stage 1 — Ingestion

### 3.1 Use the API, not HTML scraping

Wikipedia and all Fandom wikis run **MediaWiki**, so both expose `api.php`. Hitting the API is faster, gives clean structured data, and avoids brittle HTML parsing. Endpoints:

- Wikipedia: `https://en.wikipedia.org/w/api.php`
- Marvel Fandom: `https://marvel.fandom.com/api.php`
- DC Fandom: `https://dc.fandom.com/api.php`

### 3.2 Discovering "all characters"

Don't hand-maintain a name list. Enumerate via category membership, paging through every member.

- **Wikipedia**: `action=query&list=categorymembers` over categories like `Marvel Comics characters`, `DC Comics characters`, and their subcategories (walk the category tree to a sensible depth).
- **Fandom**: Marvel/DC Databases organize characters under category trees (e.g. `Characters`) and namespaces. Page through with `cmcontinue`. Expect tens of thousands of pages on Fandom — far more than Wikipedia, which only covers notable characters.

### 3.3 Fetching page content

For each discovered title, request plain-text extracts plus metadata in batches (the API accepts up to 50 titles per call):

```
action=query
  prop=extracts|pageprops|categories|info|revisions
  explaintext=1          # clean text, no wiki markup
  exsectionformat=plain
  titles=Spider-Man|Iron Man|...   # up to 50
  format=json
```

For richer structured fields (first appearance, alter ego, affiliations, powers), parse the **infobox** from raw wikitext (`rvprop=content`) with `mwparserfromhell`. Extracts give the prose; the infobox gives the facts table.

### 3.4 Being a good citizen (and not getting blocked)

This is the part that breaks naive scrapers. Build these in from day one:

- **Descriptive `User-Agent`** with a contact (MediaWiki policy requires identifying yourself).
- **`maxlag=5`** parameter on Wikipedia so you back off when their DB is busy.
- **Serial requests with a delay** (~1 req/sec per host) plus exponential backoff on `429`/`503`.
- **Resume/checkpointing** — persist a cursor per source so a crash at character 40,000 doesn't restart from zero. This matters because you chose to scrape everything.
- **Incremental re-sync** — store each page's `revid`; on later runs only re-fetch pages whose revision changed.

### 3.5 Output of this stage

One JSONL file per source, one line per character:

```json
{
  "id": "marvel_fandom:Spider-Man_(Peter_Parker)",
  "source": "marvel_fandom",
  "title": "Spider-Man (Peter Parker)",
  "url": "https://marvel.fandom.com/wiki/Spider-Man_(Peter_Parker)",
  "revid": 6543210,
  "fetched_at": "2026-06-15T10:00:00Z",
  "text": "Peter Benjamin Parker was a ...",
  "infobox": {"real_name": "Peter Parker", "affiliation": "Avengers", "...": "..."},
  "categories": ["Heroes", "Avengers members", "..."],
  "license": "CC BY-SA 3.0"
}
```

---

## 4. Stage 2 — Storage

### 4.1 Three layers, each doing one job

| Layer | Tech | Purpose |
|-------|------|---------|
| Raw | JSONL files in `data/raw/` | Immutable source of truth; re-chunk/re-embed any time without re-scraping |
| Catalog | SQLite (`catalog.sqlite`) | Character index, provenance, dedup, "which pages need refresh" queries |
| Vectors | **ChromaDB** (local, persistent) | Embedded chunks for semantic search |

Keeping raw separate from vectors is the single most useful decision here. Embedding models improve; when you want to re-embed all 40k characters with a better model next year, you re-run from raw rather than re-scraping the wikis.

### 4.2 Chunking

Character bios run long and are section-structured (Biography, Powers, Relationships). Chunk by **section with overlap**: roughly 400–800 tokens per chunk, ~80 token overlap, and stamp every chunk with metadata (`character`, `source`, `section`, `url`). Metadata lets the RAG layer filter ("only Marvel", "only the Powers section") before semantic search.

### 4.3 Embeddings (local, free)

Use `sentence-transformers` with an open model. Two reasonable picks:

- **`BAAI/bge-large-en-v1.5`** — strong English retrieval, 1024-dim, well-supported. Good default.
- **`BAAI/bge-m3`** — multilingual + long-context + supports dense/sparse hybrid, 568M params. Pick this if you want hybrid search or non-English wikis later.

Both run on CPU (slow for 40k characters) or a consumer GPU (much faster). Embedding the full corpus is a one-time batch job; budget for it.

---

## 5. Stage 3 — RAG

### 5.1 Retrieval flow

```
user query / character name
   → embed query (same BGE model)
   → ChromaDB similarity search (top ~20), with metadata filter
   → rerank top 20 → top 5 with a cross-encoder (BAAI/bge-reranker-base)
   → assemble context (5 chunks + citations)
   → LLM generates answer
```

The **reranker** step is what separates a toy RAG from one that gives tight, on-topic context. Vector search casts a wide net; the cross-encoder reorders by true relevance.

### 5.2 Generation LLM — two interchangeable backends

- **Local (free):** Ollama running e.g. Llama 3.x or Qwen. Zero API cost, fully offline, lower ceiling on quality.
- **API:** Claude or another hosted model for higher-quality scripts. Costs money per call.

Wire both behind one `LLMClient` interface so you flip a config flag. Start local to validate, switch to API for final-quality reels.

### 5.3 Two RAG entry points

1. **Q&A**: "Which villains has Daredevil fought most?" → retrieves across the corpus.
2. **Context pack** (feeds Stage 4): given a character, retrieve and compress their bio into a structured brief (origin, powers, 2–3 signature moments, key relationships). This brief is the raw material for the script.

---

## 6. Stage 4 — 30-second video reel

### 6.1 Sub-pipeline

```
context pack (from RAG)
   → script generation (LLM)         # ~75–90 words ≈ 30s narration
   → voiceover (Kokoro TTS → mp3)
   → visuals (image sequence / b-roll)
   → assembly (MoviePy + ffmpeg)     # 1080×1920 vertical, burned-in captions
   → output.mp4
```

### 6.2 Script generation

A 30-second reel is ~75–90 spoken words. Prompt the LLM with the context pack and a tight template: hook (first 3s), 2–3 punchy facts, payoff line. Output both the **narration** and **timed caption lines** so captions sync to audio.

### 6.3 Voiceover (local, free, commercially safe)

Use **Kokoro** — 82M params, Apache-2.0 licensed, fast on CPU, good quality. The license matters: XTTS-v2 sounds great and clones voices, but its model license is **non-commercial only**, so avoid it if this ever becomes a product. Kokoro keeps you clear.

### 6.4 Visuals — the real constraint

You have three options, in increasing risk/effort:

- **Text + motion graphics** (safest): animated typography, the character's name, fact cards over thematic color backgrounds. No likeness use. Ships fastest.
- **Wiki images via API**: many Fandom/Wikipedia images are non-free (fair-use comic art). Pulling them into your own reels is a copyright problem (see §8). Filter to genuinely free-licensed media only.
- **AI-generated visuals**: generate original art evoking the theme. Note that generating recognizable Marvel/DC characters reproduces protected IP.

For a first build I recommend motion-graphics reels — they prove the pipeline end-to-end without the IP minefield.

### 6.5 Assembly

**MoviePy 2.x** (Python-native, drives ffmpeg under the hood) for composition: layer audio, image/video clips, and animated captions, export 1080×1920 H.264. Drop to raw **ffmpeg** for any step where MoviePy is slow on large files.

---

## 7. Repository layout

```
marvel-dc-rag/
├── README.md
├── pyproject.toml
├── config.yaml                 # sources, models, rate limits, paths
├── data/
│   ├── raw/                    # JSONL per source (gitignored)
│   ├── catalog.sqlite
│   └── chroma/                 # persistent vector store
├── src/
│   ├── ingest/
│   │   ├── discover.py         # enumerate character titles
│   │   ├── fetch.py            # batched API calls, backoff, resume
│   │   └── parse.py            # extracts + infobox (mwparserfromhell)
│   ├── store/
│   │   ├── catalog.py          # SQLite read/write
│   │   ├── chunk.py
│   │   └── embed.py            # BGE → ChromaDB
│   ├── rag/
│   │   ├── retrieve.py         # search + rerank
│   │   ├── llm.py              # local/API backend switch
│   │   └── context_pack.py
│   ├── content/
│   │   ├── script.py
│   │   ├── tts.py              # Kokoro
│   │   ├── visuals.py
│   │   └── render.py           # MoviePy/ffmpeg
│   └── cli.py                  # one entry point per stage
└── tests/
```

Everything is **resumable and re-runnable per stage** via the CLI: `ingest`, `embed`, `ask`, `make-reel`.

---

## 8. Legal & licensing — read this before shipping anything public

This is the biggest non-technical risk, so it's called out separately.

- **Wiki text** (Wikipedia, Fandom) is **CC BY-SA** (Wikipedia 4.0; Fandom 3.0). You may reuse it, but you must **attribute** (link back to the source pages / contributors) and, if you publish derived text, apply **share-alike** (same license) and note your changes. Bake an attribution field into every record and into the reel description.
- **Marvel and DC characters are trademarked and copyrighted by Disney/Marvel and Warner Bros./DC.** The CC license on the wiki text does **not** grant rights to the characters themselves. Names, likenesses, logos, and comic art are protected IP.
- **Comic-art images** on these wikis are typically **non-free / fair-use** uploads, not freely licensed. Republishing them in your own videos is a copyright exposure. Filter to free-licensed media only, or avoid wiki images.
- **Commercial use raises the stakes.** Personal/educational/research use is lower-risk; monetized reels using protected characters invite takedowns or worse. If this becomes a product, get actual legal advice.

I'm not a lawyer and this isn't legal advice — it's the set of facts you'd want before deciding how public this goes.

---

## 9. Phased roadmap

| Phase | Goal | Deliverable | Rough effort |
|-------|------|-------------|--------------|
| **0. Scaffold** | Repo, config, CLI skeleton, deps | Runnable empty pipeline | 0.5 day |
| **1. Ingest (pilot)** | Fetch ~50 top characters from all 3 sources, with backoff + resume | `data/raw/*.jsonl` | 1–2 days |
| **2. Store + embed** | Chunk, embed (BGE), load ChromaDB; SQLite catalog | Queryable vector store | 1 day |
| **3. RAG** | Retrieve + rerank + LLM answer; context-pack generator | `ask` and context-pack working | 1–2 days |
| **4. Content** | Script → Kokoro TTS → motion-graphics reel → MP4 | First 30s reel | 2–3 days |
| **5. Scale ingest** | Full category-tree crawl of all Marvel/DC characters, incremental re-sync | Complete corpus (tens of thousands) | Runtime-bound (hours–days of crawling) |
| **6. Quality + polish** | Reranker tuning, better visuals, batch reel generation, eval harness | Production-ish pipeline | ongoing |

Build phases 0–4 on a **small sample first** (validate the whole loop), then turn on the full crawl in phase 5. Scraping everything before the pipeline works would waste hours of crawl time on an unproven design.

---

## 10. Key decisions locked / open

**Locked (from your answers):**
- Output: full vertical video reels (~30s)
- Stack: local + free (ChromaDB, sentence-transformers/BGE, Kokoro)
- Scope: all Marvel + DC characters (phase 5)
- This document first, before code

**Open — worth deciding before Phase 4:**
- Generation LLM: start local (Ollama) or go straight to an API for script quality?
- Visuals: motion-graphics only (recommended first), or invest in AI-generated art?
- Will any of this be public/monetized? (Changes the §8 calculus and the visuals choice.)

---

## 11. Recommended next step

Approve this design, then I scaffold the repo (Phase 0) and build the **ingest + store + RAG loop on ~50 characters** so you see real retrieval working before committing to the full crawl. Say the word and I'll start on Phase 0–1.
