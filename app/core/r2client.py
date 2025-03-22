import boto3
from app.core.config import settings

# Cloudflare R2 Read/Write
r2client = boto3.client(
    service_name="s3",
    endpoint_url=settings.R2_ENDPOINT_URL,
    aws_access_key_id=settings.R2_ACCESS_KEY,
    aws_secret_access_key=settings.R2_SECRET,
    region_name="auto",  # Must be one of: wnam, enam, weur, eeur, apac, auto
)
