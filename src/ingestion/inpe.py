"""Ingestão dos focos de calor do INPE (Programa Queimadas).

Três conjuntos, todos "arquivo":
  inpe_focos_anual   ZIPs 2013..2025 (satélite de referência)         -> passo 4
  inpe_focos_mensal  CSVs mensais de 2026 já fechados (backfill)      -> passo 5
  inpe_focos_diario  CSVs diários do mês corrente, com CHECKPOINT      -> passo 5

Por que mensal + diário: a pasta de diários só guarda ~30 dias. Os meses
fechados vêm do mensal; o mês corrente vem do diário, dia a dia.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from src import config
from src.common import http, metadata, quarantine
from src.common.state import StateStore
from src.ingestion.remote_file import ingest_remote_file

log = logging.getLogger(__name__)
DS_ANUAL, DS_MENSAL, DS_DIARIO = "inpe_focos_anual", "inpe_focos_mensal", "inpe_focos_diario"


def _url(path: str, **fmt: Any) -> str:
    return config.INPE_BASE_URL + path.format(**fmt)


def ingest_annual(state: StateStore, load_id: str) -> list[dict[str, Any]]:
    results = []
    for ano in config.INPE_ANUAL_ANOS:
        results.append(ingest_remote_file(
            state, load_id, dataset=DS_ANUAL, url=_url(config.INPE_ANUAL_PATH, ano=ano),
            source_system=config.INPE_SOURCE_SYSTEM))
    return results


def ingest_monthly(state: StateStore, load_id: str, today: date | None = None) -> list[dict[str, Any]]:
    today = today or datetime.now(timezone.utc).date()
    ano = config.INPE_INCREMENTAL_ANO
    if today.year < ano:
        return []
    last_closed = 12 if today.year > ano else today.month - 1
    return [ingest_remote_file(
        state, load_id, dataset=DS_MENSAL, url=_url(config.INPE_MENSAL_PATH, ano=ano, mes=mes),
        source_system=config.INPE_SOURCE_SYSTEM, expected_columns=config.INPE_COLUNAS_ESPERADAS)
        for mes in range(1, last_closed + 1)]


def _day_is_complete(day: date, head: dict[str, Any], today: date) -> bool:
    """O arquivo do dia D só está fechado depois que o INPE o regrava em D+1 (~09h).

    Regra: Last-Modified tem de ser POSTERIOR ao dia D. Sem Last-Modified, só
    aceitamos dias com 2+ dias de idade.
    """
    last_modified = head.get("last_modified")
    if last_modified:
        try:
            return parsedate_to_datetime(last_modified).date() > day
        except (TypeError, ValueError):
            pass
    return day <= today - timedelta(days=2)


def ingest_daily(state: StateStore, load_id: str, today: date | None = None) -> list[dict[str, Any]]:
    today = today or datetime.now(timezone.utc).date()
    ano = config.INPE_INCREMENTAL_ANO
    if today.year != ano:
        log.info("Diário só cobre %s; os meses fechados vêm do mensal.", ano)
        return []
    first_daily = date(ano, today.month, 1)
    listing_url = _url(config.INPE_DIARIO_DIR_PATH)
    try:
        listing = http.get_bytes(listing_url).decode("utf-8", errors="replace")
    except http.HttpError as exc:
        quarantine.quarantine_file(DS_DIARIO, listing_url, load_id, "http_error", str(exc))
        return [{"dataset": DS_DIARIO, "source_object": listing_url, "status": "quarantined",
                 "rows": 0, "detail": str(exc)}]

    available = {datetime.strptime(d, "%Y%m%d").date()
                 for d in re.findall(config.INPE_DIARIO_REGEX, listing)}
    checkpoint = state.get_checkpoint(DS_DIARIO)
    last = date.fromisoformat(checkpoint["last_date"]) if checkpoint else None

    # Lacunas: dias que deveriam existir (já fechados) e não estão na listagem.
    start = max(first_daily, last + timedelta(days=1)) if last else first_daily
    missing = [start + timedelta(days=i) for i in range((today - timedelta(days=2) - start).days + 1)]
    missing = [d for d in missing if d not in available]
    if missing:
        quarantine.quarantine_file(
            DS_DIARIO, listing_url, load_id, "dias_ausentes_na_listagem",
            f"{len(missing)} dia(s): {missing[0]}..{missing[-1]}. "
            f"A pasta guarda ~30 dias; se rodar a ingestão com menos frequência, perde dias.")

    results: list[dict[str, Any]] = []
    for day in sorted(d for d in available if start <= d <= today):
        url = _url(config.INPE_DIARIO_FILE_PATH, data=day.strftime("%Y%m%d"))
        try:
            head = http.head_info(url)
        except http.HttpError as exc:
            quarantine.quarantine_file(DS_DIARIO, url, load_id, "http_error", str(exc))
            results.append({"dataset": DS_DIARIO, "source_object": url, "status": "quarantined",
                            "rows": 0, "detail": str(exc)})
            continue
        if not _day_is_complete(day, head, today):
            results.append({"dataset": DS_DIARIO, "source_object": url, "status": "skipped",
                            "rows": 0, "detail": "dia ainda incompleto; fica para a próxima rodada"})
            continue
        res = ingest_remote_file(state, load_id, dataset=DS_DIARIO, url=url,
                                 source_system=config.INPE_SOURCE_SYSTEM,
                                 expected_columns=config.INPE_COLUNAS_ESPERADAS, head=head)
        results.append(res)
        if res["status"] in ("ok", "empty", "skipped") and (last is None or day > last):
            last = day
            state.set_checkpoint(DS_DIARIO, {"last_date": day.isoformat(),
                                             "updated_at": metadata.utc_now_iso(), "load_id": load_id})
    return results
