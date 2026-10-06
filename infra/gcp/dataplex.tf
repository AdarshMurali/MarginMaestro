# Dataplex Universal Catalog (MM-135, ADR-0015): every Cloud SQL table and
# every GCS document family, registered from the in-repo catalog
# (docs/data_catalog.yaml -- the source of truth; edit it, not this file).
#
# - Aspect type `marginmaestro-governance`: owner, class, freshness, source and
#   the confidential fields. Required on every entry.
# - Entry type `marginmaestro-data-asset` and entry group `marginmaestro`.
# - One custom entry per table (`custom:marginmaestro.cloudsql.<table>`) and
#   per document family (`custom:marginmaestro.gcs.<family>`). The lineage
#   events (MM-136) use the same names, so a call's lineage graph lands on
#   these entries.
#
# Cost: catalog metadata storage is free up to 1 MiB (monthly average), then
# $2/GiB-month. ~21 small entries are a few KB: $0. Catalog API calls made by
# Terraform are free. No scans are created (Dataplex data-quality/profile
# scans are billed per DCU and would target BigQuery, which is parked with G7).

locals {
  catalog = yamldecode(file("${path.module}/../../docs/data_catalog.yaml"))

  catalog_entries = merge(
    {
      for name, table in local.catalog.tables : "cloudsql-${replace(name, "_", "-")}" => {
        fqn         = "custom:marginmaestro.cloudsql.${name}"
        title       = "Cloud SQL table ${name}"
        platform    = "Cloud SQL"
        resource    = "${google_sql_database_instance.main.name}/${google_sql_database.app.name}/public.${name}"
        owner       = table.owner
        description = table.description
        class       = table.class
        freshness   = table.freshness
        source      = table.source
        confidential_fields = sort([
          for column, entry in table.columns : column if entry.class == "confidential"
        ])
      }
    },
    {
      for name, family in local.catalog.documents : "gcs-${name}" => {
        fqn                 = "custom:marginmaestro.gcs.${name}"
        title               = "GCS documents: ${name}"
        platform            = "Cloud Storage"
        resource            = "gs://${google_storage_bucket.documents.name}/${name}/"
        owner               = family.owner
        description         = family.description
        class               = family.class
        freshness           = family.freshness
        source              = family.source
        confidential_fields = family.contains
      }
    },
  )

  governance_aspect_key = "${data.google_project.this.number}.${var.region}.${google_dataplex_aspect_type.governance.aspect_type_id}"
}

resource "google_project_service" "dataplex" {
  service            = "dataplex.googleapis.com"
  disable_on_destroy = false
}

resource "google_dataplex_aspect_type" "governance" {
  aspect_type_id = "marginmaestro-governance"
  location       = var.region
  display_name   = "MarginMaestro governance"
  description    = "Owner, classification (public/internal/confidential), freshness expectation and source of a MarginMaestro data asset (ADR-0015)."

  metadata_template = jsonencode({
    name = "marginmaestro-governance"
    type = "record"
    recordFields = [
      {
        name        = "owner"
        type        = "string"
        index       = 1
        constraints = { required = true }
      },
      {
        name  = "data_class"
        type  = "enum"
        index = 2
        enumValues = [
          { name = "public", index = 1 },
          { name = "internal", index = 2 },
          { name = "confidential", index = 3 },
        ]
        constraints = { required = true }
      },
      {
        name  = "freshness"
        type  = "string"
        index = 3
      },
      {
        name  = "source"
        type  = "string"
        index = 4
      },
      {
        name       = "confidential_fields"
        type       = "array"
        index      = 5
        arrayItems = { name = "field", type = "string" }
      },
    ]
  })

  depends_on = [google_project_service.dataplex]
}

resource "google_dataplex_entry_type" "asset" {
  entry_type_id = "marginmaestro-data-asset"
  location      = var.region
  display_name  = "MarginMaestro data asset"
  description   = "A Cloud SQL table or GCS document family of MarginMaestro, as listed in docs/data_catalog.yaml."
  platform      = "Google Cloud"
  system        = "MarginMaestro"

  required_aspects {
    type = google_dataplex_aspect_type.governance.name
  }

  depends_on = [google_project_service.dataplex]
}

resource "google_dataplex_entry_group" "marginmaestro" {
  entry_group_id = "marginmaestro"
  location       = var.region
  display_name   = "MarginMaestro"
  description    = "MarginMaestro's Cloud SQL tables and GCS document families (synced from docs/data_catalog.yaml)."

  depends_on = [google_project_service.dataplex]
}

resource "google_dataplex_entry" "asset" {
  for_each = local.catalog_entries

  entry_group_id = google_dataplex_entry_group.marginmaestro.entry_group_id
  location       = var.region
  entry_id       = each.key
  # Dataplex rejects the project id here ("project IDs are not supported"),
  # so the entry type is referenced by project number (found on first apply).
  entry_type           = "projects/${data.google_project.this.number}/locations/${var.region}/entryTypes/${google_dataplex_entry_type.asset.entry_type_id}"
  fully_qualified_name = each.value.fqn

  entry_source {
    display_name = each.value.title
    description  = each.value.description
    platform     = each.value.platform
    system       = "MarginMaestro"
    resource     = each.value.resource
    labels = {
      data-class = each.value.class
      owner      = each.value.owner
    }
  }

  aspects {
    aspect_key = local.governance_aspect_key
    aspect {
      data = jsonencode({
        owner               = each.value.owner
        data_class          = each.value.class
        freshness           = each.value.freshness
        source              = each.value.source
        confidential_fields = each.value.confidential_fields
      })
    }
  }
}

output "catalog_entry_group" {
  description = "Dataplex entry group holding the MarginMaestro catalog entries (MM-135)"
  value       = google_dataplex_entry_group.marginmaestro.name
}
