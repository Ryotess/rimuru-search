# Search tuning

Rimuru Search runs four ranking stages:

1. Embed the query.
2. Retrieve vector and lexical candidates as independent branches.
3. Merge both ranked lists with Reciprocal Rank Fusion (RRF).
4. Optionally score the fused candidates with a cross-encoder reranker.

The API exposes the size and behavior of these stages so each collection can
choose its own quality/latency balance. Start with defaults, measure on real
queries, and change one stage at a time.

## Request parameters

| Parameter | Default | Range | Effect |
| --- | ---: | ---: | --- |
| `query` | required | non-empty text | Used by lexical search, the embedding model, and the reranker |
| `collection` | `default` | non-empty text | Isolates every retrieval branch to one collection |
| `document_ids` | none | list of strings | Restricts both branches to an ID allowlist; an empty list returns no hits |
| `metadata_filter` | none | JSON object | Requires stored metadata to contain the supplied JSON values |
| `vector_top_k` | `100` | `1`–`200` | ANN candidates retrieved before fusion |
| `lexical_top_k` | `100` | `1`–`200` | BM25 or FTS candidates retrieved before fusion |
| `use_fuzzy` | `false` | boolean | Adds trigram matches to the configured lexical backend |
| `min_similarity` | `0.2` | `0.0`–`1.0` | Minimum trigram similarity when fuzzy search is enabled |
| `rrf_top_k` | `15` | `1`–`100` | Fused candidates retained and passed to the reranker |
| `rerank_top_n` | `3` | `1`–`200` | Final results returned, capped by the fused candidate count |
| `bypass_cache` | `false` | boolean | Skips cache reads, runs the pipeline, and still writes the fresh result |

All request parameters participate in the cache key except `bypass_cache`, so
two requests with different tuning values do not share a cached result. The
operator-selected lexical backend also participates in the key.

## How each stage behaves

### Vector retrieval

The query embedding is compared with document embeddings using cosine distance
over a pgvector HNSW index. Smaller `vector_distance` values are better.

Increase `vector_top_k` when relevant documents use synonyms, paraphrases, or
different phrasing and are missing before fusion. Higher values increase database
work and give RRF a larger semantic candidate pool; they do not change how many
results the API ultimately returns.

`GLOBAL_HNSW_EF_SEARCH` is the corresponding server-side ANN breadth setting and
defaults to `200`. Raising it can improve approximate-search recall at the cost
of query time. Tune it separately from the request's result limit.

`GLOBAL_HNSW_ITERATIVE_SCAN` defaults to `strict_order`. This lets pgvector scan
farther when a collection, document-ID, or metadata filter removes initial HNSW
candidates, while preserving exact distance order. `relaxed_order` can improve
filtered recall and throughput with slightly relaxed ordering; `off` restores
the bounded HNSW scan and can return fewer than `vector_top_k` filtered results.

### Lexical retrieval

The default `SEARCH_LEXICAL_BACKEND=bm25` uses pg_textsearch with the `simple`
text-search configuration. BM25 uses corpus-wide term frequency, frequency
saturation, and document-length normalization to rank keyword matches. Rimuru
Search converts pg_textsearch's negative distance into a positive
`lexical_score`, so higher values are better.

The `simple` configuration is a domain-neutral default without
language-specific stemming. It works best when PostgreSQL's parser can identify
the source text's words. CJK and other languages without whitespace-delimited
tokens generally need a compatible PostgreSQL text-search parser/configuration
and rebuilt BM25/FTS indexes, or should rely more heavily on a validated
multilingual embedding model.

The `collection` predicate still isolates returned candidates. BM25 corpus
statistics come from the shared index, so documents in other collections can
influence inverse-document-frequency values without becoming visible results.

Operators can set `SEARCH_LEXICAL_BACKEND=fts` and restart the application to
use the retained PostgreSQL fallback. FTS parses queries with
`websearch_to_tsquery`, uses the same `simple` configuration, and ranks matches
with `ts_rank_cd`. The backend is deliberately not a request parameter: clients
control search intent while operators control indexes and runtime behavior.

Increase `lexical_top_k` when exact names, identifiers, or rare keywords are
present but fail to survive fusion. PostgreSQL web-search syntax—including
quoted phrases, `OR`, and `-` for NOT—applies only to the FTS fallback. The BM25
backend does not provide native phrase queries.

When `use_fuzzy=true`, a document can also enter the lexical list through
`pg_trgm` similarity. Rimuru Search fuses the configured backend and trigram
lists by rank because BM25, `ts_rank_cd`, and trigram scores use different
scales. The resulting `lexical_score` is then the internal lexical RRF score.

- Lower `min_similarity` to recover more misspellings and variations.
- Raise it when fuzzy matches introduce unrelated documents.
- Keep fuzzy matching disabled for identifiers where near-matches are dangerous.

The trigram threshold applies only when `use_fuzzy` is enabled.

### Reciprocal Rank Fusion

RRF combines rank positions instead of trying to compare vector distance with a
PostgreSQL text score. Rimuru Search uses the fixed stability constant `60`:

```text
rrf_score(document) = Σ 1 / (60 + rank_in_each_result_list)
```

A document found by both branches receives contributions from both and usually
rises above a document found by only one. `rrf_top_k` then truncates the merged
list.

Increase `rrf_top_k` when a relevant candidate appears in a retrieval branch but
is removed before reranking. This setting also determines how many query/document
pairs the cross-encoder must consider, so it is the most important reranking
latency control.

### Cross-encoder reranking

The optional reranker sees the query and each of the `rrf_top_k` fused documents
together. This is usually more precise than embedding similarity but more
expensive, which is why it runs only on the short fused list.

`rerank_top_n` controls how many scored results are returned; it does not enlarge
the retrieval or fusion pools. If reranking is disabled or temporarily
unavailable, the service returns the first `rerank_top_n` results in RRF order and
sets `rerank_score` to `null`.

Reranker scores are model-specific. Do not assume every model returns `0.0`–`1.0`
or compare raw scores across different models and queries without calibration.

## Starting profiles

These are starting points, not universal quality guarantees.

### Low-latency local profile

Useful for development on CPU or a small collection:

```json
{
  "query": "hybrid search",
  "vector_top_k": 20,
  "lexical_top_k": 20,
  "rrf_top_k": 5,
  "rerank_top_n": 3
}
```

### Balanced profile

The repository defaults favor recall before producing a small final list:

```json
{
  "query": "hybrid search",
  "vector_top_k": 100,
  "lexical_top_k": 100,
  "rrf_top_k": 15,
  "rerank_top_n": 3
}
```

### Typo-tolerant profile

Start near `0.2`, inspect false positives, and raise the threshold if needed:

```json
{
  "query": "hybird serch",
  "use_fuzzy": true,
  "min_similarity": 0.2,
  "vector_top_k": 100,
  "lexical_top_k": 100,
  "rrf_top_k": 20,
  "rerank_top_n": 5
}
```

### Recall-heavy profile

Use this when missing a relevant result is more costly than additional latency:

```json
{
  "query": "hybrid search",
  "vector_top_k": 200,
  "lexical_top_k": 200,
  "rrf_top_k": 50,
  "rerank_top_n": 10
}
```

## A practical tuning workflow

1. Collect representative queries and label at least one or more relevant
   documents for each query.
2. Send evaluation requests with `bypass_cache=true`.
3. Inspect `vector_rank` and `lexical_rank` to find which retrieval branch is
   missing relevant candidates.
4. Increase only that branch's top-k until candidate recall stops improving.
5. Increase `rrf_top_k` until relevant candidates consistently reach reranking.
6. Set `rerank_top_n` to the number of results the client actually displays or
   consumes.
7. Compare relevance metrics such as Recall@K, MRR, or NDCG together with p50 and
   p95 latency.
8. Re-run the evaluation whenever the model, document content, language mix, or
   chunking strategy changes.

Use returned scores for diagnosis rather than as universal thresholds:

- `vector_distance`: lower is better within the configured embedding model.
- `lexical_score`: higher is better, but its scale depends on the configured
  backend and whether fuzzy fusion was enabled.
- `rrf_score`: higher means stronger combined rank evidence.
- `rerank_score`: higher is better according to the configured reranker.

Vector distance, lexical rank, RRF score, and reranker score are different scales
and should not be compared directly with each other.

## Further reading

- [pg_textsearch BM25 indexing and query behavior](https://github.com/timescale/pg_textsearch)
- [PostgreSQL full-text query parsing and ranking](https://www.postgresql.org/docs/current/textsearch-controls.html)
- [PostgreSQL `pg_trgm` similarity](https://www.postgresql.org/docs/current/pgtrgm.html)
- [pgvector HNSW and hybrid-search guidance](https://github.com/pgvector/pgvector#hnsw)
- [Original Reciprocal Rank Fusion paper](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/)
- [Sentence Transformers retrieve-and-rerank guide](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)

For model-specific runtime constraints, see [Model compatibility](model-compatibility.md).
For environment defaults, see [Configuration](configuration.md).
