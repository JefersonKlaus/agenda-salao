resource "aws_cognito_user_pool" "salon" {
  # Physical name kept as is ("usuarios" = users): renaming the pool would replace it and delete
  # every login. The create-user workflow looks the pool up by this name.
  name                     = "${local.prefix}-usuarios"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = var.environment == "prod" ? "ACTIVE" : "INACTIVE"

  # Only you create the salons' accounts (there is no open sign-up for now).
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

  # Written when the manager creates a login in the app (create_access): the salon it belongs to and,
  # for a service provider, her professional. Immutable: set once, at creation, and never changed by
  # anyone, so a login cannot move itself to another salon or professional. The token carries them.
  schema {
    name                     = "salon"
    attribute_data_type      = "String"
    mutable                  = false
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 1
      max_length = 64
    }
  }

  schema {
    name                     = "professional_id"
    attribute_data_type      = "String"
    mutable                  = false
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 1
      max_length = 16
    }
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_client" "site" {
  name            = "${local.prefix}-site"
  user_pool_id    = aws_cognito_user_pool.salon.id
  generate_secret = false # a browser app cannot keep a secret

  explicit_auth_flows = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]

  prevent_user_existence_errors = "ENABLED"
  write_attributes              = ["email", "name"] # never custom:salon / custom:professional_id
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

# What a login may do. The salon's own account (created by the "Create salon user" workflow, with no
# custom:salon) is the manager even in no group; a login created in the app is in one of these.
resource "aws_cognito_user_group" "manager" {
  name         = "manager"
  user_pool_id = aws_cognito_user_pool.salon.id
  description  = "Gerente: tudo"
}

resource "aws_cognito_user_group" "employee" {
  name         = "employee"
  user_pool_id = aws_cognito_user_pool.salon.id
  description  = "Funcionaria: ve a agenda e os servicos; registra as proprias ausencias"
}
