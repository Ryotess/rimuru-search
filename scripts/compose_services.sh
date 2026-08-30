#!/bin/sh
set -eu

# Select only the bundled services used by the effective Compose configuration.
# Docker Compose performs the .env parsing so this remains compatible with its
# interpolation rules and keeps Docker as the only requirement for `make start`.
compose_environment=$(docker compose config --environment)

lookup() {
    printf '%s\n' "$compose_environment" | awk -v key="$1" '
        index($0, key "=") == 1 {
            print substr($0, length(key) + 2)
            found = 1
            exit
        }
        END { if (!found) exit 1 }
    '
}

uses_service_host() {
    value=$1
    service=$2
    case "$value" in
        *"://$service"|*"://$service:"*|*"://$service/"*|*"@$service:"*|*"@$service/"*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

services="postgres migrate api"

if embed_api=$(lookup COMPOSE_EMBED_API_BASE); then
    if [ -z "$embed_api" ] || uses_service_host "$embed_api" embedding; then
        services="$services embedding"
    fi
else
    services="$services embedding"
fi

rerank_enabled=true
if configured=$(lookup SEARCH_ENABLE_RERANK); then
    case "$(printf '%s' "$configured" | tr '[:upper:]' '[:lower:]')" in
        false|0|no|off) rerank_enabled=false ;;
    esac
fi

if [ "$rerank_enabled" = true ]; then
    if reranker_api=$(lookup COMPOSE_RERANKER_API_BASE); then
        if [ -z "$reranker_api" ] || uses_service_host "$reranker_api" reranker; then
            services="$services reranker"
        fi
    else
        services="$services reranker"
    fi
fi

if redis_url=$(lookup COMPOSE_CACHE_REDIS_URL); then
    if [ -n "$redis_url" ] && uses_service_host "$redis_url" redis; then
        services="$services redis"
    fi
else
    services="$services redis"
fi

printf '%s\n' "$services"
