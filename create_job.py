import boto3
import datetime
client = boto3.client('sagemaker', region_name='us-west-2')

response = client.create_training_job(
  TrainingJobName=datetime.datetime.now().strftime("%y-%m-%d-%H-%M"),
  HyperParameters={
    "test_data":"/opt/ml/input/data/train/adult.test",
    "train_data":"/opt/ml/input/data/train/adult.data",
    "model_type": "wide",
    "train_epochs": "40",
    "epochs_per_eval": "2",
    "batch_size":"40"
    },
    AlgorithmSpecification={
      "TrainingInputMode": "File",
      "TrainingImage": "007038732177.dkr.ecr.us-west-2.amazonaws.com/tf-dock"
    },
    RoleArn="arn:aws:iam::007038732177:role/service-role/AmazonSageMaker-ExecutionRole-20180116T121112",
    InputDataConfig=[
        {
            "CompressionType": "None",
            "ChannelName": "train",
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3DataDistributionType": "FullyReplicated",
                    "S3Uri": "s3://fcandela-sagemaker-census/"
                }
            },
            "RecordWrapperType": "None"
        }
    ],
    OutputDataConfig={
        "KmsKeyId": "",
        "S3OutputPath": "s3://fcandela-sagemaker-census/output/"
    },
    ResourceConfig={
        "VolumeSizeInGB": 1,
        "InstanceCount": 1,
        "InstanceType": "ml.p2.8xlarge"
    },
    StoppingCondition={
        "MaxRuntimeInSeconds": 86400
    }
)
print response
