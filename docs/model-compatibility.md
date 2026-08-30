# Model compatibility

The search service is model-agnostic at its application boundaries, but models
are not interchangeable merely because they can be downloaded by the same
runtime. A replacement must satisfy the embedding or reranking API contract and
may require model-server configuration outside the FastAPI code.

The bundled model IDs are local-demo defaults, not a list of specially supported
models. Keep model-specific runtime files under `examples/model_profiles/` or in
deployment configuration owned by the user.

The bundled `mixedbread-ai/mxbai-embed-large-v1` embedding model and
`cross-encoder/ms-marco-MiniLM-L6-v2` reranker are English-oriented demo
defaults. For multilingual or domain-specific data, select and evaluate models
that cover the target language and corpus, then follow the dimension and
stored-data regeneration rules below.

## Compatibility checklist

Check these items before changing a model:

1. **API contract** — the embedding endpoint must implement the
   OpenAI-compatible `/v1/embeddings` request used by LiteLLM. A reranker must
   implement the compatible scoring/reranking request expected by the current
   adapter. Both configured model names must appear in `/v1/models`.
2. **Embedding dimension** — the bundled PostgreSQL schema stores exactly 1,024
   values. A different dimension requires an Alembic/schema change,
   `VDB_EMBEDDING_DIM` update, and regeneration of every stored embedding.
3. **Served model name** — `EMBEDDING_MODEL_ID` and `RERANKER_MODEL_ID` are the
   source and served names for bundled vLLM. Use `*_REQUEST_MODEL` only when an
   external endpoint exposes a deliberate alias.
4. **Runtime task and architecture** — confirm whether vLLM should use an
   embedding, pooling, classification, or other runner. Some checkpoints need
   Hugging Face architecture overrides or score conversion settings.
5. **Input format** — verify instruction prefixes, query/document formatting,
   pooling strategy, normalization, score tokens, and chat templates. A server
   can return valid numbers while applying the wrong model semantics.
6. **Context and resources** — choose maximum sequence length, batch/concurrency
   limits, dtype, CPU/GPU backend, memory, startup timeout, and model-cache
   storage for the selected checkpoint.
7. **Stored-data compatibility** — regenerate the complete collection whenever
   the embedding model, dimensionality, normalization, or input construction
   changes. Vectors from two embedding configurations must not be mixed.

## What normally changes

When a replacement already exposes the same API, uses 1,024-dimensional
embeddings, and needs the same vLLM runner, changing the model IDs in `.env` may
be sufficient:

```dotenv
EMBEDDING_MODEL_ID=organization/embedding-model
RERANKER_MODEL_ID=organization/reranker-model
```

Models backed by custom Hugging Face Python code also require an explicit
security opt-in:

```dotenv
RERANKER_REMOTE_CODE_FLAG=--trust-remote-code
```

Review and pin the model source before enabling this option. Bundled Compose
defaults to `--no-trust-remote-code`.

An external service additionally needs its container-reachable API base. Set a
request-model alias only when `/v1/models` reports a name different from the
source model ID:

```dotenv
COMPOSE_EMBED_API_BASE=http://host.docker.internal:9001/v1
COMPOSE_EMBED_REQUEST_MODEL=hosted_vllm/embedding-served-alias
```

When the runtime needs other CLI arguments or mounted templates, add a Compose
override or equivalent deployment configuration. Keep it outside `compose.yml`
so the core demo and other model choices remain unchanged.

## Worked example: a reranker requiring runtime adaptation

The `Qwen/Qwen3-Reranker-0.6B` checkpoint illustrates this category. With the
vLLM version pinned by this repository, the original checkpoint needs a
sequence-classification architecture override, `no`/`yes` score-token mapping,
original-model score conversion, and a score chat template. Only changing
`RERANKER_MODEL_ID` can make the endpoint run with incorrect scoring semantics.

The example is isolated under `examples/model_profiles/qwen3/`:

```bash
export EMBEDDING_MODEL_ID=Qwen/Qwen3-Embedding-0.6B
export RERANKER_MODEL_ID=Qwen/Qwen3-Reranker-0.6B
export COMPOSE_FILE=compose.yml:examples/model_profiles/qwen3/compose.override.yml

make start FILE=./documents.jsonl
make smoke-models
```

This profile is an example of the adjustment process, not a promise that Qwen3
is the preferred model. For another checkpoint, read that model's and runtime's
official documentation and create a separate override with only the required
arguments.

In one ARM64 CPU evaluation, the example embedding model used about 6.1 GiB and
needed a roughly 7 GiB container limit. This is an observed starting point, not
a portable minimum; architecture, runtime version, context length, concurrency,
and dtype all change memory consumption.

Relevant upstream references:

- <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- <https://huggingface.co/Qwen/Qwen3-Reranker-0.6B>
- <https://docs.vllm.ai/en/latest/models/pooling_models/scoring/>
- <https://github.com/vllm-project/vllm/blob/main/examples/pooling/score/qwen3_reranker_online.py>

## Validation after any model change

Run the checks in this order:

```bash
make config
docker compose config --quiet
make up
make smoke-models
```

Then import a dedicated test collection and evaluate labeled queries. At a
minimum record Top-1/Recall, MRR or NDCG, uncached latency, cached latency, and
resource usage. A successful health endpoint proves connectivity; it does not
prove retrieval or reranking quality.
