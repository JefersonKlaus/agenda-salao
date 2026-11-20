# Resources renamed when the code was translated to English. These blocks tell Terraform they are
# the same objects, so existing environments are updated in place instead of destroyed and recreated
# (the user pool holds every login). They can be deleted once every environment has been deployed
# with them at least once.

moved {
  from = aws_cognito_user_pool.salao
  to   = aws_cognito_user_pool.salon
}

moved {
  from = aws_apigatewayv2_stage.padrao
  to   = aws_apigatewayv2_stage.default_stage
}

moved {
  from = aws_cloudfront_response_headers_policy.seguranca
  to   = aws_cloudfront_response_headers_policy.security
}

moved {
  from = aws_iam_role_policy.lambda_dados
  to   = aws_iam_role_policy.lambda_data
}

# The single API Lambda was split into one Lambda per action (backend/lambdas/). Its logging
# attachment is kept as the write role's one, instead of being detached and attached again.
moved {
  from = aws_iam_role_policy_attachment.lambda_logs
  to   = aws_iam_role_policy_attachment.lambda_logs["write"]
}
