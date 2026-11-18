"""Erros de negócio. Cada um já sabe qual código HTTP representa."""


class ErroDeNegocio(Exception):
    status = 400


class ErroValidacao(ErroDeNegocio):
    status = 400


class NaoEncontrado(ErroDeNegocio):
    status = 404


class ConflitoHorario(ErroDeNegocio):
    status = 409
