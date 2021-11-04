import logging
from typing import IO, Union

import boto3
import botocore.exceptions
from botocore.config import Config
from starlette import status

from settings import settings

LINK_EXPIRATION_TIME_SEC = 60
STORAGE_ACCOUNT_IMAGE_BUCKET = 'account-images'
STORAGE_CHAT_IMAGE_BUCKET = 'chat-images'

logger = logging.getLogger(__name__)


class CloudStorage:
    def __init__(self):
        self._client = boto3.client(
            "s3",
            aws_access_key_id=settings.STORAGE_ACCESS_KEY,
            aws_secret_access_key=settings.STORAGE_SECRET_KEY,
            region_name=settings.STORAGE_REGION,
            endpoint_url=settings.STORAGE_ENDPOINT,
            config=Config(signature_version="s3v4")
        )

    def initialize_buckets(self):
        self._initialize_bucket(STORAGE_ACCOUNT_IMAGE_BUCKET)
        self._initialize_bucket(STORAGE_CHAT_IMAGE_BUCKET)

    def _initialize_bucket(self, bucket_name: str):
        logger.info(f"Validating cloud storage bucket {bucket_name}")
        try:
            self._client.head_bucket(Bucket=bucket_name)
        except botocore.exceptions.ClientError as e:
            if int(e.response['Error']['Code']) == status.HTTP_404_NOT_FOUND:
                logger.info(f"Bucket {bucket_name} "
                            f"was not found, creating")
                self._client.create_bucket(Bucket=bucket_name)
            else:
                raise

    # TODO all sorts of error handling
    def upload_image(self, image_id: str, file_content: Union[IO, bytes]):
        self._client.put_object(
            Bucket=STORAGE_ACCOUNT_IMAGE_BUCKET, Key=image_id,
            Body=file_content)

    def upload_chat_image(self, image_id: str, file_content: Union[IO, bytes]):
        self._client.put_object(
            Bucket=STORAGE_CHAT_IMAGE_BUCKET, Key=image_id,
            Body=file_content)

    def get_image_url(self, image_id: str) -> str:
        # TODO add a check for file existence
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": STORAGE_ACCOUNT_IMAGE_BUCKET, "Key": image_id},
            ExpiresIn=LINK_EXPIRATION_TIME_SEC,
        )

    def get_chat_image_url(self, image_id: str) -> str:
        # TODO add a check for file existence
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": STORAGE_CHAT_IMAGE_BUCKET, "Key": image_id},
            ExpiresIn=LINK_EXPIRATION_TIME_SEC,
        )

    def delete_image(self, image_id: str):
        # TODO any validations that objects were actually deleted?
        self._client.delete_objects(
            Bucket=STORAGE_ACCOUNT_IMAGE_BUCKET,
            Delete={'Objects': [{'Key': image_id}]})


storage_client = CloudStorage()
