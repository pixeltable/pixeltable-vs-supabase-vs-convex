#!/bin/sh
# Remove everything cloud/deploy_compute.sh created, so nothing keeps billing.
#
#     sh cloud/teardown_compute.sh
#
# The ECR repository, its image and the CodeBuild project go too; a later deploy rebuilds them.
set -u
REGION=${AWS_REGION:-us-east-1}
NAME=platform-comparison-compute
aws() { command aws --region "$REGION" --output text "$@"; }

aws ecs update-service --cluster "$NAME" --service "$NAME" --desired-count 0 >/dev/null 2>&1
aws ecs delete-service --cluster "$NAME" --service "$NAME" --force >/dev/null 2>&1 &&
    aws ecs wait services-inactive --cluster "$NAME" --services "$NAME"
aws ecs delete-cluster --cluster "$NAME" >/dev/null 2>&1
for arn in $(aws ecs list-task-definitions --family-prefix "$NAME" --query 'taskDefinitionArns[]'); do
    aws ecs deregister-task-definition --task-definition "$arn" >/dev/null
done
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId')
SG=$(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" "Name=group-name,Values=$NAME" \
    --query 'SecurityGroups[0].GroupId')
[ "$SG" != None ] && aws ec2 delete-security-group --group-id "$SG"
aws iam delete-role-policy --role-name "$NAME-execution" --policy-name read-token 2>/dev/null
aws iam detach-role-policy --role-name "$NAME-execution" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy 2>/dev/null
aws iam delete-role --role-name "$NAME-execution" 2>/dev/null
aws secretsmanager delete-secret --secret-id "$NAME/token" --force-delete-without-recovery >/dev/null 2>&1
aws logs delete-log-group --log-group-name "/ecs/$NAME" 2>/dev/null
aws ecr delete-repository --repository-name "$NAME" --force >/dev/null 2>&1
aws codebuild delete-project --name "$NAME" >/dev/null 2>&1
aws iam delete-role-policy --role-name "$NAME-build" --policy-name build 2>/dev/null
aws iam detach-role-policy --role-name "$NAME-build" \
    --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser 2>/dev/null
aws iam delete-role --role-name "$NAME-build" 2>/dev/null
ACCOUNT=$(aws sts get-caller-identity --query Account)
aws s3 rb "s3://$NAME-build-$ACCOUNT" --force >/dev/null 2>&1
echo "removed $NAME from $REGION"
