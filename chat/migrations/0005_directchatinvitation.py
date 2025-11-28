# Generated migration for DirectChatInvitation model

import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0004_add_self_encrypted_session_key'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DirectChatInvitation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('pending', '대기중'), ('accepted', '수락됨'), ('rejected', '거절됨'), ('cancelled', '취소됨')], default='pending', max_length=10, verbose_name='상태')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('invitee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='received_direct_invitations', to=settings.AUTH_USER_MODEL, verbose_name='초대받은 사람')),
                ('inviter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sent_direct_invitations', to=settings.AUTH_USER_MODEL, verbose_name='초대자')),
                ('room', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='direct_invitations', to='chat.chatroom', verbose_name='채팅방')),
            ],
            options={
                'verbose_name': '1:1 채팅 초대',
                'verbose_name_plural': '1:1 채팅 초대',
                'db_table': 'direct_chat_invitations',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='directchatinvitation',
            index=models.Index(fields=['invitee', 'status'], name='direct_chat_invitee_status_idx'),
        ),
        migrations.AddIndex(
            model_name='directchatinvitation',
            index=models.Index(fields=['inviter', 'invitee', 'status'], name='direct_chat_inviter_invitee_status_idx'),
        ),
        migrations.AddConstraint(
            model_name='directchatinvitation',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status', 'pending')),
                fields=('inviter', 'invitee'),
                name='unique_pending_direct_invitation'
            ),
        ),
    ]

