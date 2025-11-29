import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models

User = get_user_model()


class Friend(models.Model):
    STATUS_CHOICES = [
        ('pending', '대기중'),
        ('accepted', '수락됨'),
        ('rejected', '거절됨'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_friend_requests', verbose_name='요청자')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_friend_requests', verbose_name='수신자')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name='상태')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'friends'
        verbose_name = '친구'
        verbose_name_plural = '친구'
        unique_together = [['requester', 'receiver']]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['requester', 'status']),
            models.Index(fields=['receiver', 'status']),
        ]
    
    def __str__(self):
        return f"{self.requester.name} -> {self.receiver.name} ({self.status})"
    
    def clean(self):
        if self.requester == self.receiver:
            raise ValidationError('자기 자신에게 친구 요청을 보낼 수 없습니다.')
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
