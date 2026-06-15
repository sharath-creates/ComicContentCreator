# Marvel & DC — Phase 1: Extraction

Scrapes every Marvel and DC character page from Wikipedia, the Marvel Database
(Fandom), and the DC Database (Fandom) via their MediaWiki APIs, and stores the
results locally as JSONL. This is the first of three phases:

1. **Extract** (this repo) → local JSONL
2. Ingest into a storage layer (chunk + embed + index)
3. Build the RAG layer

## Install

Python 3.9+ recommended.

```bash
pip install -r requirements.txt
```

## Configure

Open `config.yaml` and set `contact` to your email (MediaWiki policy asks bots
to identify themselves). Defaults for rate limits and category roots are sane;
tune `request_delay_seconds` up if you ever get throttled.

## Run

```bash
# Everything, all three sources (discover then fetch), resumable:
python scrape.py run -v

# Or one source at a time:
python scrape.py run --source wikipedia_en -v
python scrape.py run --source marvel_fandom -v
python scrape.py run --source dc_fandom -v

# Steps separately:
python scrape.py discover --source marvel_fandom -v
python scrape.py fetch    --source marvel_fandom -v

# See what's on disk:
python scrape.py status
```

`-v` turns on progress logging. Drop it for quiet mode.

## Resuming

The fetch step is **append-only and resumable**. Each written page's id goes
into `<source>.done.txt`; rerunning `fetch` skips anything already done. If the
crawl dies at character 40,000, just run the same command again — it picks up
where it left off. Re-running `discover` refreshes the candidate list.

## Output

Under `data/raw/` per source:

| File | Contents |
|------|----------|
| `<source>.titles.jsonl` | discovered candidate pages (`pageid`, `title`) |
| `<source>.pages.jsonl`  | one character record per line (the corpus) |
| `<source>.done.txt`     | resume marker (fetched pageids) |

Each record:

```json
{
  "id": "marvel_fandom:12345",
  "pageid": 12345,
  "source": "marvel_fandom",
  "title": "Spider-Man (Peter Parker)",
  "url": "https://marvel.fandom.com/wiki/Spider-Man_(Peter_Parker)",
  "revid": 6543210,
  "text": "Peter Benjamin Parker was ...",
  "infobox": {"real name": "Peter Parker", "alignment": "Good", "...": "..."},
  "categories": ["Category:Heroes", "Category:Avengers members"],
  "wikibase_item": "Q79037",
  "license": "CC BY-SA 3.0"
}
```

`data/raw/` is the immutable source of truth. Phase 2 reads from it — you never
re-scrape just to re-chunk or re-embed.

## Phase 2 — ingest into the vector store

Chunks each character record, embeds the chunks with a local BGE model, and
indexes them into a persistent ChromaDB collection. A SQLite catalog tracks what
is indexed.

```bash
pip install -r requirements.txt        # adds chromadb + sentence-transformers

python ingest.py index -v              # chunk + embed + index all sources
python ingest.py status                # indexed characters / chunks per source
python ingest.py query "who is Venom?" -k 5
python ingest.py query "Gotham vigilante" --source dc_fandom
```

The first `index` run downloads the embedding model (`BAAI/bge-large-en-v1.5`
by default; change `storage.embed_model` in `config.yaml`, e.g. to
`BAAI/bge-m3`). With no GPU it runs on CPU; set `storage.device: cuda` if you
have one.

Indexing is **resumable**: a character whose revision is already in the catalog
is skipped, so re-running only processes new or changed pages. Outputs:

| Path | Contents |
|------|----------|
| `data/chroma/` | ChromaDB collection `comics` (chunk vectors + metadata) |
| `data/catalog.sqlite` | per-character provenance and chunk counts |

Each chunk carries metadata (`character`, `source`, `url`, `chunk_index`) so the
Phase 3 RAG layer can filter before searching and cite sources after.

## Scope notes

- **Marvel/DC Fandom** databases auto-categorize every character under
  `Category:Characters`, so `max_depth: 0` already captures essentially all of
  them (tens of thousands each, including alternate-universe versions like
  Earth-616). Expect a long crawl.
- **Wikipedia** only covers notable characters and uses messy category trees, so
  it walks sub-categories to `max_depth: 2`. Far smaller, cleaner corpus.
- Raw text on all three is **CC BY-SA**; reuse requires attribution. The
  characters themselves are Marvel/DC trademarked IP — see the project
  `ARCHITECTURE.md` §8 before publishing anything.

## How it works

```
scrape.py  ──▶ mdrag.pipeline ──▶ discover.py  (walk category tree)
                               └─▶ fetch.py     (batch 50 pageids: extracts + wikitext + categories)
                                     └─▶ parse.py  (infobox from wikitext)
                                     └─▶ store.py  (append JSONL + checkpoint)
            mdrag.client = polite session (User-Agent, maxlag, retry/backoff)
```

The logic is covered by an offline test suite (parser, normalization,
checkpoint/resume, category paging with dedup, missing-page handling).
