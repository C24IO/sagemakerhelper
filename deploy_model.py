import boto3
import datetime
client = boto3.client('sagemaker', region_name='us-west-2')

project_name = 'census'
environment = 'production'
version = '1'
deploy_name = project_name + "-" + environment
variant = project_name + "-v" + version

training_job_name = 'census-18-01-23-18-54'
training_job = client.describe_training_job(TrainingJobName=training_job_name)
training_tags = client.list_tags(ResourceArn=training_job['TrainingJobArn'])
model = client.create_model(
    ModelName=training_job['TrainingJobName'],
    PrimaryContainer={
        'Image': training_job['AlgorithmSpecification']['TrainingImage']
    },
    ExecutionRoleArn=training_job['RoleArn'],
    Tags=training_tags['Tags'] 
)
endpoint_config = client.create_endpoint_config(
    EndpointConfigName=variant,
    ProductionVariants=[
        {
            'VariantName': variant,
            'ModelName': training_job['TrainingJobName'],
            'InitialInstanceCount': 1,
            'InstanceType': 'ml.m4.xlarge'
        },
    ],
    Tags=training_tags['Tags']
)
print endpoint_config 
