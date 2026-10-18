"""Estado persistente da ingestão: manifest (o que já foi carregado) e checkpoints.

- manifest[chave]: o que sabemos sobre cada objeto de origem já processado
  (hash do arquivo, linhas, carga, status). É o que torna a rodada idempotente.
- checkpoints[nome]: "marcador de página" das fontes incrementais.

O arquivo é gravado de forma atômica (escreve em .tmp e renomeia), então uma
queda no meio da gravação nunca deixa o estado corrompido.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from src import config

log = logging.getLogger(__name__)


class StateStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else Path(config.STATE_FILE)
        self._data = self._load()

    # ------------------------------------------------------------------ io --
    def _empty(self) -> dict[str, Any]:
        return {"version": 1, "manifest": {}, "checkpoints": {}}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("manifest", {})
            data.setdefault("checkpoints", {})
            return data
        except (json.JSONDecodeError, OSError) as exc:
            backup = self.path.with_name(f"{self.path.name}.corrompido-{int(time.time())}")
            os.replace(self.path, backup)
            log.error("Estado ilegível (%s). Guardado em %s; começando do zero.", exc, backup)
            return self._empty()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    # ------------------------------------------------------------ manifest --
    def get_manifest(self, key: str) -> dict[str, Any] | None:
        return self._data["manifest"].get(key)

    def set_manifest(self, key: str, entry: dict[str, Any]) -> None:
        self._data["manifest"][key] = entry
        self._save()

    # --------------------------------------------------------- checkpoints --
    def get_checkpoint(self, name: str) -> dict[str, Any] | None:
        return self._data["checkpoints"].get(name)

    def set_checkpoint(self, name: str, value: dict[str, Any]) -> None:
        self._data["checkpoints"][name] = value
        self._save()
