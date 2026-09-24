#!/bin/sh
# compute-service on AWS Fargate: 2 vCPU, 16 GB, x86_64, us-east-1 by default.
#
#     COMPUTE_SERVICE_TOKEN=... sh cloud/deploy_compute.sh
#     sh cloud/teardown_compute.sh        # stops the billing
#
# Needs the AWS CLI signed in and Docker able to build linux/amd64. Creates, or reuses
# when they exist: an ECR repository, a Secrets Manager secret holding the bearer token,
# a task execution role, a log group, an ECS cluster, a security group open on the
# service port, a task definition and a one-task service with a public IP. Prints the
# service URL. The size matches the hosted Pixeltable database's cpu and memory_mb, so
# the model work runs on the same compute on both sides.
#
# Plain HTTP on the task's public IP: there is no domain to put a certificate on. The
# bearer token keeps strangers off the endpoints; it does not keep it private on the wire.
set -eu
: "${COMPUTE_SERVICE_TOKEN:?set COMPUTE_SERVICE_TOKEN to the bearer token both consumers will send}"
REGION=${AWS_REGION:-us-east-1}
NAME=platform-comparison-compute
PORT=8080
CPU=2048
MEMORY=16384
cd "$(dirname "$0")/.."
aws() { command aws --region "$REGION" --output text "$@"; }

ACCOUNT=$(aws sts get-caller-identity --query Account)
REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$NAME"

echo "--- image"
aws ecr describe-repositories --repository-names "$NAME" >/dev/null 2>&1 ||
    aws ecr create-repository --repository-name "$NAME" >/dev/null
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%%/*}"
docker buildx build --platform linux/amd64 -t "$REPO:latest" --push compute-service

echo "--- secret"
if SECRET_ARN=$(aws secretsmanager describe-secret --secret-id "$NAME/token" --query ARN 2>/dev/null); then
    printf '%s' "$COMPUTE_SERVICE_TOKEN" | aws secretsmanager put-secret-value --secret-id "$SECRET_ARN" \
        --secret-string file:///dev/stdin >/dev/null
else
    SECRET_ARN=$(printf '%s' "$COMPUTE_SERVICE_TOKEN" |
        aws secretsmanager create-secret --name "$NAME/token" --secret-string file:///dev/stdin --query ARN)
fi

echo "--- role"
ROLE="$NAME-execution"
if ! ROLE_ARN=$(aws iam get-role --role-name "$ROLE" --query Role.Arn 2>/dev/null); then
    ROLE_ARN=$(aws iam create-role --role-name "$ROLE" --query Role.Arn --assume-role-policy-document \
        '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}')
    aws iam attach-role-policy --role-name "$ROLE" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
fi
# Only this one secret, which is all the task reads at start.
aws iam put-role-policy --role-name "$ROLE" --policy-name read-token --policy-document \
    "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"$SECRET_ARN\"}]}"

echo "--- network"
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId')
SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" Name=default-for-az,Values=true \
    --query 'Subnets[].SubnetId' | tr '\t' ',')
if ! SG=$(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" "Name=group-name,Values=$NAME" \
    --query 'SecurityGroups[0].GroupId') || [ "$SG" = None ]; then
    SG=$(aws ec2 create-security-group --group-name "$NAME" --vpc-id "$VPC" --query GroupId \
        --description 'compute-service for the platform comparison')
    aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port "$PORT" --cidr 0.0.0.0/0 >/dev/null
fi

echo "--- service"
aws logs create-log-group --log-group-name "/ecs/$NAME" 2>/dev/null || true
aws ecs create-cluster --cluster-name "$NAME" >/dev/null
TASK_DEF=$(aws ecs register-task-definition --family "$NAME" --network-mode awsvpc \
    --requires-compatibilities FARGATE --cpu "$CPU" --memory "$MEMORY" \
    --runtime-platform cpuArchitecture=X86_64,operatingSystemFamily=LINUX \
    --execution-role-arn "$ROLE_ARN" --query taskDefinition.taskDefinitionArn \
    --container-definitions "[{\"name\":\"compute\",\"image\":\"$REPO:latest\",\"essential\":true,
        \"portMappings\":[{\"containerPort\":$PORT}],
        \"environment\":[{\"name\":\"PORT\",\"value\":\"$PORT\"}],
        \"secrets\":[{\"name\":\"COMPUTE_SERVICE_TOKEN\",\"valueFrom\":\"$SECRET_ARN\"}],
        \"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/$NAME\",
            \"awslogs-region\":\"$REGION\",\"awslogs-stream-prefix\":\"compute\"}}}]")
NETWORK="awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=ENABLED}"
if [ "$(aws ecs describe-services --cluster "$NAME" --services "$NAME" --query 'services[0].status' 2>/dev/null)" = ACTIVE ]; then
    aws ecs update-service --cluster "$NAME" --service "$NAME" --task-definition "$TASK_DEF" \
        --desired-count 1 --force-new-deployment >/dev/null
else
    aws ecs create-service --cluster "$NAME" --service-name "$NAME" --task-definition "$TASK_DEF" \
        --desired-count 1 --launch-type FARGATE --network-configuration "$NETWORK" >/dev/null
fi
aws ecs wait services-stable --cluster "$NAME" --services "$NAME"

TASK=$(aws ecs list-tasks --cluster "$NAME" --service-name "$NAME" --query 'taskArns[0]')
ENI=$(aws ecs describe-tasks --cluster "$NAME" --tasks "$TASK" \
    --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value")
IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI" --query 'NetworkInterfaces[0].Association.PublicIp')
echo "http://$IP:$PORT"
