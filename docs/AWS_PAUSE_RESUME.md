# AWS pause / resume runbook

> **Status as of 2026-09-29: PAUSED** (credit crunch). Account `301276846405`, profile `lavanya`, region `ap-south-1`.

## What was changed on 2026-09-29

| Item | Before | Now |
|---|---|---|
| EventBridge schedule `daily-ec2-start-8am-ist` (`cron(0 10 ? * MON-FRI *)`, Asia/Kolkata) | ENABLED | **DISABLED** |
| EventBridge schedule `daily-ec2-stop-10pm-ist` (`cron(0 18 ? * MON-FRI *)`, Asia/Kolkata) | ENABLED | **DISABLED** |
| `marginmaestro-prod-app` (`i-08abe8840668f0f3f`, t3.micro) | on schedule | **stopped** |
| `finsight-chromadb` (`i-0d5332841d8f8da41`, t3.small) | on schedule | **stopped** |
| `finsight-flink` (`i-06df445415d082798`) | stopped | stopped (unchanged) |
| Elastic IP `13.202.222.57` (`eipalloc-0753ece538cef5a00`, Terraform `aws_eip.app`) → MarginMaestro app | attached | **RELEASED** |
| Elastic IP `13.206.225.80` (`eipalloc-012982f21044b6357`, not Terraform-managed) → finsight-chromadb | attached | **RELEASED** |

Released IPs cannot be recovered. **Both instances will get new public IPs on resume**, so everything that references the old IPs must be updated.

Still billing while paused: EBS volumes of the stopped instances, the Secrets Manager secret `marginmaestro/prod`, S3. The EventBridge schedules and IAM role `marginmaestro-finsight-ec2-scheduler-role` are kept (free).

## Resume checklist

### 1. MarginMaestro backend (`marginmaestro-prod-app`)
1. `cd infra && terraform plan`: it should show `aws_eip.app` being **created** (the old one was released outside Terraform). Review, then `terraform apply` (run it yourself; it needs explicit approval).
   - Alternative without Terraform: start the instance and allocate/associate a new EIP by hand. Terraform state will then drift and must be reconciled with `terraform import` or `terraform state rm`.
2. Note the new IP: `terraform output` (see `infra/outputs.tf`).
3. **Azure SQL firewall** (`finsight-sql-server`): replace the rule `marginmaestro-prod-ec2` (was `13.202.222.57`) with the new IP. Without this, the API cannot reach the DB.
4. **Vercel** (project `marginmaestro`, team `FinSightsAI`): update env vars `BACKEND_API_URL` and the backend target used by the `next.config.ts` fallback rewrite to `http://<new-ip>:8000`, then redeploy.
5. **Docs/links using the old IP:** `README.md` (API row + `run_demo --base-url`), `docs/ROADMAP.md` (MM-102 lines), resume and demo links.
6. Verify: `curl http://<new-ip>:8000/health`, log in on https://marginmaestro.vercel.app, and run `python -m demo.run_demo --base-url http://<new-ip>:8000`. Scenario percentages may need re-tuning after real-market drift.

### 2. FinSight_AI box (`finsight-chromadb`)
1. Allocate and associate a new EIP (it was never Terraform-managed here).
2. **Azure SQL firewall** (`finsight-sql-server`): update the rule `chroma-backend-ec2` (was `13.206.225.80`) to the new IP.
3. Update anything in the FinSight_AI project that points at `13.206.225.80` (its config, its frontend env vars, its links).

### 3. Re-enable the start/stop schedules
For each of `daily-ec2-start-8am-ist` and `daily-ec2-stop-10pm-ist`, run `aws scheduler get-schedule`, set `State` to `ENABLED`, strip `Arn`/`CreationDate`/`LastModificationDate`, write it with `Set-Content -Encoding ascii` (Windows PowerShell 5.1 adds a BOM otherwise), then `aws scheduler update-schedule --cli-input-json file://...`.
