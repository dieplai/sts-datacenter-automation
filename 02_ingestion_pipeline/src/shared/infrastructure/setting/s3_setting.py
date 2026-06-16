"""AWS S3 settings."""

from shared.infrastructure.setting.base_setting import AppBaseSetting


class S3Setting(AppBaseSetting):
    """Settings for AWS S3 integration."""

    s3_bucket: str
    s3_region: str = "ap-southeast-1"
    aws_access_key_id: str
    aws_secret_access_key: str