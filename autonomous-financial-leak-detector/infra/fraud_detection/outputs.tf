output "kinesis_stream_arn" {
  value = aws_kinesis_stream.transactions.arn
}

output "kinesis_stream_name" {
  value = aws_kinesis_stream.transactions.name
}

output "flink_application_name" {
  value = aws_kinesisanalyticsv2_application.fraud_detector.name
}

output "lambda_fraud_scorer_arn" {
  value = aws_lambda_function.fraud_scorer.arn
}

output "lambda_fraud_scorer_name" {
  value = aws_lambda_function.fraud_scorer.function_name
}

output "fraud_alerts_sns_arn" {
  value = aws_sns_topic.fraud_alerts.arn
}

output "flink_checkpoint_bucket" {
  value = aws_s3_bucket.flink_checkpoints.id
}
