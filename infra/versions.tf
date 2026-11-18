terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
  }

  # O estado fica num bucket S3 criado à mão uma vez (veja o README).
  # Os valores entram em `terraform init -backend-config=...`, por isso o bloco está vazio.
  backend "s3" {}
}

provider "aws" {
  region = var.regiao

  default_tags {
    tags = {
      Projeto  = var.nome
      Ambiente = var.ambiente
    }
  }
}

data "aws_caller_identity" "atual" {}
