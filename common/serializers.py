from rest_framework import serializers

from .models import Asset


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = ['id', 'url', 'file_name', 'file_size', 'content_type']
        read_only_fields = ['id']
    
    file_name = serializers.CharField(source='original_name', read_only=True)

