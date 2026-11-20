# One Lambda per business action: each folder backend/lambdas/<action>/ has its use case, its
# inbound adapter (handler.py) and a lambda.json with its route, its database access ("read" or
# "write") and, for the ones that create logins, "identity": true. Adding a folder adds the function,
# its route and its logs; nothing to list here.
locals {
  lambdas_dir = "${path.module}/../backend/lambdas"
  core_dir    = "${path.module}/../backend/core"
  lambdas = {
    for config in fileset(local.lambdas_dir, "*/lambda.json") :
    # the same shape for all of them ("identity" is only in the few that create logins)
    dirname(config) => merge({ identity = false }, jsondecode(file("${local.lambdas_dir}/${config}")))
  }
  core_files = fileset(local.core_dir, "agenda_core/**/*.py")
}

# Each zip = the shared core (agenda_core/) + only this Lambda's own folder.
data "archive_file" "lambda" {
  for_each    = local.lambdas
  type        = "zip"
  output_path = "${path.module}/build/${each.key}.zip"

  dynamic "source" {
    for_each = local.core_files
    content {
      content  = file("${local.core_dir}/${source.value}")
      filename = source.value
    }
  }

  dynamic "source" {
    for_each = fileset("${local.lambdas_dir}/${each.key}", "*.py")
    content {
      content  = file("${local.lambdas_dir}/${each.key}/${source.value}")
      filename = "${each.key}/${source.value}"
    }
  }
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# Lambdas that change data ("write" in lambda.json).
resource "aws_iam_role" "lambda" {
  name               = "${local.prefix}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

# Lambdas that only read ("read" in lambda.json): they cannot write even if their code tried to.
resource "aws_iam_role" "lambda_read" {
  name               = "${local.prefix}-lambda-read"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

# Only what the functions use: read, write and delete items in this table. No Scan, no other tables.
data "aws_iam_policy_document" "lambda_access" {
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:ConditionCheckItem",
    ]
    resources = [aws_dynamodb_table.agenda.arn, "${aws_dynamodb_table.agenda.arn}/index/*"]
  }
}

data "aws_iam_policy_document" "lambda_read_access" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.agenda.arn, "${aws_dynamodb_table.agenda.arn}/index/*"]
  }
}

resource "aws_iam_role_policy" "lambda_data" {
  name   = "dados" # inline policy name kept as is ("dados" = data), so it is not recreated
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_access.json
}

resource "aws_iam_role_policy" "lambda_read_data" {
  name   = "read"
  role   = aws_iam_role.lambda_read.id
  policy = data.aws_iam_policy_document.lambda_read_access.json
}

# Lambdas that create logins ("identity": true): write the table and create users in this pool only.
resource "aws_iam_role" "lambda_identity" {
  name               = "${local.prefix}-lambda-identity"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "lambda_identity_access" {
  source_policy_documents = [data.aws_iam_policy_document.lambda_access.json]
  statement {
    actions   = ["cognito-idp:AdminCreateUser", "cognito-idp:AdminAddUserToGroup", "cognito-idp:AdminDeleteUser"]
    resources = [aws_cognito_user_pool.salon.arn]
  }
}

resource "aws_iam_role_policy" "lambda_identity_data" {
  name   = "identity"
  role   = aws_iam_role.lambda_identity.id
  policy = data.aws_iam_policy_document.lambda_identity_access.json
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  for_each = {
    write = aws_iam_role.lambda.name, read = aws_iam_role.lambda_read.name, identity = aws_iam_role.lambda_identity.name
  }
  role       = each.value
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.lambdas
  name              = "/aws/lambda/${local.prefix}-${replace(each.key, "_", "-")}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "action" {
  for_each      = local.lambdas
  function_name = "${local.prefix}-${replace(each.key, "_", "-")}"
  role = (each.value.identity ? aws_iam_role.lambda_identity.arn
  : each.value.database == "read" ? aws_iam_role.lambda_read.arn : aws_iam_role.lambda.arn)
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "${each.key}.handler.lambda_handler"
  filename         = data.archive_file.lambda[each.key].output_path
  source_code_hash = data.archive_file.lambda[each.key].output_base64sha256
  memory_size      = 256
  timeout          = 10

  environment {
    variables = merge({ TABLE_NAME = aws_dynamodb_table.agenda.name },
    each.value.identity ? { USER_POOL_ID = aws_cognito_user_pool.salon.id } : {})
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy_attachment.lambda_logs]
}
