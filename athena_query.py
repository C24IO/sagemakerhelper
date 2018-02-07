import boto3
import time
import pandas as pd

client = boto3.client('athena')
s3_client = boto3.client('s3')

sql_query_string = 'SELECT * FROM "census"."adult_data_manual" limit 11'
query_bucket = 'aws-athena-query-results-007038732177-us-west-2'
query_bucket_url = 's3://' + query_bucket + '/'
response = client.start_query_execution(
        QueryString=sql_query_string,
        QueryExecutionContext={
            'Database': 'census'
        },
        ResultConfiguration={
            'OutputLocation': query_bucket_url 
        }
    )
query_id = response['QueryExecutionId']

#response = client.get_query_results(QueryExecutionId=query_id)
while True:
  response = client.get_query_execution(QueryExecutionId=query_id)  
  if response['QueryExecution']['Status']['State'] in 'SUCCEEDED':
    key = response['QueryExecution']['ResultConfiguration']['OutputLocation'].split("/")[-1] 
    obj = s3_client.get_object(Bucket=query_bucket, Key=key)
    print obj['Body'].read()
    break
  else:
    time.sleep(2)
