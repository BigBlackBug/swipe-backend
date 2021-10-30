import logging
from typing import IO, Union

import boto3
import botocore.exceptions
from botocore.config import Config
from starlette import status

from settings import settings

LINK_EXPIRATION_TIME_SEC = 60
STORAGE_IMAGE_BUCKET = 'account-images'
STORAGE_ENDPOINT = 'https://storage.yandexcloud.net'
STORAGE_REGION = "ru-central1"

logger = logging.getLogger(__name__)


class CloudStorage:
    def __init__(self):
        self._client = boto3.client(
            "s3",
            aws_access_key_id=settings.STORAGE_ACCESS_KEY,
            aws_secret_access_key=settings.STORAGE_SECRET_KEY,
            region_name=STORAGE_REGION,
            endpoint_url=STORAGE_ENDPOINT,
            config=Config(signature_version="s3v4")
        )

    def initialize_buckets(self):
        logger.info(f"Validating cloud storage bucket {STORAGE_IMAGE_BUCKET}")
        try:
            self._client.head_bucket(Bucket=STORAGE_IMAGE_BUCKET)
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == status.HTTP_404_NOT_FOUND:
                logger.info(f"Bucket {STORAGE_IMAGE_BUCKET} "
                            f"was not found, creating")
                self._client.create_bucket(Bucket=STORAGE_IMAGE_BUCKET)
            else:
                raise

    # TODO all sorts of error handling
    def upload_image(self, image_id: str, file_content: Union[IO, bytes]):
        self._client.put_object(
            Bucket=STORAGE_IMAGE_BUCKET, Key=image_id, Body=file_content)

    def get_image_url(self, image_id: str) -> str:
        # TODO add a check for file existence
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": STORAGE_IMAGE_BUCKET, "Key": image_id},
            ExpiresIn=LINK_EXPIRATION_TIME_SEC,
        )

    def delete_image(self, image_id: str):
        # TODO any validations that objects were actually deleted?
        self._client.delete_objects(
            Bucket=STORAGE_IMAGE_BUCKET,
            Delete={'Objects': [{'Key': image_id}]})


storage_client = CloudStorage()
