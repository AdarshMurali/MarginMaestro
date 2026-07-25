# Compute (ECS/EC2/Lambda/App Runner) is deliberately not defined yet -- the
# choice depends on decisions not yet made (see docs/ROADMAP.md Phase 10,
# MM-102). Once decided, add the compute resource here and an aws_iam_role
# with a matching assume-role trust policy, then attach
# aws_iam_policy.read_parameters (see iam.tf) to it.
