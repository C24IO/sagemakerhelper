A small set of scripts that bootstrap a machine learning ci/cd pipeline that takes the contents of a repo that contains a docker file, a buildspec file, the train and serve files, and a manifiest file to create a docker container that then gets sent to sagemaker for execution.

hydrate.py is a file that depends on toropshere to create the cfn template to instantiate the codepipeline and all it's dependent servies.
pipeline.json is the output of a run of hydrate with it's variables left as it's been commited to this repo.
sageDispatch.py contains the lambda function that is invoked by the pipeline. 
sageDispatch.zip is a zip that you should shove into an s3 bucket avaialble to the pipeline. Replace the value of 'lambda_function_bucket' in hydrate.py with the bucket name into which you put this file so that your cloudformation template can grab it.
