from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.s3_utils import S3Uploader


class FileUploadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="파일 업로드",
        description="이미지 또는 파일을 S3에 업로드하고 Asset 정보를 반환합니다.",
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'file': {
                        'type': 'string',
                        'format': 'binary',
                        'description': '업로드할 파일'
                    },
                    'folder': {
                        'type': 'string',
                        'description': 'S3 폴더명 (기본값: chat)',
                        'default': 'chat'
                    }
                },
                'required': ['file']
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string', 'format': 'uuid'},
                    'url': {'type': 'string', 'format': 'uri'},
                    'file_name': {'type': 'string'},
                    'file_size': {'type': 'integer'},
                    'content_type': {'type': 'string'}
                }
            },
            400: {'description': '파일이 없거나 업로드 실패'}
        }
    )
    def post(self, request):
        file = request.FILES.get('file')
        folder = request.data.get('folder', 'chat')
        
        if not file:
            return Response(
                {'error': '파일이 제공되지 않았습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            uploader = S3Uploader()
            asset, _ = uploader.upload_file(file, folder=folder)
            
            return Response({
                'id': str(asset.id),
                'url': asset.url,
                'file_name': asset.original_name,
                'file_size': asset.file_size,
                'content_type': asset.content_type
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': f'파일 업로드 실패: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
