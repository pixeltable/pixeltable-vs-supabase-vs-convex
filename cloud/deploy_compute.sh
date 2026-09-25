#!/bin/sh
# compute-service on AWS Fargate: 2 vCPU, 8 GB, x86_64, us-east-1 by default.
#
#     COMPUTE_SERVICE_TOKEN=... sh cloud/deploy_compute.sh
#     sh cloud/teardown_compute.sh        # stops the billing
#
# Needs the AWS CLI signed in, and nothing else locally: the image is built by CodeBuild on
# x86_64, because building it here means amd64 emulation (llama.cpp's kernels die with
# SIGILL under it) and several GB of local disk. Creates, or reuses when they exist: an
# ECR repository, a CodeBuild project with its role and a source bucket, a Secrets
# Manager secret holding the bearer token, a task execution role, a log group, an ECS
# cluster, a security group open on the service port, a task definition and a one-task
# service with a public IP. Ends with a smoke test against the live task, which is the
# first time the chat model runs on x86, and prints the service URL. The size matches the hosted Pixeltable database's cpu and memory_mb, so
# the model work runs on the same compute on both sides.
#
# Plain HTTP on the task's public IP: there is no domain to put a certificate on. The
# bearer token keeps strangers off the endpoints; it does not keep it private on the wire.
# -f: no globbing, since the CodeBuild environment argument contains [ ].
set -euf
: "${COMPUTE_SERVICE_TOKEN:?set COMPUTE_SERVICE_TOKEN to the bearer token both consumers will send}"
REGION=${AWS_REGION:-us-east-1}
NAME=platform-comparison-compute
PORT=8080
CPU=2048
MEMORY=8192
cd "$(dirname "$0")/.."
aws() { command aws --region "$REGION" --output text "$@"; }

ACCOUNT=$(aws sts get-caller-identity --query Account)
REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$NAME"

echo "--- image"
aws ecr describe-repositories --repository-names "$NAME" >/dev/null 2>&1 ||
    aws ecr create-repository --repository-name "$NAME" >/dev/null
BUCKET="$NAME-build-$ACCOUNT"
aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1 || aws s3api create-bucket --bucket "$BUCKET" >/dev/null
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
cp compute-service/app.py compute-service/pyproject.toml compute-service/prefetch.py \
    compute-service/Dockerfile compute-service/.dockerignore "$stage/"
cat >"$stage/buildspec.yml" <<'SPEC'
version: 0.2
phases:
  pre_build:
    commands:
      - aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%%/*}"
  build:
    commands:
      - docker build -t "$REPO:$TAG" .
      - docker push "$REPO:$TAG"
SPEC
# Tagged by a hash of what goes into it, so the task runs an image that says which source
# built it, and a rerun with unchanged source reuses the image instead of rebuilding.
TAG=$(cd compute-service && cat app.py pyproject.toml prefetch.py Dockerfile .dockerignore | shasum -a 256 | cut -c1-16)
(cd "$stage" && zip -q -r source.zip . -x source.zip)
aws s3 cp "$stage/source.zip" "s3://$BUCKET/source.zip" >/dev/null

BUILD_ROLE="$NAME-build"
if ! BUILD_ROLE_ARN=$(aws iam get-role --role-name "$BUILD_ROLE" --query Role.Arn 2>/dev/null); then
    BUILD_ROLE_ARN=$(aws iam create-role --role-name "$BUILD_ROLE" --query Role.Arn --assume-role-policy-document \
        '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"codebuild.amazonaws.com"},"Action":"sts:AssumeRole"}]}')
    aws iam attach-role-policy --role-name "$BUILD_ROLE" \
        --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser
fi
aws iam put-role-policy --role-name "$BUILD_ROLE" --policy-name build --policy-document \
    "{\"Version\":\"2012-10-17\",\"Statement\":[
        {\"Effect\":\"Allow\",\"Action\":[\"logs:CreateLogGroup\",\"logs:CreateLogStream\",\"logs:PutLogEvents\"],\"Resource\":\"*\"},
        {\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::$BUCKET/*\"}]}"
PROJECT_ARGS="--source type=S3,location=$BUCKET/source.zip --artifacts type=NO_ARTIFACTS
    --environment type=LINUX_CONTAINER,image=aws/codebuild/standard:7.0,computeType=BUILD_GENERAL1_MEDIUM,privilegedMode=true,environmentVariables=[{name=REPO,value=$REPO},{name=TAG,value=$TAG}]
    --service-role $BUILD_ROLE_ARN"
if aws codebuild batch-get-projects --names "$NAME" --query 'projects[0].name' | grep -q "$NAME"; then
    # shellcheck disable=SC2086
    aws codebuild update-project --name "$NAME" $PROJECT_ARGS >/dev/null
else
    # A new role takes a few seconds before CodeBuild can assume it.
    # shellcheck disable=SC2086
    until aws codebuild create-project --name "$NAME" $PROJECT_ARGS >/dev/null 2>&1; do sleep 5; done
fi
if aws ecr describe-images --repository-name "$NAME" --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
    echo "image $TAG already built"
else
    BUILD=$(aws codebuild start-build --project-name "$NAME" --query build.id)
    while [ "$(aws codebuild batch-get-builds --ids "$BUILD" --query 'builds[0].buildStatus')" = IN_PROGRESS ]; do
        sleep 15
    done
    STATUS=$(aws codebuild batch-get-builds --ids "$BUILD" --query 'builds[0].buildStatus')
    if [ "$STATUS" != SUCCEEDED ]; then
        echo "image build $STATUS: $(aws codebuild batch-get-builds --ids "$BUILD" --query 'builds[0].logs.deepLink')" >&2
        exit 1
    fi
fi

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
# An account that has never run ECS has no service-linked role, and CreateService fails
# without it. Creating it is a no-op error when it already exists.
aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com >/dev/null 2>&1 || true
aws ecs create-cluster --cluster-name "$NAME" >/dev/null
TASK_DEF=$(aws ecs register-task-definition --family "$NAME" --network-mode awsvpc \
    --requires-compatibilities FARGATE --cpu "$CPU" --memory "$MEMORY" \
    --runtime-platform cpuArchitecture=X86_64,operatingSystemFamily=LINUX \
    --execution-role-arn "$ROLE_ARN" --query taskDefinition.taskDefinitionArn \
    --container-definitions "[{\"name\":\"compute\",\"image\":\"$REPO:$TAG\",\"essential\":true,
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
# One waiter gives up after ten minutes, and the first pull of a multi-GB image can take longer.
for attempt in 1 2 3; do
    aws ecs wait services-stable --cluster "$NAME" --services "$NAME" && break
    [ "$attempt" = 3 ] && exit 1
done

TASK=$(aws ecs list-tasks --cluster "$NAME" --service-name "$NAME" --query 'taskArns[0]')
ENI=$(aws ecs describe-tasks --cluster "$NAME" --tasks "$TASK" \
    --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value")
IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI" --query 'NetworkInterfaces[0].Association.PublicIp')
URL="http://$IP:$PORT"

echo "--- smoke"
# The header goes through a file so the token never shows in the process list.
header="$stage/auth"
printf 'Authorization: Bearer %s\n' "$COMPUTE_SERVICE_TOKEN" >"$header"
chmod 600 "$header"
for call in 'embed-text {"texts":["hello"]}' 'chat {"messages":[{"role":"user","content":"Say hi."}],"max_tokens":8}'; do
    path=${call%% *}
    curl -sf -o /dev/null -X POST "$URL/$path" -H @"$header" -H 'Content-Type: application/json' -d "${call#* }" ||
        { echo "smoke failed on /$path; logs: aws logs tail /ecs/$NAME --region $REGION" >&2; exit 1; }
done
echo "$URL"
