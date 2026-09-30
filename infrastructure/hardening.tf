# ─────────────────────────────────────────────────────────────────────────────
# Dengbej AI — Production Hardening (Phase 1)
#
# PLAN-ONLY / DISABLED BY DEFAULT.
#
# Every resource in this file is gated by a feature flag that defaults to
# false, so `count` evaluates to 0 and Terraform plans NO change until a flag
# is deliberately turned on in a later, individually reviewed apply. This lets
# us keep the intended hardening in code and review it now, without touching
# live AWS.
#
# See docs/production_infrastructure_plan.md → SAFE APPLY SEQUENCE.
#
# What this file intentionally does NOT do in Phase 1:
#   - No CloudFront distribution (a later, separately reviewed step).
#   - No change to S3 Block Public Access or the public bucket policy.
#   - No DynamoDB table replacement. TTL and the pub_date GSI are IN-PLACE,
#     additive edits to the existing table block; they are intentionally NOT
#     represented here (editing the live table block could surface an
#     unexpected diff). They are specified as reviewed proposals in the plan
#     doc and applied by editing news_ingestion.tf in their own apply step.
#   - No deletion of any data. No detachment of existing IAM policies.
# ─────────────────────────────────────────────────────────────────────────────

# ─── S3 lifecycle for audio (transition only — NO expiry / NO delete) ────────
# Transitions older audio objects to cheaper STANDARD_IA storage. There is no
# expiration or deletion action, so this rule never removes any audio file.
# Additive: creating a lifecycle configuration does not alter existing objects'
# accessibility or the bucket policy.
resource "aws_s3_bucket_lifecycle_configuration" "audio_lifecycle" {
  count  = var.enable_s3_audio_lifecycle ? 1 : 0
  bucket = aws_s3_bucket.audio_storage.id

  rule {
    id     = "transition-old-audio-to-ia"
    status = "Enabled"

    filter {}

    transition {
      days          = var.s3_audio_transition_days
      storage_class = "STANDARD_IA"
    }
    # Intentionally NO expiration / NO delete action.
  }
}

# ─── Least-privilege replacement policy for the legacy shared role ───────────
# The legacy summary role (aws_iam_role.lambda_role) currently attaches the
# AWS-managed AmazonPollyFullAccess and AmazonBedrockFullAccess policies
# (full-service). This scoped inline policy grants only the actions that Lambda
# actually uses (verified in backend code): Bedrock InvokeModel on the specific
# model/inference-profile ARNs, and Polly SynthesizeSpeech.
#
# This resource only ADDS the scoped inline policy. Detaching the two managed
# policies is a separate, deliberate edit (remove the
# aws_iam_role_policy_attachment.lambda_polly_full /
# .lambda_bedrock_full resources) performed in the SAME reviewed apply, so the
# swap is explicit and trivially reversible. Enable only after confirming the
# legacy Lambda's real runtime usage against CloudTrail/Access Analyzer.
resource "aws_iam_role_policy" "legacy_least_privilege" {
  count = var.manage_least_privilege_legacy_role ? 1 : 0

  name = "DengbejLegacyScopedAiSpeech"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ScopedBedrockInvoke"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}:*:inference-profile/${var.bedrock_model_id}",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
        ]
      },
      {
        Sid      = "ScopedPollySynthesize"
        Effect   = "Allow"
        Action   = ["polly:SynthesizeSpeech"]
        Resource = "*" # Polly does not support resource-level permissions
      }
    ]
  })
}
