import boto3

code_pipeline = boto3.client('codepipeline')

def handler(event, context):
  code_pipeline.start_pipeline_execution(name='ml_pipeline')
