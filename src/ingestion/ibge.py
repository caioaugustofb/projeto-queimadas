"""Ingestão da API do IBGE (passo 6): municípios do Pará, população, rebanho e PIB.

- "Paginação": a API do SIDRA devolve tudo de uma vez, então paginamos por
  tabela x ano (uma requisição por ano, 144 municípios cada).
- Retry com backoff vem de src.common.http.
- Idempotência: toda resposta é comparada (SHA-256 do corpo) com a da rodada
  anterior; igual => não grava de novo. Se o IBGE revisar um número, grava
  uma nova versão (a Silver escolhe a vigente).
- Respostas inválidas (200 com erro no corpo, lista vazia) vão para a quarentena.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import pandas as pd

from src import config
from src.common import http, metadata, quarantine, storage
from src.common.state import StateStore

log = logging.getLogger(__name__)
DS_MUNICIPIOS, DS_PERIODOS = "ibge_municipios_pa", "ibge_periodos"


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def records_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Lista de dicts -> DataFrame só de texto (aninhados viram JSON em string)."""
    return pd.DataFrame([{str(k): _to_str(v) for k, v in rec.items()} for rec in records]).fillna("")


def _parse_list(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(payload, list) or not payload or not all(isinstance(r, dict) for r in payload):
        raise ValueError("resposta não é uma lista não vazia de objetos")
    return payload, {}


def _parse_sidra(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """O SIDRA devolve [cabeçalho, linha, linha, ...]. O cabeçalho vai para _header.json."""
    if (not isinstance(payload, list) or len(payload) < 2
            or not all(isinstance(r, dict) for r in payload)):
        raise ValueError("resposta do SIDRA sem registros de dados")
    return payload[1:], {"_header.json": payload[0]}


def _ingest_json(state: StateStore, load_id: str, dataset: str, url: str,
                 parse: Callable[[Any], tuple[list[dict[str, Any]], dict[str, Any]]]) -> dict[str, Any]:
    out = {"dataset": dataset, "source_object": url, "payload": None}
    try:
        body = http.get_bytes(url)
    except http.HttpError as exc:
        quarantine.quarantine_file(dataset, url, load_id, "http_error", str(exc))
        return {**out, "status": "quarantined", "rows": 0, "detail": str(exc)}
    try:
        payload = json.loads(body.decode("utf-8"))
        records, sidecars = parse(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        quarantine.quarantine_file(dataset, url, load_id, "resposta_invalida",
                                   f"{exc}; início do corpo: {body[:300]!r}")
        return {**out, "status": "quarantined", "rows": 0, "detail": f"resposta inválida: {exc}"}

    sha = metadata.sha256_bytes(body)
    entry = state.get_manifest(url)
    if entry and entry.get("status") == "ok" and entry.get("sha256") == sha:
        return {**out, "status": "skipped", "rows": 0, "payload": payload,
                "detail": "resposta idêntica à da rodada anterior"}

    df = metadata.add_metadata(records_to_dataframe(records), source_system=config.IBGE_SOURCE_SYSTEM,
                               source_object=url, load_id=load_id)
    stats = storage.write_bronze_chunks(dataset, url, load_id, [df], sidecars=sidecars)
    state.set_manifest(url, {"status": "ok", "sha256": sha, "rows": stats["rows"], "load_id": load_id,
                             "ingested_at": metadata.utc_now_iso(), "bronze_path": stats["path"]})
    return {**out, "status": "ok", "rows": stats["rows"], "payload": payload}


def ingest_municipios(state: StateStore, load_id: str) -> dict[str, Any]:
    url = f"{config.IBGE_LOCALIDADES_URL}/estados/{config.IBGE_UF_PARA}/municipios"
    res = _ingest_json(state, load_id, DS_MUNICIPIOS, url, _parse_list)
    payload = res["payload"]
    if isinstance(payload, list) and len(payload) != config.IBGE_MUNICIPIOS_ESPERADOS:
        log.warning("Esperados %d municípios do Pará, a API devolveu %d.",
                    config.IBGE_MUNICIPIOS_ESPERADOS, len(payload))
    return res


def _available_periods(state: StateStore, load_id: str, tabela: int) -> set[str] | None:
    url = f"{config.IBGE_AGREGADOS_URL}/{tabela}/periodos"
    res = _ingest_json(state, load_id, DS_PERIODOS, url, _parse_list)
    if isinstance(res["payload"], list):
        return {str(p.get("id")) for p in res["payload"] if isinstance(p, dict)}
    return None


def _sidra_url(spec: dict[str, Any], ano: int) -> str:
    url = (f"{config.IBGE_SIDRA_URL}/t/{spec['tabela']}/n6/in%20n3%20{config.IBGE_UF_PARA}"
           f"/v/{spec['variavel']}/p/{ano}")
    return f"{url}/{spec['classificacao']}" if spec.get("classificacao") else url


def ingest_tabela(state: StateStore, load_id: str, nome: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    dataset = f"ibge_{nome}"
    available = _available_periods(state, load_id, spec["tabela"])
    results = []
    for ano in spec["anos"]:
        url = _sidra_url(spec, ano)
        if available is not None and str(ano) not in available:
            quarantine.quarantine_file(dataset, url, load_id, "periodo_indisponivel",
                                       f"tabela {spec['tabela']} não tem o período {ano}")
            results.append({"dataset": dataset, "source_object": url, "status": "skipped",
                            "rows": 0, "detail": f"período {ano} não publicado"})
            continue
        res = _ingest_json(state, load_id, dataset, url, _parse_sidra)
        res.pop("payload", None)
        results.append(res)
        time.sleep(config.IBGE_PAUSA_SEGUNDOS)
    return results


def ingest_all(state: StateStore, load_id: str) -> list[dict[str, Any]]:
    results = [ingest_municipios(state, load_id)]
    for nome, spec in config.IBGE_TABELAS.items():
        results.extend(ingest_tabela(state, load_id, nome, spec))
    for res in results:
        res.pop("payload", None)
    return results
