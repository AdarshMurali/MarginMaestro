# Bucket is created by infra/gcp/bootstrap (run once, before the first init here).
terraform {
  backend "gcs" {
    bucket = "marginmaestro-demo-tfstate"
    prefix = "infra/gcp"
  }
}
