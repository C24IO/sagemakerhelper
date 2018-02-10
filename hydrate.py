from troposphere.constants import NUMBER
from troposphere import Output, Ref, Template, Parameter, GetAtt, Join
from troposphere.kms import Key
from troposphere.s3 import Bucket, ServerSideEncryptionByDefault, BucketEncryption, ServerSideEncryptionRule
from troposphere.codecommit import Repository
from troposphere.awslambda import Function, Code, MEMORY_VALUES, Environment as Lambda_Environment
from troposphere.iam import Role, Policy
from troposphere.codepipeline import (
    Pipeline, Stages, Actions, ActionTypeID, OutputArtifacts, InputArtifacts,
    ArtifactStore, DisableInboundStageTransitions)
from troposphere.codebuild import Project, Artifacts, Environment, Source
from troposphere.ecr import Repository as Docker_Repo
from troposphere.events import Rule, Target

project_name = 'cloudMlPipeline'
account = '007038732177'
prefix = account + project_name
input_bucket = prefix + 'Input'
output_bucket = prefix + 'Output'
pipeline_name = prefix + 'Pipeline'
repo_name = prefix + 'Repo'
build_name = prefix + 'Build'
lambda_function_name = 'sageDispatch'
lambda_function_bucket = account + 'lambda'
lambda_function_key = lambda_function_name + ".zip"
project_kms_key = project_name + 'Key'
root_arn = "arn:aws:iam::" + account + ":root"
codepipeline_artifact_store_location = account + project_name.lower() + 'artifactstore'
code_build_image = 'aws/codebuild/docker:17.09.0'
region = 'us-west-2'
ml_docker_registry_name = prefix + 'Registry'
pipeline_artificat_store_name = 'source_action_output'

t = Template()

ml_docker_repo = t.add_resource(Docker_Repo(ml_docker_registry_name, RepositoryName=ml_docker_registry_name.lower()))

code_build_artifacts = Artifacts(Type='CODEPIPELINE')

environment = Environment(
    ComputeType='BUILD_GENERAL1_SMALL',
    Image=code_build_image,
    Type='LINUX_CONTAINER',
    EnvironmentVariables=[
        {'Name': 'AWS_DEFAULT_REGION', 'Value': region, 'Type': 'PLAINTEXT'},
        {'Name': 'AWS_ACCOUNT_ID', 'Value': account, 'Type': 'PLAINTEXT'},
        {'Name': 'IMAGE_REPO_NAME', 'Value': ml_docker_registry_name.lower(), 'Type': 'PLAINTEXT'},
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
                                             "Principal": {"AWS": root_arn},
                                             "Action": "kms:*",
                                             "Resource": "*"
                                         }]
                                 }
                                 ))

t.add_description("This template hydrates a machine learning pipeline.")

bucket_encryption_config = ServerSideEncryptionByDefault(KMSMasterKeyID=GetAtt(project_kms_key, "Arn"),
                                                         SSEAlgorithm='aws:kms')
bucket_encryption_rule = ServerSideEncryptionRule(ServerSideEncryptionByDefault=bucket_encryption_config)
bucket_encryption = BucketEncryption(ServerSideEncryptionConfiguration=[bucket_encryption_rule])

input_bucket = t.add_resource(
    Bucket('InputBucket', AccessControl='Private', BucketName=input_bucket.lower(), BucketEncryption=bucket_encryption))
output_bucket = t.add_resource(Bucket('OutputBucket', AccessControl='Private', BucketName=output_bucket.lower(),
                                      BucketEncryption=bucket_encryption))
codepipeline_artifact_store_bucket = t.add_resource(
    Bucket('CodePipelineBucket', AccessControl='Private', BucketName=codepipeline_artifact_store_location,
           BucketEncryption=bucket_encryption))
t.add_output(Output('InputBucket', Value=Ref(input_bucket), Description='Name of input S3 bucket'))
t.add_output(Output('OutputBucket', Value=Ref(output_bucket), Description='Name of output S3 bucket'))

repo = t.add_resource(Repository('Repository', RepositoryDescription='ML repo', RepositoryName=repo_name))
t.add_output(Output('Repository', Value=Ref(repo), Description='ML repo'))

artifactStore = ArtifactStore(Location=codepipeline_artifact_store_location, Type='S3')

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
                {"Action": [
                    "codebuild:BatchGetBuilds",
                    "codebuild:StartBuild",
                    "ecr:GetAuthorizationToken",
                    "iam:PassRole"
                ],
                    "Resource": "*",
                    "Effect": "Allow"
                },
                {"Action": [
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:PutImage",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload"
                ],
                    "Resource": Join('', ['arn:aws:ecr:', region, ':', account, ':repository/', ml_docker_registry_name.lower()]),
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

lambda_env = Lambda_Environment(Variables={'App_bundle': pipeline_artificat_store_name})

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
    OutputArtifacts=[OutputArtifacts(Name=pipeline_artificat_store_name)]
)

build_action = Actions(
    ActionTypeId=build_action_id,
    Configuration={
        "ProjectName": build_name
    },
    InputArtifacts=[InputArtifacts(Name=pipeline_artificat_store_name)],
    Name='Build',
    RunOrder=1,
    OutputArtifacts=[OutputArtifacts(Name='build_action_output')]
)

invoke_action = Actions(
    ActionTypeId=invoke_action_id,
    Configuration={
        "FunctionName": lambda_function_name
    },
    InputArtifacts=[InputArtifacts(Name=pipeline_artificat_store_name)],
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

print(t.to_json())
