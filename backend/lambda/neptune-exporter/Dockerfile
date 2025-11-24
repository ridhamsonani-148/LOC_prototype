FROM public.ecr.aws/lambda/python:3.12

# Copy requirements
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# Set the CMD to your handler
CMD [ "lambda_function.lambda_handler" ]
