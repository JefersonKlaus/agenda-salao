data "archive_file" "backend" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/src"
  output_path = "${path.module}/build/backend.zip"
  excludes    = ["**/__pycache__/**"]
}

data "aws_iam_policy_document" "lambda_confia" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.prefixo}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_confia.json
}

# Só o que a função usa: ler, gravar e apagar itens desta tabela. Nada de Scan nem de outras tabelas.
data "aws_iam_policy_document" "lambda_acesso" {
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:ConditionCheckItem",
    ]
    resources = [aws_dynamodb_table.agenda.arn]
  }
}

resource "aws_iam_role_policy" "lambda_dados" {
  name   = "dados"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_acesso.json
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.prefixo}-api"
  retention_in_days = var.retencao_logs_dias
}

resource "aws_lambda_function" "api" {
  function_name    = "${local.prefixo}-api"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "agenda.handler.lambda_handler"
  filename         = data.archive_file.backend.output_path
  source_code_hash = data.archive_file.backend.output_base64sha256
  memory_size      = 256
  timeout          = 10

  environment {
    variables = {
      TABELA = aws_dynamodb_table.agenda.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy_attachment.lambda_logs]
}
