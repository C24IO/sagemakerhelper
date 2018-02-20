import boto3
import json
import tempfile
import zipfile
import datetime
import os
import logging

log_level = os.environ['LOG_LEVEL']
formatter = logging.Formatter('[%(asctime)s] p%(process)s {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s',
                              '%m-%d %H:%M:%S')
if log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
  log_level = 'WARNING'
log = logging.getLogger()
log.setLevel(log_level)
ch = logging.StreamHandler()
ch.setLevel(log_level)
log.addHandler(ch)
ch.setFormatter(formatter)

log.info("The log level is %s", log_level)

code_pipeline = boto3.client('codepipeline')
s3 = boto3.client('s3')
s3resource = boto3.resource('s3')
sagemaker = boto3.client('sagemaker')
codecommit = boto3.client('codecommit')


def lambda_handler(event, context):
  log.debug(event)

  try:
    job_id = event['CodePipeline.job']['id']
    job_data = event['CodePipeline.job']['data']
    artifacts = job_data['inputArtifacts']
    log.debug(artifacts)
    manifest = get_manifest_dictionary(artifacts)
    log.info("got manifest and sending job")
    result = send_to_training(manifest)
    log.debug(result)
    if 'TrainingJobArn' in result:
      put_job_success(job_id, 'started job: ' + result['TrainingJobArn'])
    else:
      put_job_failure(job_id, 'Sagemaker training job failed.')
  except Exception as e:
    log.critical(e)
    code_pipeline.put_job_failure_result(jobId=job_id,
                                         failureDetails={'message': 'some sort of exception', 'type': 'JobFailed'})


def send_to_training(manifest):
  suffix = datetime.datetime.now().strftime("%y-%m-%d-%H-%M")
  commit_id = codecommit.get_branch(repositoryName=os.environ['CODE_COMMIT_REPO'], branchName='master')['branch'][
    'commitId']
  try:
    training_object = s3resource.Object(os.environ['INPUT_BUCKET'].split('/')[-2],
                                        manifest['HyperParameters']['train_data'].split('/')[-1])
    testing_object = s3resource.Object(os.environ['INPUT_BUCKET'].split('/')[-2],
                                       manifest['HyperParameters']['test_data'].split('/')[-1])
  except Exception as e:
    log.critical(e)

  try:
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
      Tags=[{'Key': 'commitID', 'Value': commit_id},
            {'Key': 'training_data_version', 'Value': training_object.version_id},
            {'Key': 'testing_data_version', 'Value': testing_object.version_id}]
    )
  except Exception as e:
    log.critical(e)
  return response


def get_manifest_dictionary(artifacts):
  manifest_file = ''
  for artifact in artifacts:
    if os.environ['APP_BUNDLE'] in artifact['name']:
      manifiest_bucket = artifact['location']['s3Location']['bucketName']
      manifiest_key = artifact['location']['s3Location']['objectKey']
      manifest_file = get_manifest_from_s3(manifiest_bucket, manifiest_key)
  return json.loads(manifest_file)


def get_manifest_from_s3(bucket, key):
  tmp_file = tempfile.NamedTemporaryFile()
  with tempfile.NamedTemporaryFile() as tmp_file:
    s3.download_file(bucket, key, tmp_file.name)
    with zipfile.ZipFile(tmp_file.name, 'r') as zip:
      return zip.read('manifest.json')


def put_job_success(job, message):
  log.info('Putting job success')
  log.debug(message)
  try:
    code_pipeline.put_job_success_result(jobId=job)
  except Exception as e:
    log.critical(e)


def put_job_failure(job, message):
  log.info('Putting job failure')
  log.debug(message)
  try:
    code_pipeline.put_job_failure_result(jobId=job, failureDetails={'message': message, 'type': 'JobFailed'})
  except Exception as e:
    log.critical(e)