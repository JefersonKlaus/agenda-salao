resource "aws_dynamodb_table" "agenda" {
  # Physical name kept as is ("dados" = data): renaming the table would replace it and lose its data.
  name         = "${local.prefix}-dados"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # A client's appointments, whatever the date: each appointment carries GSI1PK = "<salon>#<phone>"
  # (backend/core/agenda_core/adapters/dynamo_repository.py). Adding an index updates the table in
  # place: its data stays.
  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "by_client"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = var.environment == "prod"
}
