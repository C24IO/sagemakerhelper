from troposphere.constants import NUMBER
from troposphere import Output, Ref, Template, Parameter, GetAtt, Join
from troposphere.kms import Key
from troposphere.s3 import Bucket, ServerSideEncryptionByDefault, BucketEncryption, ServerSideEncryptionRule
from troposphere.codecommit import Repository
from troposphere.awslambda import Function, Code, MEMORY_VALUES, Environment as Lambda_Environment
from troposphere.iam import Role, Policy
from troposphere.codepipeline import (
    Pipeline, Stages, Actions, ActionTypeID, OutputArtifacts, InputArtifacts,
    ArtifactStore)
from troposphere.codebuild import Project, Artifacts, Environment, Source
from troposphere.ecr import Repository as Docker_Repo
from troposphere.events import Rule, Target

# So listen - if this thing ever sees the insides of a production account you'll want to check out deletionpolicy
# attributes. I haven't enabled them for things like the codecommit repo or the ecr registry as i'm constantly tearing
# stacks up and down. Were I to do this in production i'd enabled retention of stuff like that. Seriously bro - you've
# been warned.

# These variables are used to bootstrap the cloudformation template. You'll need to change things like the region and
# account number. In additional you'll have to get your hands on the lambda code that submits the training job which here
# is referred to as sageDispatch. It is contained in this same github repo. Just shove it into a s3 bucket and make
# certain that the bucket is referred to in the "lambda_function_bucket" variable.

# The name of the ml project you're working on
project_name = 'census'
region = 'us-west-2'

# This is to ensure that buckets created by the cfn template are unique
account = '007038732177'
prefix = account + project_name

# buckets used to store machine learning dataset. Anything in here will be served up to the sagemaker containers
input_bucket_name = prefix + 'input'
output_bucket_name = prefix + 'output'

# the name of the pipeline that gets created by this cfn template and the name of the bucket used for the pipeline
# the name of the artificats that  hold the codecommit code the pipeline downloads.
pipeline_name = prefix + 'pipeline'
codepipeline_artifact_store_location = account + project_name + 'artifactstore'
pipeline_artifact_store_name = 'source_action_output'

# the name of the codecommmit repo where machine learning code gets commited to
repo_name = prefix + 'repo'
# The name of the codebuild project that creates the docker container
build_name = prefix + 'build'
code_build_image = 'aws/codebuild/docker:17.09.0'

# the name of the ecr registory that contains the docker container built for submission to sagemaker
ml_docker_registry_name = prefix + 'registry'

# variables for the name of the lambda function that gets invovked to send the container to training.
lambda_function_name = 'sageDispatch'
lambda_function_bucket = account + 'lambda'
lambda_function_key = lambda_function_name + ".zip"

# KMS key used to encrypted the input and output bucks that contain the data sets
project_kms_key = project_name + 'key'

# CFN Template
t = Template()
t.add_description("This template hydrates a machine learning pipeline.")

# Add the project's kms key to the cfn template
project_key = t.add_resource(Key(project_kms_key,
                                 Description=project_kms_key,
                                 Enabled=True,
                                 EnableKeyRotation=True,
                                 KeyPolicy={
                                     "Version": "2012-10-17",
                                     "Id": "project_key",
                                     "Statement": [
                                         {
                                             "Sid": "Enable IAM User Permissions",
                                             "Effect": "Allow",
                                             "Principal": {"AWS": "arn:aws:iam::" + account + ":root"},
                                             "Action": "kms:*",
                                             "Resource": "*"
                                         }]
                                 }
                                 ))

#Add buckets to the template
bucket_encryption_config = ServerSideEncryptionByDefault(KMSMasterKeyID=GetAtt(project_kms_key, "Arn"),
                                                         SSEAlgorithm='aws:kms')
bucket_encryption_rule = ServerSideEncryptionRule(ServerSideEncryptionByDefault=bucket_encryption_config)
bucket_encryption = BucketEncryption(ServerSideEncryptionConfiguration=[bucket_encryption_rule])

input_bucket = t.add_resource(
    Bucket('InputBucket', AccessControl='Private', BucketName=input_bucket_name, BucketEncryption=bucket_encryption))
output_bucket = t.add_resource(Bucket('OutputBucket', AccessControl='Private', BucketName=output_bucket_name,
                                      BucketEncryption=bucket_encryption))
codepipeline_artifact_store_bucket = t.add_resource(
    Bucket('CodePipelineBucket', AccessControl='Private', BucketName=codepipeline_artifact_store_location,
           BucketEncryption=bucket_encryption))

# Add ecr repo to the cfn template
ml_docker_repo = t.add_resource(Docker_Repo(ml_docker_registry_name, RepositoryName=ml_docker_registry_name))

# Add codecommit repo
repo = t.add_resource(Repository('Repository', RepositoryDescription='ML repo', RepositoryName=repo_name))


# Start to build out the codeBuild portion of the solution. This part of the pipeline relies on dockerfile being present
# in the codecommit repo that the pipeline passes onto it. The build details should also be contained in a buildspec.yml
# file that is also located in the same repo. The buildspec file will use the docker file to create a container based on
# the dockerfile and then tag it with the commit id that triggered the pipeline. Once the build is complete it will push
# it to ecr.
code_build_artifacts = Artifacts(Type='CODEPIPELINE')

environment = Environment(
    ComputeType='BUILD_GENERAL1_SMALL',
    Image=code_build_image,
    Type='LINUX_CONTAINER',
    EnvironmentVariables=[
        {'Name': 'AWS_DEFAULT_REGION', 'Value': region, 'Type': 'PLAINTEXT'},
        {'Name': 'AWS_ACCOUNT_ID', 'Value': account, 'Type': 'PLAINTEXT'},
        {'Name': 'IMAGE_REPO_NAME', 'Value': ml_docker_registry_name, 'Type': 'PLAINTEXT'},
        {'Name': 'IMAGE_TAG', 'Value': 'latest', 'Type': 'PLAINTEXT'},
        {'Name': 'CODE_COMMIT_REPO', 'Value': repo_name, 'Type': 'PLAINTEXT'}
    ]
)

source = Source(
    Type='CODEPIPELINE'
)

code_build_project = t.add_resource(Project(
    build_name,
    Artifacts=code_build_artifacts,
    Environment=environment,
    Name=build_name,
    ServiceRole=GetAtt("CodepipelineExecutionRole", "Arn"),
    Source=source,
))


# The place where codepipeline stores the source that it downloads from codecommit when the pipeline kicks off
artifactStore = ArtifactStore(Location=codepipeline_artifact_store_location, Type='S3')

# This is the role that is used by both codepipeline and codebuild to execute it's actions. I tried very hard to keep
# the policy document to the minimum required access. Bascially the pipeline is allowed to execute the lambda function
# that is used to send off docker images to training. It's allowed to manipulate the contents of the buckets used to
# store the machine learning data and the artificats in the codepipeline bucket. It's allowed to use get the source code
# from the specific code repo defined in the template. It's allowed to push docker images into the registry defined in
# the cfn template and finally it's allowed to write logs into cloudwatch.
CodepipelineExecutionRole = t.add_resource(Role(
    "CodepipelineExecutionRole",
    Path="/",
    Policies=[Policy(
        PolicyName="CodepipelineExecutionRole",
        PolicyDocument={
            "Version": "2012-10-17",
            "Statement": [{
                "Action": ["kms:Decrypt"],
                "Resource": GetAtt(project_kms_key, "Arn"),
                "Effect": "Allow"
            },
                {
                    "Action": [
                        "lambda:listfunctions"
                    ],
                    "Resource": "*",
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "lambda:invokefunction",
                        "lambda:listfunctions"
                    ],
                    "Resource": [GetAtt(lambda_function_name, "Arn")],
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "s3:ListBucket",
                        "s3:GetBucketPolicy",
                        "s3:GetObjectAcl",
                        "s3:PutObjectAcl",
                        "s3:DeleteObject",
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:PutObjectTagging"
                    ],
                    "Resource": [
                        Join('', [GetAtt("InputBucket", "Arn"), "/*"]),
                        Join('', [GetAtt("OutputBucket", "Arn"), "/*"]),
                        Join('', [GetAtt("CodePipelineBucket", "Arn"), "/*"])
                    ],
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "codecommit:CancelUploadArchive",
                        "codecommit:GetBranch",
                        "codecommit:GetCommit",
                        "codecommit:GetUploadArchiveStatus",
                        "codecommit:UploadArchive"
                    ],
                    "Resource": [GetAtt("Repository", "Arn")],
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "codebuild:BatchGetBuilds",
                        "codebuild:StartBuild",
                        "ecr:GetAuthorizationToken",
                        "iam:PassRole"
                ],
                    "Resource": "*",
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:PutImage",
                        "ecr:InitiateLayerUpload",
                        "ecr:UploadLayerPart",
                        "ecr:CompleteLayerUpload"
                ],
                    "Resource": Join('', ['arn:aws:ecr:', region, ':', account, ':repository/',
                                          ml_docker_registry_name]),
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                        "logs:DescribeLogStreams"
                    ],
                    "Resource": ["arn:aws:logs:*:*:*"],
                    "Effect": "Allow"
                }
            ]
        })],
    AssumeRolePolicyDocument={
        "Version": "2012-10-17",
        "Statement": [{
            "Action": ["sts:AssumeRole"],
            "Effect": "Allow",
            "Principal": {
                "Service": ["codepipeline.amazonaws.com", "codebuild.amazonaws.com"]
            }
        }]
    },
))

#These are the various states that have to be defined in the pipeline

source_action_id = ActionTypeID(
    Category='Source',
    Owner='AWS',
    Provider='CodeCommit',
    Version='1'
)

build_action_id = ActionTypeID(
    Category='Build',
    Owner='AWS',
    Provider='CodeBuild',
    Version='1'
)

invoke_action_id = ActionTypeID(
    Category='Invoke',
    Owner='AWS',
    Provider='Lambda',
    Version='1'
)

source_action = Actions(
    ActionTypeId=source_action_id,
    ###
    Configuration={
        "PollForSourceChanges": "false",
        "BranchName": "master",
        "RepositoryName": repo_name
    },
    InputArtifacts=[],
    Name='Source',
    RunOrder=1,
    OutputArtifacts=[OutputArtifacts(Name=pipeline_artifact_store_name)]
)

build_action = Actions(
    ActionTypeId=build_action_id,
    Configuration={
        "ProjectName": build_name
    },
    InputArtifacts=[InputArtifacts(Name=pipeline_artifact_store_name)],
    Name='Build',
    RunOrder=1,
    OutputArtifacts=[OutputArtifacts(Name='build_action_output')]
)

invoke_action = Actions(
    ActionTypeId=invoke_action_id,
    Configuration={
        "FunctionName": lambda_function_name
    },
    InputArtifacts=[InputArtifacts(Name=pipeline_artifact_store_name)],
    Name='Train',
    RunOrder=1,
    OutputArtifacts=[]
)

source_stage = Stages(
    Actions=[source_action],
    Name='Source'
)

build_stage = Stages(
    Actions=[build_action],
    Name='Build'
)

invoke_action = Stages(
    Actions=[invoke_action],
    Name='Train'
)

pipeline = t.add_resource(Pipeline(
    pipeline_name,
    RoleArn=GetAtt("CodepipelineExecutionRole", "Arn"),
    ArtifactStore=artifactStore,
    Stages=[source_stage, build_stage, invoke_action]))

# In order for the pipeline to be triggered by a code commit what's required is a cloudwatch event rule. This rule is
# configured so that whenever a commmit event comes over the cloudwatch event bus for the specific code commit repo it
# then executtes a startpipelineexecution call to the piepeline. Notice after this pattern that there is also a role
# that the rule assumes.
cw_event_pattern = {
    "source": [
        "aws.codecommit"
    ],
    "resources": [
        GetAtt("Repository", "Arn")
    ],
    "detail-type": [
        "CodeCommit Repository State Change"
    ],
    "detail": {
        "event": [
            "referenceCreated",
            "referenceUpdated"
        ],
        "referenceType": [
            "branch"
        ],
        "referenceName": [
            "master"
        ]
    }
}

# Role that allows the event rule to execute the start of the pipeline against the specific pipeline created in this cfn
CloudWatchEventExecutionRole = t.add_resource(Role(
    "CloudWatchEventExecutionRole",
    Path="/",
    Policies=[Policy(
        PolicyName='pipelineTargetRulePolicy',
        PolicyDocument={
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "codepipeline:StartPipelineExecution",
                "Resource": Join('', ['arn:aws:codepipeline:', region, ':', account, ':', Ref(pipeline)]),
                "Effect": "Allow"
            }
            ]
        })],
    AssumeRolePolicyDocument={
        "Version": "2012-10-17",
        "Statement": [{
            "Action": ["sts:AssumeRole"],
            "Effect": "Allow",
            "Principal": {
                "Service": ["events.amazonaws.com"]
            }
        }]
    },
))

cw_rule_target = Target(
    Arn=Join('', ["arn:aws:codepipeline:", region, ':', account, ':', Ref(pipeline)]),
    Id='mlTargert1',
    RoleArn=GetAtt("CloudWatchEventExecutionRole", "Arn")
)

pipeline_cw_rule = t.add_resource(Rule(
    'mlpipelinerule',
    Description='Triggers codepipeline',
    EventPattern=cw_event_pattern,
    State='ENABLED',
    Targets=[cw_rule_target]

))

# This role allows sagemaker to do things like use the kms key that was used to encrypt the contents of the input and
# output buckets as well as pull docker container images from the ecr repo.
SagemakerExecutionRole = t.add_resource(Role(
    "SagemakerExecutionRole",
    Path="/",
    Policies=[Policy(
        PolicyName="SagemakerExecutionRole",
        PolicyDocument={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": [
                        "kms:Decrypt",
                        "kms:GenerateDataKey"
                    ],
                    "Resource": GetAtt(project_key, "Arn"),
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:DeleteObject"
                    ],
                    "Resource": [
                        Join('', [GetAtt("InputBucket", "Arn"), "/*"]),
                        Join('', [GetAtt("OutputBucket", "Arn"), "/*"])
                    ],
                    "Effect": "Allow"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:CreateBucket",
                        "s3:GetBucketLocation",
                        "s3:ListBucket",
                        "s3:ListAllMyBuckets"
                    ],
                    "Resource": "*"
                },
                {
                    "Action": [
                        "ecr:GetAuthorizationToken",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                        "ecr:BatchCheckLayerAvailability"
                    ],
                    "Resource": Join('', ['arn:aws:ecr:', region, ':', account, ':repository/',
                                          ml_docker_registry_name]),
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "ecr:GetAuthorizationToken"
                    ],
                    "Resource": "*",
                    "Effect": "Allow"
                },
{
                    "Action": [
                        "cloudwatch:PutMetricData"
                    ],
                    "Resource": "*",
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:DescribeLogStreams",
                        "logs:GetLogEvents",
                        "logs:PutLogEvents"
                    ],
                    "Resource": ["arn:aws:logs:*:*:*"],
                    "Effect": "Allow"
                }
            ]
        })],
    AssumeRolePolicyDocument={
        "Version": "2012-10-17",
        "Statement": [{
            "Action": ["sts:AssumeRole"],
            "Effect": "Allow",
            "Principal": {
                "Service": ["sagemaker.amazonaws.com"]
            }
        }]
    },
))

# This is the role for the lambda function that is used to setup the sagemaker job. It needs permissions to get the
# commit id so that it can setup a training job with a specific docker container, get the artificats of the pipeline so
# that it can read the manifest file which defines certain parts of the job information, send a job to sagemaker, and
# finally to signal back to the pipeline success or failure.
LambdaExecutionRole = t.add_resource(Role(
    "LambdaExecutionRole",
    Path="/",
    Policies=[Policy(
        PolicyName=lambda_function_name,
        PolicyDocument={
            "Version": "2012-10-17",
            "Statement": [{
                "Action": ["logs:*"],
                "Resource": "arn:aws:logs:*:*:*",
                "Effect": "Allow"
            },
                {
                    "Action": ["kms:Decrypt"],
                    "Resource": GetAtt(project_kms_key, "Arn"),
                    "Effect": "Allow"
                },
                {
                    "Action": ["codepipeline:PutJobFailureResult",
                               "codepipeline:PutJobSuccessResult"],
                    "Resource": "*",
                    "Effect": "Allow"
                },
                {
                    "Action": [
                        "codecommit:GetBranch"
                    ],
                    "Resource": [GetAtt("Repository", "Arn")],
                    "Effect": "Allow"
                },
                {
                    "Action": ["s3:GetObject"],
                    "Resource": Join('', [GetAtt("CodePipelineBucket", "Arn"), "/*"]),
                    "Effect": "Allow"
                },
                {
                    "Action": ["sagemaker:CreateTrainingJob"],
                    "Resource": "*",
                    "Effect": "Allow"
                },
                {
                    "Action": ["iam:PassRole"],
                    "Resource": "*",
                    "Effect": "Allow"
                }
            ]
        })],
    AssumeRolePolicyDocument={
        "Version": "2012-10-17",
        "Statement": [{
            "Action": ["sts:AssumeRole"],
            "Effect": "Allow",
            "Principal": {
                "Service": ["lambda.amazonaws.com"]
            }
        }]
    },
))

# I used these environment variables so that the lambda code remains static while these fiddly bits that get setup
# for the project can just be injected in.
lambda_env = Lambda_Environment(Variables={
    'APP_BUNDLE': pipeline_artifact_store_name,
    'CODE_COMMIT_REPO': repo_name,
    'TRAINING_IMAGE': account + ".dkr.ecr." + region + ".amazonaws.com/" + ml_docker_registry_name,
    'SAGEMAKER_ROLE_ARN': GetAtt("SagemakerExecutionRole", "Arn"),
    'INPUT_BUCKET': 's3://' + input_bucket_name + '/',
    'BUCKET_KEY_ARN': GetAtt(project_kms_key, "Arn"),
    'OUTPUT_BUCKET': 's3://' + output_bucket_name + '/output/'
}
)

func = t.add_resource(Function(
    lambda_function_name,
    Code=Code(
        S3Bucket=lambda_function_bucket,
        S3Key=lambda_function_key
    ),
    FunctionName=lambda_function_name,
    Handler="sageDispatch.lambda_handler",
    Role=GetAtt("LambdaExecutionRole", "Arn"),
    Runtime="python2.7",
    Environment=lambda_env,
    Timeout=300
))

MemorySize = t.add_parameter(Parameter(
    'LambdaMemorySize',
    Type=NUMBER,
    Description='Amount of memory to allocate to the Lambda Function',
    Default='128',
    AllowedValues=MEMORY_VALUES
))

Timeout = t.add_parameter(Parameter(
    'LambdaTimeout',
    Type=NUMBER,
    Description='Timeout in seconds for the Lambda function',
    Default='60'
))

# This prints out the CFN template. You could of course write this to a file but I is lazy. Oh and don't print to yaml.
# There's either some bug with tropophere or with CF that causes templates to fail legacy parsing when submitted to CF
# in yaml format. It's certainly easier to look at but I got tired to troubleshooting.
print(t.to_json())
