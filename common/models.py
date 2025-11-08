import uuid
from django.db import models


class Asset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    s3_key = models.CharField(max_length=500, unique=True, verbose_name='S3 Key')
    original_name = models.CharField(max_length=255, verbose_name='원본 파일명')
    content_type = models.CharField(max_length=100, verbose_name='Content Type')
    file_size = models.BigIntegerField(verbose_name='파일 크기 (bytes)')
    url = models.URLField(verbose_name='파일 URL')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'assets'
        verbose_name = '에셋'
        verbose_name_plural = '에셋'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.original_name} ({self.s3_key})"
