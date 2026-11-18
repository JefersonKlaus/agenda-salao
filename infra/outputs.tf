output "url_do_site" {
  value = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "api_url" {
  value = aws_apigatewayv2_api.api.api_endpoint
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.salao.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.site.id
}

output "bucket_do_site" {
  value = aws_s3_bucket.site.bucket
}

output "cloudfront_id" {
  value = aws_cloudfront_distribution.site.id
}
