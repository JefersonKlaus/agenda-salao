"""Repositório no DynamoDB, uma tabela só.

PK = SALAO#<dono>   SK = SERV#id | PROF#id | CONF | AGE#<id do agendamento> | TRAVA#<bloco>
O item guarda o objeto inteiro em JSON no atributo `dados`. O `dono` vem sempre do token
de login, nunca do que o navegador envia: é isso que separa os dados de cada salão.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .dominio import MODELOS, Agendamento, Configuracao
from .erros import ConflitoHorario
from .horarios import chaves_das_travas

PREFIXOS = {"servico": "SERV#", "profissional": "PROF#"}


class RepositorioDynamo:
    def __init__(self, cliente: Any, tabela: str) -> None:
        self.cliente, self.tabela = cliente, tabela

    # -------------------------------------------------------------- baixo nível
    @staticmethod
    def _pk(dono: str) -> dict[str, str]:
        return {"S": f"SALAO#{dono}"}

    def _chave(self, dono: str, sk: str) -> dict[str, Any]:
        return {"PK": self._pk(dono), "SK": {"S": sk}}

    def _item(self, dono: str, sk: str, objeto: Any) -> dict[str, Any]:
        return {**self._chave(dono, sk), "dados": {"S": json.dumps(objeto, ensure_ascii=False)}}

    def _ler(self, dono: str, sk: str) -> Optional[dict[str, Any]]:
        resposta = self.cliente.get_item(TableName=self.tabela, Key=self._chave(dono, sk),
                                         ConsistentRead=True)
        item = resposta.get("Item")
        return json.loads(item["dados"]["S"]) if item else None

    def _buscar(self, dono: str, prefixo: str) -> list[dict[str, Any]]:
        itens, inicio = [], None
        while True:
            pedido = {"TableName": self.tabela, "ConsistentRead": True,
                      "KeyConditionExpression": "PK = :pk AND begins_with(SK, :p)",
                      "ExpressionAttributeValues": {":pk": self._pk(dono), ":p": {"S": prefixo}}}
            if inicio:
                pedido["ExclusiveStartKey"] = inicio
            resposta = self.cliente.query(**pedido)
            itens += [json.loads(i["dados"]["S"]) for i in resposta.get("Items", [])]
            inicio = resposta.get("LastEvaluatedKey")
            if not inicio:
                return itens

    # -------------------------------------------------------------- serviços e profissionais
    def listar(self, dono: str, tipo: str) -> list[Any]:
        return [MODELOS[tipo].de_dict(d) for d in self._buscar(dono, PREFIXOS[tipo])]

    def obter(self, dono: str, tipo: str, id: str) -> Optional[Any]:
        dados = self._ler(dono, PREFIXOS[tipo] + id)
        return MODELOS[tipo].de_dict(dados) if dados else None

    def salvar(self, dono: str, tipo: str, item: Any) -> None:
        self.cliente.put_item(TableName=self.tabela,
                              Item=self._item(dono, PREFIXOS[tipo] + item.id, item.para_dict()))

    def excluir(self, dono: str, tipo: str, id: str) -> None:
        self.cliente.delete_item(TableName=self.tabela, Key=self._chave(dono, PREFIXOS[tipo] + id))

    def obter_configuracao(self, dono: str) -> Optional[Configuracao]:
        dados = self._ler(dono, "CONF")
        return Configuracao.de_dict(dados) if dados else None

    def salvar_configuracao(self, dono: str, config: Configuracao) -> None:
        self.cliente.put_item(TableName=self.tabela,
                              Item=self._item(dono, "CONF", config.para_dict()))

    # -------------------------------------------------------------- agendamentos
    def agendamentos_do_dia(self, dono: str, data: str) -> list[Agendamento]:
        return [Agendamento.de_dict(d) for d in self._buscar(dono, f"AGE#{data}_")]

    def obter_agendamento(self, dono: str, id: str) -> Optional[Agendamento]:
        dados = self._ler(dono, f"AGE#{id}")
        return Agendamento.de_dict(dados) if dados else None

    def criar_agendamento(self, dono: str, ag: Agendamento) -> None:
        """Grava o agendamento e uma trava por bloco de 15 min numa transação só.
        Se qualquer trava já existir, nada é gravado e o horário é recusado."""
        nao_existe = "attribute_not_exists(PK)"
        operacoes = [{"Put": {"TableName": self.tabela, "ConditionExpression": nao_existe,
                              "Item": self._item(dono, f"AGE#{ag.id}", ag.para_dict())}}]
        for chave in chaves_das_travas(ag.profissional_id, ag.data, ag.inicio_min, ag.duracao_min):
            operacoes.append({"Put": {"TableName": self.tabela, "ConditionExpression": nao_existe,
                                      "Item": self._item(dono, f"TRAVA#{chave}", {"ag": ag.id})}})
        try:
            self.cliente.transact_write_items(TransactItems=operacoes)
        except Exception as erro:       # botocore.ClientError, sem importar botocore aqui
            if _foi_condicao_falsa(erro):
                raise ConflitoHorario("esse horário acabou de ser ocupado") from None
            raise

    def cancelar_agendamento(self, dono: str, id: str) -> Optional[Agendamento]:
        ag = self.obter_agendamento(dono, id)
        if ag is None:
            return None
        operacoes = [{"Delete": {"TableName": self.tabela, "Key": self._chave(dono, f"AGE#{id}")}}]
        for chave in chaves_das_travas(ag.profissional_id, ag.data, ag.inicio_min, ag.duracao_min):
            operacoes.append({"Delete": {"TableName": self.tabela,
                                         "Key": self._chave(dono, f"TRAVA#{chave}")}})
        self.cliente.transact_write_items(TransactItems=operacoes)
        return ag


def _foi_condicao_falsa(erro: Exception) -> bool:
    resposta = getattr(erro, "response", None) or {}
    if resposta.get("Error", {}).get("Code") != "TransactionCanceledException":
        return False
    return any(r.get("Code") == "ConditionalCheckFailed"
               for r in resposta.get("CancellationReasons", []))
