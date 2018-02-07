from troposphere.constants import NUMBER
from troposphere import Output, Ref, Template, Parameter, GetAtt, Join
from troposphere.kms import Key
from troposphere.s3 import Bucket, ServerSideEncryptionByDefault, BucketEncryption, ServerSideEncryptionRule
from troposphere.codecommit import Repository
from troposphere.awslambda import Function, Code, MEMORY_VALUES
from troposphere.iam import Role, Policy
from troposphere.codepipeline import (
    Pipeline, Stages, Actions, ActionTypeID, OutputArtifacts, InputArtifacts,
    ArtifactStore, DisableInboundStageTransitions)



project_name = 'cloudMlPipeline'
account = '007038732177'
prefix = account + project_name
input_bucket = prefix + 'Input'
output_bucket = prefix + 'Output'
pipeline_name = prefix + 'Pipeline'
repo_name = prefix + 'Repo'
build_name = prefix + 'Build'
lambda_function_name = 'sageDispatch'
lambda_function_bucket = account + 'Lambda'
lambda_function_key = lambda_function_name + ".py"
project_kms_key = project_name + 'Key'
root_arn = "arn:aws:iam::" + account + ":root"

t = Template()

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
          "Principal": {"AWS":root_arn},
          "Action": "kms:*",
          "Resource": "*"
        }]
    }
))



t.add_description("This template hydrates a machine learning pipeline.")

bucket_encryption_config = ServerSideEncryptionByDefault(KMSMasterKeyID=GetAtt("project_key", "Arn"), SSEAlgorithm='aws:kms')
bucket_encryption_rule = ServerSideEncryptionRule(ServerSideEncryptionByDefault=bucket_encryption_config)
bucket_encryption = BucketEncryption(ServerSideEncryptionConfiguration=[bucket_encryption_rule])

input_bucket = t.add_resource(Bucket('InputBucket', AccessControl='Private', BucketName=input_bucket.lower(), BucketEncryption=bucket_encryption))
output_bucket = t.add_resource(Bucket('OutputBucket', AccessControl='Private', BucketName=output_bucket.lower(), BucketEncryption=bucket_encryption))

t.add_output(Output('InputBucket', Value=Ref(input_bucket), Description='Name of input S3 bucket'))
t.add_output(Output('OutputBucket', Value=Ref(output_bucket), Description='Name of output S3 bucket'))

repo = t.add_resource(Repository('Repository', RepositoryDescription='ML repo', RepositoryName=repo_name))
t.add_output(Output('Repository', Value=Ref(repo), Description='ML repo'))

artifactStore = ArtifactStore(Location='codepipeline-us-west-2-007038732177', Type='S3')

"""
Add IAM roles here
Codepipeline source iam role
Codepipeline build iam role
Codepipeline invoke iam role
Codepipeline role
Add bucket policy

{
    "Version": "2012-10-17",
    "Id": "SSEAndSSLPolicy",
    "Statement": [
        {
            "Sid": "DenyUnEncryptedObjectUploads",
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:PutObject",
            "Resource": "arn:aws:s3:::codepipeline-us-east-2-1234567890/*",
            "Condition": {
                "StringNotEquals": {
                    "s3:x-amz-server-side-encryption": "aws:kms"
                }
            }
        },
        {
            "Sid": "DenyInsecureConnections",
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:*",
            "Resource": "arn:aws:s3:::codepipeline-us-east-2-1234567890/*",
            "Condition": {
                "Bool": {
                    "aws:SecureTransport": false
                }
            }
        }
    ]
}


"""

CodepipelineExecutionRole = t.add_resource(Role(
    "CodepipelineExecutionRole",
    Path="/",
    Policies=[Policy(
        PolicyName="CodepipelineExecutionRole",
        PolicyDocument={
            "Version": "2012-10-17",
            "Statement": [{
            "Action": ["kms:Decrypt"],
            "Resource": GetAtt("project_key", "Arn"),
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
                "s3:DeleteObject"
            ],
            "Resource": [
                Join('', [GetAtt("InputBucket", "Arn"), "/*"]),
                Join('', [GetAtt("OutputBucket", "Arn"), "/*"])
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
        {   "Action": [
            "codebuild:BatchGetBuilds",
            "codebuild:StartBuild"
            ],
            "Resource": "*",
            "Effect": "Allow"
        }]
        })],
    AssumeRolePolicyDocument={
        "Version": "2012-10-17",
        "Statement": [{
            "Action": ["sts:AssumeRole"],
            "Effect": "Allow",
            "Principal": {
                "Service": ["codepipeline.amazonaws.com"]
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
                    "Resource": GetAtt("project_key", "Arn"),
                    "Effect": "Allow"
                },
{
                    "Action": ["codepipeline:PutJobFailureResult, codepipeline:PutJobSuccessResult"],
                    "Resource": "*",
                    "Effect": "Allow"
                },
{
                    "Action": ["s3:GetObject"],
                    "Resource": Join('', [GetAtt("InputBucket", "Arn"), "/*"]),
                    "Effect": "Allow"
                },
{
                    "Action": ["sagemaker:CreateTrainingJob"],
                    "Resource": Join('', [GetAtt("AppPipeline", "Arn"), "/", project_name, "*"]),
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
func = t.add_resource(Function(
    lambda_function_name,
    Code=Code(
        S3Bucket=lambda_function_bucket,
        S3Key=lambda_function_key
    ),
    FunctionName=lambda_function_name,
    Handler="main.handler",
    Role=GetAtt("LambdaExecutionRole", "Arn"),
    Runtime="python2.7",
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
  RoleArn=GetAtt("CodepipelineExecutionRole", "Arn"),
  RunOrder=1,
  OutputArtifacts=[OutputArtifacts(Name='source_action_output')]
  )

build_action = Actions(
  ActionTypeId=build_action_id,
  Configuration={
                            "ProjectName": build_name
                        },
  InputArtifacts=[InputArtifacts(Name='source_action_output')],
  Name='Build',
  RoleArn=GetAtt("CodepipelineExecutionRole", "Arn"),
  RunOrder=1,
  OutputArtifacts=[OutputArtifacts(Name='build_action_output')]
  )

invoke_action = Actions(
  ActionTypeId=invoke_action_id,
  Configuration={
                            "FunctionName": lambda_function_name 
                        },
  InputArtifacts=[InputArtifacts(Name='MyApp')],
  Name='Train',
  RoleArn=GetAtt("CodepipelineExecutionRole", "Arn"),
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
    "AppPipeline",
    RoleArn=GetAtt("CodepipelineExecutionRole", "Arn"),
    ArtifactStore=artifactStore,
    Stages=[source_stage, build_stage, invoke_action]))

print(t.to_json())
