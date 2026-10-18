"""Leitura de CSV (puro ou dentro de ZIP) para a Bronze.

Decisões explícitas (exigência do projeto):
  encoding  : detectado (UTF-8, UTF-8 com BOM ou latin-1 como último recurso)
  separador : detectado no cabeçalho entre , ; | e TAB
  tipagem   : tudo texto (dtype=str, sem converter vazio em NaN). Tipos fortes só na Silver.
Linhas malformadas (campos a mais) vão para a quarentena; arquivos ilegíveis também.
"""
from __future__ import annotations

import codecs
import csv
import logging
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Iterator

import pandas as pd

from src import config
from src.common import metadata, quarantine, storage

log = logging.getLogger(__name__)


def detect_encoding(fobj: BinaryIO) -> str:
    head = fobj.read(1 << 20)
    fobj.seek(0)
    if head.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    try:
        codecs.getincrementaldecoder("utf-8")().decode(head, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def detect_delimiter(header_line: str) -> str:
    counts = {c: header_line.count(c) for c in config.CSV_DELIMITER_CANDIDATES}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _result(source_object: str, status: str, rows: int = 0, **extra: Any) -> dict[str, Any]:
    return {"source_object": source_object, "status": status, "rows": rows, **extra}


def _iter_chunks(fobj: BinaryIO, encoding: str, delimiter: str, on_bad) -> Iterator[pd.DataFrame]:
    fobj.seek(0)
    reader = pd.read_csv(
        fobj, sep=delimiter, encoding=encoding, dtype=str, keep_default_na=False,
        na_filter=False, engine="python", on_bad_lines=on_bad,
        chunksize=config.CSV_CHUNK_ROWS,
    )
    yield from reader


def _ingest_stream(fobj: BinaryIO, *, dataset: str, source_system: str, source_object: str,
                   load_id: str, ingested_at: str, expected_columns: list[str] | None) -> dict[str, Any]:
    first_line = fobj.readline()
    fobj.seek(0)
    if not first_line.strip():
        quarantine.quarantine_file(dataset, source_object, load_id, "arquivo_vazio")
        return _result(source_object, "quarantined", detail="arquivo vazio")

    stats: dict[str, Any] | None = None
    bad_total, bad_sample, columns, delimiter, encoding = 0, [], [], ",", ""
    for encoding in dict.fromkeys([detect_encoding(fobj), "latin-1"]):
        delimiter = detect_delimiter(first_line.decode(encoding, errors="replace"))
        bad_total, bad_sample, columns = 0, [], []

        def on_bad(line: list[str]) -> None:
            nonlocal bad_total
            bad_total += 1
            if len(bad_sample) < config.CSV_MAX_BAD_LINES_SAMPLE:
                bad_sample.append(line)
            return None  # None = descarta a linha da carga (ela já está na quarentena)

        def chunks() -> Iterator[pd.DataFrame]:
            for chunk in _iter_chunks(fobj, encoding, delimiter, on_bad):
                if not columns:
                    columns.extend(chunk.columns)
                yield metadata.add_metadata(chunk, source_system=source_system,
                                            source_object=source_object, load_id=load_id,
                                            ingested_at=ingested_at)
        try:
            stats = storage.write_bronze_chunks(dataset, source_object, load_id, chunks())
            break
        except UnicodeDecodeError:
            log.info("Encoding %s falhou em %s; tentando o próximo.", encoding, source_object)
        except (pd.errors.ParserError, pd.errors.EmptyDataError, csv.Error) as exc:
            quarantine.quarantine_file(dataset, source_object, load_id, "erro_de_parse", str(exc))
            return _result(source_object, "quarantined", detail=f"erro de parse: {exc}")
    if stats is None:
        quarantine.quarantine_file(dataset, source_object, load_id, "encoding_ilegivel")
        return _result(source_object, "quarantined", detail="encoding ilegível")

    if bad_total:
        quarantine.quarantine_rows(dataset, source_object, load_id, "linha_malformada",
                                   bad_sample, total=bad_total)
    missing = [c for c in (expected_columns or []) if c not in columns]
    if missing:
        log.warning("%s: colunas esperadas ausentes: %s (colunas: %s)", source_object, missing, columns)
    if stats["rows"] == 0:
        return _result(source_object, "empty", 0, columns=columns, detail="só cabeçalho")
    return _result(source_object, "ok", stats["rows"], columns=columns, encoding=encoding,
                   delimiter=delimiter, bad_lines=bad_total, missing_columns=missing,
                   bronze_path=stats["path"])


def ingest_local_file(path: Path | str, *, dataset: str, source_system: str, source_url: str,
                      load_id: str, expected_columns: list[str] | None = None) -> list[dict[str, Any]]:
    """Ingere um CSV ou ZIP já baixado. Devolve um resultado por CSV encontrado."""
    path = Path(path)
    ingested_at = metadata.utc_now_iso()
    ctx = dict(dataset=dataset, source_system=source_system, load_id=load_id,
               ingested_at=ingested_at, expected_columns=expected_columns)

    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            quarantine.quarantine_file(dataset, source_url, load_id, "zip_invalido", str(exc))
            return [_result(source_url, "quarantined", detail=f"zip inválido: {exc}")]
        with zf:
            members = [i for i in zf.infolist() if not i.is_dir()
                       and i.filename.lower().endswith(".csv") and "__MACOSX" not in i.filename]
            if not members:
                quarantine.quarantine_file(dataset, source_url, load_id, "zip_sem_csv",
                                           f"conteúdo: {zf.namelist()[:10]}")
                return [_result(source_url, "quarantined", detail="zip sem CSV")]
            results = []
            for info in members:
                with zf.open(info) as member:
                    results.append(_ingest_stream(member, source_object=f"{source_url}#{info.filename}", **ctx))
            return results

    with open(path, "rb") as fobj:
        return [_ingest_stream(fobj, source_object=source_url, **ctx)]
