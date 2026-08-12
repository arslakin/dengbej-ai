# ─────────────────────────────────────────────────────────────────────────────
# Dengbej AI — Events Table (News Presentation V2)
#
# Canonical news events: clusters of source articles about the same development.
# Provides stable event identity (ULID), canonical URLs via slug, and
# reusable AI-generated context across programs.
#
# Design decisions affecting future edition/archive support:
# - PK is event_id (ULID) — time-sortable, enables range queries on creation time
# - No range key on the base table — events are accessed by ID or slug
# - GSI on slug for O(1) URL lookups (/news/{slug})
# - No TTL configured — events persist indefinitely for archive/SEO
# - Edition history is stored in dengbej-programs (program_id + briefing_date)
#   which already supports historical records via its range key
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_dynamodb_table" "events" {
  name         = var.events_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"

  attribute {
    name = "event_id"
    type = "S"
  }

  attribute {
    name = "slug"
    type = "S"
  }

  global_secondary_index {
    name            = "slug-index"
    hash_key        = "slug"
    projection_type = "ALL"
  }

  tags = {
    Name    = "Dengbej AI Events"
    Project = "dengbej-ai"
  }
}
