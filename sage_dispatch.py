import boto3
import json
import tempfile
import zipfile
import datetime

code_pipeline = boto3.client('codepipeline')
s3 = boto3.client('s3')
sagemaker = boto3.client('sagemaker')

def lambda_handler(event, context):
  print event
  job_id = event['CodePipeline.job']['id']
  job_data = event['CodePipeline.job']['data']
  artifacts = job_data['inputArtifacts']
  manifest = get_manifest_dictionary(artifacts)
  manifest['Tags']=[{'Key':'job_id','Value':job_id}]
  result = send_to_training(manifest)
  if 'TrainingJobArn' in result:
    put_job_success(job_id, 'started job: ' + result['TrainingJobArn'])
  else:
   put_job_failure(job_id, 'Sagemaker training job failed.')

def send_to_training(manifest):
  suffix = datetime.datetime.now().strftime("%y-%m-%d-%H-%M")
  response = sagemaker.create_training_job(
    TrainingJobName=manifest['TrainingJobName'] + "-" + suffix,
    HyperParameters=manifest['HyperParameters'],
    AlgorithmSpecification=manifest['AlgorithmSpecification'],
    RoleArn=manifest['RoleArn'],
    InputDataConfig=manifest['InputDataConfig'],
    OutputDataConfig=manifest['OutputDataConfig'],
    ResourceConfig=manifest['ResourceConfig'],
    StoppingCondition=manifest['StoppingCondition'],
    Tags=manifest['Tags']
    )
  return response


def get_manifest_dictionary(artifacts):
  manifiest_bucket = ''
  manifiest_object = ''
  manifest_file = ''
  for artifact in artifacts:
    if 'MyAppBuild' in artifact['name']:
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
  """Notify CodePipeline of a successful job

  Args:
      job: The CodePipeline job ID
      message: A message to be logged relating to the job status

  Raises:
      Exception: Any exception thrown by .put_job_success_result()

  """
  print('Putting job success')
  print(message)
  code_pipeline.put_job_success_result(jobId=job)

def put_job_failure(job, message):
  """Notify CodePipeline of a failed job

  Args:
      job: The CodePipeline job ID
      message: A message to be logged relating to the job status

  Raises:
      Exception: Any exception thrown by .put_job_failure_result()

  """
  print('Putting job failure')
  print(message)
  code_pipeline.put_job_failure_result(jobId=job, failureDetails={'message': message, 'type': 'JobFailed'})

