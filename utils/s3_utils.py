import os
import uuid
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from accounts.models import Asset


class S3Uploader:
    """S3 파일 업로드 유틸리티 클래스"""
    
    def __init__(self):
        s3_config = {
            'aws_access_key_id': settings.S3_ACCESS_KEY_ID,
            'aws_secret_access_key': settings.S3_SECRET_ACCESS_KEY,
            'region_name': settings.S3_REGION,
        }
        
        if settings.S3_ENDPOINT:
            s3_config['endpoint_url'] = settings.S3_ENDPOINT
        
        self.s3_client = boto3.client('s3', **s3_config)
        self.bucket_name = settings.S3_BUCKET_NAME
        
        if settings.S3_PUBLIC_URL:
            self.base_url = settings.S3_PUBLIC_URL.rstrip('/')
        else:
            self.base_url = f"https://{self.bucket_name}.s3.{settings.S3_REGION}.amazonaws.com"
    
    def _generate_unique_filename(self, original_filename: str) -> str:
        """UUID를 사용하여 고유한 파일명 생성"""
        ext = os.path.splitext(original_filename)[1]
        unique_filename = f"{uuid.uuid4()}{ext}"
        return unique_filename
    
    def upload_file(
        self,
        file: UploadedFile,
        folder: str = 'profiles',
        content_type: Optional[str] = None
    ) -> Tuple[Asset, str]:
        original_filename = file.name
        file_size = file.size
        
        if not content_type:
            content_type = file.content_type or 'application/octet-stream'
        
        unique_filename = self._generate_unique_filename(original_filename)
        s3_key = f"{folder}/{unique_filename}"
        
        try:
            file.seek(0)
            
            self.s3_client.upload_fileobj(
                file,
                self.bucket_name,
                s3_key,
                ExtraArgs={
                    'ContentType': content_type,
                    'ACL': 'public-read'
                }
            )
            
            file_url = f"{self.base_url}/{s3_key}"
            
            asset = Asset.objects.create(
                s3_key=s3_key,
                original_name=original_filename,
                content_type=content_type,
                file_size=file_size,
                url=file_url
            )
            
            return asset, file_url
            
        except ClientError as e:
            raise Exception(f"S3 업로드 실패: {str(e)}")
        except Exception as e:
            raise Exception(f"파일 업로드 중 오류 발생: {str(e)}")
    
    def delete_file(self, s3_key: str) -> bool:
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return True
        except ClientError as e:
            print(f"S3 파일 삭제 실패: {str(e)}")
            return False
    
    def delete_asset(self, asset: Asset) -> bool:
        success = self.delete_file(asset.s3_key)
        if success:
            asset.delete()
        return success

