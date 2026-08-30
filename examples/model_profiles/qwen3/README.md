# Qwen3 model-profile example

This directory is an illustrative model-runtime override, not a project default
or a specially supported core backend. It shows why changing a model ID may be
insufficient when a reranker needs a different architecture adapter, score-token
mapping, and chat template.

The template is copied from the Apache-2.0 licensed vLLM v0.28.0 source tree so
it stays aligned with the CPU image currently used by the example:

<https://github.com/vllm-project/vllm/blob/v0.28.0/examples/pooling/score/template/qwen3_reranker.jinja>

See [Model compatibility](../../../docs/model-compatibility.md) for the complete
checklist and commands. When using another model, create an override for that
model's documented runtime contract instead of modifying the core search code.
