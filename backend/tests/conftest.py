import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agenda.agenda import Agenda  # noqa: E402
from agenda.repositorio_dynamo import RepositorioDynamo  # noqa: E402
from agenda.repositorio_memoria import RepositorioMemoria  # noqa: E402

AGORA = datetime(2026, 11, 16, 10, 0)       # segunda-feira, 10:00
DONO = "dono-a"
OUTRO = "dono-b"


class ErroFalso(Exception):
    """Imita botocore.ClientError: tem `.response`."""

    def __init__(self, codigo, motivos=()):
        super().__init__(codigo)
        self.response = {"Error": {"Code": codigo},
                         "CancellationReasons": [{"Code": m} for m in motivos]}


class DynamoFalso:
    """Só o que o repositório usa. Transação é tudo-ou-nada, como no DynamoDB de verdade."""

    def __init__(self, pagina=2):
        self.itens, self.pagina, self.chamadas = {}, pagina, []

    @staticmethod
    def _k(chave):
        return chave["PK"]["S"], chave["SK"]["S"]

    def get_item(self, TableName, Key, ConsistentRead=False):
        item = self.itens.get(self._k(Key))
        return {"Item": item} if item else {}

    def put_item(self, TableName, Item):
        self.itens[self._k(Item)] = Item

    def delete_item(self, TableName, Key):
        self.itens.pop(self._k(Key), None)

    def query(self, TableName, KeyConditionExpression, ExpressionAttributeValues,
              ConsistentRead=False, ExclusiveStartKey=None):
        pk, prefixo = ExpressionAttributeValues[":pk"]["S"], ExpressionAttributeValues[":p"]["S"]
        achados = sorted(k for k in self.itens if k[0] == pk and k[1].startswith(prefixo))
        if ExclusiveStartKey:
            achados = [k for k in achados if k[1] > ExclusiveStartKey["SK"]["S"]]
        pagina, resto = achados[:self.pagina], achados[self.pagina:]
        resposta = {"Items": [self.itens[k] for k in pagina]}
        if resto:
            resposta["LastEvaluatedKey"] = {"PK": {"S": pk}, "SK": {"S": pagina[-1][1]}}
        return resposta

    def transact_write_items(self, TransactItems):
        self.chamadas.append(TransactItems)
        motivos = []
        for op in TransactItems:
            put = op.get("Put")
            falhou = bool(put and put.get("ConditionExpression") and self._k(put["Item"]) in self.itens)
            motivos.append("ConditionalCheckFailed" if falhou else "None")
        if "ConditionalCheckFailed" in motivos:
            raise ErroFalso("TransactionCanceledException", motivos)
        for op in TransactItems:
            if "Put" in op:
                self.put_item(**{"TableName": "t", "Item": op["Put"]["Item"]})
            else:
                self.delete_item(TableName="t", Key=op["Delete"]["Key"])


@pytest.fixture(params=["memoria", "dynamo"])
def repo(request):
    """Todo teste de regra roda nos dois repositórios: eles precisam se comportar igual."""
    return RepositorioMemoria() if request.param == "memoria" else RepositorioDynamo(DynamoFalso(), "t")


@pytest.fixture
def agenda(repo):
    return Agenda(repo, lambda: AGORA)


@pytest.fixture
def salao(agenda):
    """Um serviço de 60 min, outro de 30, e uma profissional que faz os dois."""
    corte = agenda.criar(DONO, "servico", {"nome": "Corte", "duracao_min": 60, "preco_centavos": 8000})
    unha = agenda.criar(DONO, "servico", {"nome": "Unha", "duracao_min": 30, "preco_centavos": 4000})
    ana = agenda.criar(DONO, "profissional", {"nome": "Ana", "servicos": [corte.id, unha.id]})
    return corte, unha, ana


def pedido(corte, ana, inicio="10:00", data="2026-11-17", **extra):
    return {"data": data, "inicio": inicio, "servico_id": corte.id, "profissional_id": ana.id,
            "cliente_nome": "Maria", "cliente_telefone": "(11) 98888-7777", **extra}
