"""S3 client construction for the ai-worker."""

from storage import CloudS3, StorageConfig

from app.config.settings import Settings


def build_cloud_s3(settings: Settings) -> CloudS3:
    """Build a configured object-storage client from application settings."""
    return CloudS3(
        StorageConfig(
            s3_endpoint_url=settings.s3_endpoint_url,
            s3_key_id=settings.s3_key_id,
            s3_key_secret=settings.s3_key_secret,
            s3_bucket_name=settings.s3_bucket_name,
            s3_region=settings.s3_region,
            s3_tenant_id=settings.s3_tenant_id,
        )
    )