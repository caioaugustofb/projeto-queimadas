"""Teste ponta a ponta da Bronze contra um servidor HTTP local (sem internet).

Rodar na raiz do repositório:  python -m unittest discover -s tests -v

O servidor simula: ZIP anual em latin-1 com linha malformada, ZIP corrompido, 404,
503 transitório (retry), arquivo diário do dia corrente ainda incompleto, API do
IBGE com período indisponível e resposta inválida. Usa BRONZE_FORMAT="csv" porque
o teste não depende do pyarrow; a lógica é a mesma do Parquet.
"""
from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src import config
from src.common import checks, http, metadata, storage
from src.common.state import StateStore
from src.ingestion import run_bronze

DAILY_HEADER = ("id,lat,lon,data_hora_gmt,satelite,municipio,estado,pais,municipio_id,estado_id,"
                "pais_id,numero_dias_sem_chuva,precipitacao,risco_fogo,bioma,frp\n")


def http_date(y: int, m: int, d: int, hh: int, mm: int) -> str:
    return format_datetime(datetime(y, m, d, hh, mm, tzinfo=timezone.utc), usegmt=True)


def daily_csv(day: date, n: int = 2) -> bytes:
    rows = "".join(
        f"{day:%Y%m%d}-{i},  -3.1000, -54.2000,{day} 12:0{i}:00,GOES-19,ALTAMIRA,PARÁ,Brasil,"
        f"1500602,15,33,,,,Amazônia,{40 + i}.5\n" for i in range(n))
    return (DAILY_HEADER + rows).encode("utf-8")


def make_zip(name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    routes: dict = {}
    hits: dict = {}

    def log_message(self, *args):  # silencioso
        pass

    def _serve(self, send_body: bool) -> None:
        route = self.routes.get(self.path)
        if send_body:
            self.hits[self.path] = self.hits.get(self.path, 0) + 1
        if route is None:
            self.send_response(404); self.end_headers(); return
        if send_body and self.hits[self.path] <= route.get("fail_first", 0):
            self.send_response(503); self.end_headers(); return
        if route.get("always_503"):
            self.send_response(503); self.end_headers(); return
        body = route["body"]
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        if route.get("last_modified"):
            self.send_header("Last-Modified", route["last_modified"])
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def do_GET(self): self._serve(True)
    def do_HEAD(self): self._serve(False)


class BronzeOfflineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        cfg = {
            "RAW_DIR": root / "raw", "BRONZE_DIR": root / "bronze", "QUARANTINE_DIR": root / "quar",
            "STATE_FILE": root / "state.json", "BRONZE_FORMAT": "csv", "HTTP_BACKOFF_BASE": 0.01,
            "IBGE_PAUSA_SEGUNDOS": 0, "HTTP_MAX_ATTEMPTS": 4,
            "INPE_BASE_URL": self.base + "/inpe", "INPE_ANUAL_ANOS": range(2013, 2016),
            "IBGE_LOCALIDADES_URL": self.base + "/ibge/localidades",
            "IBGE_AGREGADOS_URL": self.base + "/ibge/agregados",
            "IBGE_SIDRA_URL": self.base + "/ibge/sidra",
            "IBGE_TABELAS": {"populacao": {"tabela": 6579, "variavel": "9324",
                                           "classificacao": None, "anos": range(2013, 2016)}},
        }
        self._old = {k: getattr(config, k) for k in cfg}
        for k, v in cfg.items():
            setattr(config, k, v)
        Handler.hits = {}
        Handler.routes = self.build_routes()

    def tearDown(self):
        for k, v in self._old.items():
            setattr(config, k, v)
        self.tmp.cleanup()

    # ----------------------------------------------------------- fixtures --
    def build_routes(self) -> dict:
        r: dict = {}
        annual = ("DataHora;Satelite;Municipio\n2013-01-01 10:00:00;AQUA_M-T;SÃO FÉLIX DO XINGU\n"
                  "2013-01-02 10:00:00;AQUA_M-T;ALTAMIRA\nlinha;com;campos;demais\n")
        r["/inpe/anual/Brasil_sat_ref/focos_br_ref_2013.zip"] = {
            "body": make_zip("focos_br_ref_2013.csv", annual.encode("latin-1")),
            "last_modified": http_date(2023, 8, 9, 12, 28)}
        r["/inpe/anual/Brasil_sat_ref/focos_br_ref_2015.zip"] = {
            "body": b"isto nao e um zip", "last_modified": http_date(2023, 8, 9, 12, 28)}
        # 2014 não existe -> 404
        r["/inpe/mensal/Brasil/focos_mensal_br_202601.csv"] = {
            "body": daily_csv(date(2026, 1, 15), 3), "last_modified": http_date(2026, 7, 17, 11, 51)}
        # 202602 não existe -> 404
        days = [date(2026, 3, 1) + timedelta(days=i) for i in range(10)]  # 01..10/03
        links = "".join(f'<a href="focos_diario_br_{d:%Y%m%d}.csv">x</a>\n' for d in days)
        r["/inpe/diario/Brasil/"] = {"body": f"<html>{links}</html>".encode()}
        for d in days:
            partial = d == date(2026, 3, 10)
            r[f"/inpe/diario/Brasil/focos_diario_br_{d:%Y%m%d}.csv"] = {
                "body": daily_csv(d),
                "last_modified": http_date(d.year, d.month, d.day, 17, 6) if partial else
                http_date(d.year, d.month, d.day + 1, 9, 5),
                "fail_first": 1 if d == date(2026, 3, 5) else 0}
        muni = [{"id": 1500107 + i, "nome": f"M{i}", "microrregiao": {"id": 1, "nome": "X"}} for i in range(3)]
        r["/ibge/localidades/estados/15/municipios"] = {"body": json.dumps(muni).encode()}
        r["/ibge/agregados/6579/periodos"] = {
            "body": json.dumps([{"id": "2013"}, {"id": "2014"}]).encode()}
        header = {"NC": "Nível Territorial (Código)", "MC": "Município (Código)", "V": "Valor"}
        rows = [{"NC": "6", "MC": "1500107", "V": "1000"}, {"NC": "6", "MC": "1500131", "V": "-"}]
        r["/ibge/sidra/t/6579/n6/in%20n3%2015/v/9324/p/2013"] = {"body": json.dumps([header] + rows).encode()}
        r["/ibge/sidra/t/6579/n6/in%20n3%2015/v/9324/p/2014"] = {"body": json.dumps({"erro": "x"}).encode()}
        return r

    def run_all(self, today: str = "2026-03-10") -> int:
        return run_bronze.main(["--fonte", "todas", "--hoje", today])

    def bronze(self, dataset: str):
        return storage.read_bronze(dataset)

    def quarantine_reasons(self, dataset: str) -> list[str]:
        out = []
        for f in (Path(config.QUARANTINE_DIR) / dataset).glob("*.jsonl"):
            out += [json.loads(line)["reason"] for line in f.read_text(encoding="utf-8").splitlines()]
        return out

    # -------------------------------------------------------------- testes --
    def test_primeira_carga(self):
        self.assertEqual(self.run_all(), 0)

        anual = self.bronze("inpe_focos_anual")
        self.assertEqual(len(anual), 2)  # 2 válidas; a linha malformada foi para a quarentena
        self.assertIn("SÃO FÉLIX DO XINGU", set(anual["Municipio"]))  # latin-1 decodificado
        checks.check_bronze_metadata(anual)
        reasons = self.quarantine_reasons("inpe_focos_anual")
        for expected in ("linha_malformada", "http_error", "zip_invalido"):
            self.assertIn(expected, reasons)

        mensal = self.bronze("inpe_focos_mensal")
        self.assertEqual(len(mensal), 3)
        self.assertEqual(mensal["lat"].iloc[0], "  -3.1000")  # espaços preservados (Bronze = como veio)
        self.assertIn("http_error", self.quarantine_reasons("inpe_focos_mensal"))  # fev/2026 = 404

        diario = self.bronze("inpe_focos_diario")
        self.assertEqual(len(diario), 18)  # dias 01..09; o dia 10 estava incompleto
        self.assertNotIn("2026-03-10", set(diario["data_hora_gmt"].str[:10]))
        self.assertEqual(StateStore().get_checkpoint("inpe_focos_diario")["last_date"], "2026-03-09")
        self.assertEqual(Handler.hits["/inpe/diario/Brasil/focos_diario_br_20260305.csv"], 2)  # 503 + retry
        checks.check_bronze_metadata(diario)

        pop = self.bronze("ibge_populacao")
        self.assertEqual(len(pop), 2)
        self.assertEqual(set(pop["V"]), {"1000", "-"})  # símbolo especial preservado
        sidecars = list((Path(config.BRONZE_DIR) / "ibge_populacao").glob("*/*/_header.json"))
        self.assertEqual(len(sidecars), 1)
        self.assertEqual(len(self.bronze("ibge_municipios_pa")), 3)
        reasons = self.quarantine_reasons("ibge_populacao")
        self.assertIn("resposta_invalida", reasons)
        self.assertIn("periodo_indisponivel", reasons)

    def test_idempotencia_rodar_duas_vezes(self):
        self.run_all()
        datasets = ["inpe_focos_anual", "inpe_focos_mensal", "inpe_focos_diario",
                    "ibge_municipios_pa", "ibge_populacao", "ibge_periodos"]
        before = {d: checks.summarize_bronze(self.bronze(d)) for d in datasets}
        state_before = StateStore()._data["manifest"].copy()

        self.assertEqual(self.run_all(), 0)

        for d in datasets:
            after = checks.summarize_bronze(self.bronze(d))
            self.assertTrue(before[d].equals(after), f"{d} mudou na segunda rodada")
            self.assertTrue((after["cargas"] == 1).all(), f"{d} tem objeto com mais de uma carga")
        sha = lambda m: {k: v.get("sha256") for k, v in m.items()}
        self.assertEqual(sha(state_before), sha(StateStore()._data["manifest"]))

    def test_incremental_so_baixa_o_dia_novo(self):
        self.run_all("2026-03-10")
        # No dia 11 o INPE regrava o arquivo do dia 10 (agora completo) e cria o dia 11 (parcial).
        d10, d11 = date(2026, 3, 10), date(2026, 3, 11)
        Handler.routes[f"/inpe/diario/Brasil/focos_diario_br_{d10:%Y%m%d}.csv"]["last_modified"] = \
            http_date(2026, 3, 11, 9, 5)
        Handler.routes[f"/inpe/diario/Brasil/focos_diario_br_{d11:%Y%m%d}.csv"] = {
            "body": daily_csv(d11), "last_modified": http_date(2026, 3, 11, 8, 0)}
        Handler.routes["/inpe/diario/Brasil/"]["body"] = Handler.routes["/inpe/diario/Brasil/"]["body"].replace(
            b"</html>", b'<a href="focos_diario_br_20260311.csv">x</a></html>')
        Handler.hits = {}

        self.run_all("2026-03-11")

        self.assertEqual(len(self.bronze("inpe_focos_diario")), 20)  # 18 + só o dia 10
        self.assertEqual(StateStore().get_checkpoint("inpe_focos_diario")["last_date"], "2026-03-10")
        self.assertNotIn("/inpe/diario/Brasil/focos_diario_br_20260301.csv", Handler.hits)  # nem baixou de novo

    def test_hash_do_registro_e_estavel(self):
        import pandas as pd
        a = pd.DataFrame({"x": ["1", "2"], "y": ["a", "b"]})
        b = a[["y", "x"]]
        self.assertEqual(metadata.compute_record_hashes(a), metadata.compute_record_hashes(b))
        self.assertNotEqual(*metadata.compute_record_hashes(a))

    def test_retry_e_erros_sem_retry(self):
        Handler.routes["/flaky"] = {"body": b"ok", "fail_first": 2}
        Handler.routes["/down"] = {"body": b"", "always_503": True}
        self.assertEqual(http.get_bytes(self.base + "/flaky"), b"ok")
        self.assertEqual(Handler.hits["/flaky"], 3)
        with self.assertRaises(http.HttpError):
            http.get_bytes(self.base + "/down")
        self.assertEqual(Handler.hits["/down"], config.HTTP_MAX_ATTEMPTS)
        with self.assertRaises(http.HttpError) as ctx:
            http.get_bytes(self.base + "/nao-existe")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(Handler.hits["/nao-existe"], 1)  # 404 não é repetido

    def test_arquivo_vazio_e_so_cabecalho_nao_quebram(self):
        Handler.routes["/inpe/anual/Brasil_sat_ref/focos_br_ref_2014.zip"] = {
            "body": make_zip("vazio.csv", b"")}
        self.assertEqual(self.run_all(), 0)
        self.assertIn("arquivo_vazio", self.quarantine_reasons("inpe_focos_anual"))


if __name__ == "__main__":
    unittest.main()
