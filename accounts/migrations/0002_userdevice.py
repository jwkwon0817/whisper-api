# Generated migration for UserDevice model

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserDevice',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('device_name', models.CharField(max_length=100, verbose_name='기기 이름')),
                ('device_fingerprint', models.CharField(max_length=255, unique=True, verbose_name='기기 지문')),
                ('encrypted_private_key', models.TextField(verbose_name='암호화된 개인키 (JSON)')),
                ('is_primary', models.BooleanField(default=False, verbose_name='주 기기 여부')),
                ('last_active', models.DateTimeField(auto_now=True, verbose_name='마지막 활동 시간')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='devices', to=settings.AUTH_USER_MODEL, verbose_name='사용자')),
            ],
            options={
                'verbose_name': '사용자 기기',
                'verbose_name_plural': '사용자 기기',
                'db_table': 'user_devices',
                'ordering': ['-last_active'],
            },
        ),
        migrations.AddIndex(
            model_name='userdevice',
            index=models.Index(fields=['user', 'is_primary'], name='user_device_user_id_is_primary_idx'),
        ),
        migrations.AddIndex(
            model_name='userdevice',
            index=models.Index(fields=['device_fingerprint'], name='user_device_device_fingerprint_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='userdevice',
            unique_together={('user', 'device_fingerprint')},
        ),
    ]
