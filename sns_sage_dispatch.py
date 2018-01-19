import os
import boto3
import json
import subprocess

def handler(event, context):
  sns_message = event['Records'][0]['Sns']['Message']
  message = json.loads(sns_message)
  region = message['Records'][0]['awsRegion']
  arn = message['Records'][0]['eventSourceARN']
  repo = arn.split(":")[-1]
  clone_url = 'https://git-codecommit.%s.amazonaws.com/v1/repos/%s' % (region, repo)
  print clone_url
