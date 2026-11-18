resource "aws_cognito_user_pool" "salao" {
  name                     = "${local.prefixo}-usuarios"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = var.ambiente == "prod" ? "ACTIVE" : "INACTIVE"

  # Só você cria as contas dos salões (por enquanto não há cadastro aberto).
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 10
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_client" "site" {
  name            = "${local.prefixo}-site"
  user_pool_id    = aws_cognito_user_pool.salao.id
  generate_secret = false # app de navegador não guarda segredo

  explicit_auth_flows = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
