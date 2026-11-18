variable "nome" {
  description = "Nome curto do sistema, usado como prefixo dos recursos."
  type        = string
  default     = "agenda-salao"
}

variable "ambiente" {
  description = "prod, hml, dev..."
  type        = string
  default     = "prod"
}

variable "regiao" {
  type    = string
  default = "sa-east-1"
}

variable "origens_extras_cors" {
  description = "Outras origens que podem chamar a API (ex.: http://localhost:8765 em testes)."
  type        = list(string)
  default     = []
}

variable "retencao_logs_dias" {
  type    = number
  default = 14
}

variable "limite_por_segundo" {
  description = "Limite de requisições por segundo na API inteira (proteção contra abuso e custo)."
  type        = number
  default     = 20
}

variable "rajada" {
  type    = number
  default = 40
}

locals {
  prefixo = "${var.nome}-${var.ambiente}"
  conta   = data.aws_caller_identity.atual.account_id
}
