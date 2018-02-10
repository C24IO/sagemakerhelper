import boto3
import json
import tempfile
import zipfile
import datetime
import os

code_pipeline = boto3.client('codepipeline')
s3 = boto3.client('s3')
sagemaker = boto3.client('sagemaker')
codecommit = boto3.client('codecommit')


def lambda_handler(event, context):
  #print event
  job_id = event['CodePipeline.job']['id']
  try:
    job_data = event['CodePipeline.job']['data']
    artifacts = job_data['inputArtifacts']
    print artifacts
    manifest = get_manifest_dictionary(artifacts)
    result = send_to_training(manifest)
    if 'TrainingJobArn' in result:
      put_job_success(job_id, 'started job: ' + result['TrainingJobArn'])
    else:
     put_job_failure(job_id, 'Sagemaker training job failed.')
  except:
    code_pipeline.put_job_failure_result(jobId=job_id, failureDetails={'message': 'some sort of exception', 'type': 'JobFailed'})

def send_to_training(manifest):
  suffix = datetime.datetime.now().strftime("%y-%m-%d-%H-%M")
  commit_id = codecommit.get_branch(repositoryName=os.environ['CODE_COMMIT_REPO'], branchName='master')['branch'][
    'commitId']

  response = sagemaker.create_training_job(
    TrainingJobName=manifest['TrainingJobName'] + "-" + suffix,
    HyperParameters=manifest['HyperParameters'],
    AlgorithmSpecification={
      'TrainingInputMode': 'File',
      'TrainingImage': os.environ['TRAINING_IMAGE'] + ":" + commit_id
    },
    RoleArn=os.environ['SAGEMAKER_ROLE_ARN'],
    InputDataConfig=[
        {
            "CompressionType": "None",
            "ChannelName": "train",
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3DataDistributionType": "FullyReplicated",
                    "S3Uri": os.environ['INPUT_BUCKET']
                }
            },
            "RecordWrapperType": "None"
        }
    ],
    OutputDataConfig={
        "KmsKeyId": os.environ['BUCKET_KEY_ARN'].split('/')[-1],
        "S3OutputPath": os.environ['OUTPUT_BUCKET']
    },
    ResourceConfig=manifest['ResourceConfig'],
    StoppingCondition=manifest['StoppingCondition'],
    Tags=[{'Key':'commitID','Value':commit_id}]
    )
  return response


def get_manifest_dictionary(artifacts):
  manifiest_bucket = ''
  manifiest_object = ''
  manifest_file = ''
  for artifact in artifacts:
    if os.environ['APP_BUNDLE'] in artifact['name']:
      manifiest_bucket = artifact['location']['s3Location']['bucketName']
      manifiest_key = artifact['location']['s3Location']['objectKey']
      manifest_file = get_manifest_from_s3(manifiest_bucket, manifiest_key)
      print manifest_file
  return json.loads(manifest_file)

def get_manifest_from_s3(bucket, key):
  tmp_file = tempfile.NamedTemporaryFile()
  with tempfile.NamedTemporaryFile() as tmp_file:
    s3.download_file(bucket, key, tmp_file.name)
    with zipfile.ZipFile(tmp_file.name, 'r') as zip:
      return zip.read('manifest.json')

def put_job_success(job, message):
  print('Putting job success')
  print(message)
  code_pipeline.put_job_success_result(jobId=job)

def put_job_failure(job, message):
  print('Putting job failure')
  print(message)
  code_pipeline.put_job_failure_result(jobId=job, failureDetails={'message': message, 'type': 'JobFailed'})

