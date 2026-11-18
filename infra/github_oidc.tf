# O GitHub Actions entra na AWS sem senha guardada: troca um token temporário por esta role.
locals {
  provedor_oidc_arn = "arn:aws:iam::${local.conta}:oidc-provider/token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.criar_provedor_oidc ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "deploy_confia" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.provedor_oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Só o job do ambiente "producao" deste repositório (o ambiente exige aprovação no GitHub).
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.repositorio_github}:environment:producao"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${local.prefixo}-deploy"
  assume_role_policy   = data.aws_iam_policy_document.deploy_confia.json
  max_session_duration = 3600
  depends_on           = [aws_iam_openid_connect_provider.github]
}

# Permissões do deploy limitadas ao que este projeto cria (prefixo do nome), quando a AWS permite.
data "aws_iam_policy_document" "deploy_permissoes" {
  statement {
    sid       = "Dados"
    actions   = ["dynamodb:*"]
    resources = ["arn:aws:dynamodb:*:${local.conta}:table/${local.prefixo}-*"]
  }

  statement {
    sid       = "Funcao"
    actions   = ["lambda:*"]
    resources = ["arn:aws:lambda:*:${local.conta}:function:${local.prefixo}-*"]
  }

  statement {
    sid     = "Logs"
    actions = ["logs:*"]
    resources = [
      "arn:aws:logs:*:${local.conta}:log-group:/aws/lambda/${local.prefixo}-*",
      "arn:aws:logs:*:${local.conta}:log-group:/aws/lambda/${local.prefixo}-*:*",
      "arn:aws:logs:*:${local.conta}:log-group:/aws/apigateway/${local.prefixo}",
      "arn:aws:logs:*:${local.conta}:log-group:/aws/apigateway/${local.prefixo}:*",
    ]
  }

  statement {
    sid       = "LogsLeitura"
    actions = [
      "logs:DescribeLogGroups", "logs:ListTagsForResource", "logs:TagResource",
      # o API Gateway exige estas para ligar o log de acesso do estágio
      "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "Usuarios"
    actions   = ["cognito-idp:*"]
    resources = ["arn:aws:cognito-idp:*:${local.conta}:userpool/*"]
  }

  statement {
    sid       = "ApiGateway"
    actions   = ["apigateway:*"]
    resources = ["arn:aws:apigateway:*::/*"]
  }

  statement {
    sid       = "CloudFront"
    actions   = ["cloudfront:*"]
    resources = ["*"]
  }

  statement {
    sid     = "SiteEEstado"
    actions = ["s3:*"]
    resources = [
      "arn:aws:s3:::${local.prefixo}-site-${local.conta}",
      "arn:aws:s3:::${local.prefixo}-site-${local.conta}/*",
      "arn:aws:s3:::${var.bucket_estado}",
      "arn:aws:s3:::${var.bucket_estado}/*",
    ]
  }

  statement {
    sid       = "Roles"
    actions   = ["iam:*Role*", "iam:*RolePolicy*", "iam:TagRole", "iam:UntagRole", "iam:PassRole"]
    resources = ["arn:aws:iam::${local.conta}:role/${local.prefixo}-*"]
  }

  statement {
    sid       = "ProvedorOidc"
    actions   = ["iam:GetOpenIDConnectProvider", "iam:CreateOpenIDConnectProvider", "iam:DeleteOpenIDConnectProvider", "iam:TagOpenIDConnectProvider"]
    resources = [local.provedor_oidc_arn]
  }

  statement {
    sid       = "Leitura"
    actions   = ["sts:GetCallerIdentity", "s3:ListAllMyBuckets"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_permissoes.json
}
