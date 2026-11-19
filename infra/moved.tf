# Resources renamed when the code was translated to English. These blocks tell Terraform they are
# the same objects, so existing environments are updated in place instead of destroyed and recreated
# (the user pool holds every login). They can be deleted once every environment has been deployed
# with them at least once.

moved {
  from = aws_cognito_user_pool.salao
  to   = aws_cognito_user_pool.salon
}

moved {
  from = aws_apigatewayv2_route.todas
  to   = aws_apigatewayv2_route.catch_all
}

moved {
  from = aws_apigatewayv2_stage.padrao
  to   = aws_apigatewayv2_stage.default_stage
}

moved {
  from = aws_lambda_permission.api_chama_lambda
  to   = aws_lambda_permission.api_invokes_lambda
}

moved {
  from = aws_cloudfront_response_headers_policy.seguranca
  to   = aws_cloudfront_response_headers_policy.security
}

moved {
  from = aws_iam_role_policy.lambda_dados
  to   = aws_iam_role_policy.lambda_data
}
