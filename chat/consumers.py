import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .models import ChatRoom, ChatRoomMember, Message
from .serializers import MessageSerializer

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    """
    채팅 WebSocket Consumer
    
    URL: ws://<host>/ws/chat/<room_id>/?token=<jwt_token>
    
    메시지 형식:
    - 클라이언트 -> 서버:
        {
            "type": "chat_message",
            "message_type": "text|image|file",
            "content": "메시지 내용 (그룹 채팅)",
            "encrypted_content": "암호화된 메시지 (AES 암호화, 1:1 채팅)",
            "encrypted_session_key": "암호화된 세션 키 (RSA 암호화, 상대방 공개키로 암호화, 하이브리드 방식)",
            "self_encrypted_session_key": "자기 암호화된 세션 키 (RSA 암호화, 내 공개키로 암호화, 양방향 암호화 지원)",
            "reply_to": "메시지 ID (답장 시)",
            "asset_id": "파일 ID (파일 전송 시)"
        }
        {
            "type": "typing",
            "is_typing": true
        }
        {
            "type": "read_receipt",
            "message_ids": ["id1", "id2", ...]
        }
    
    - 서버 -> 클라이언트:
        {
            "type": "chat_message",
            "message": {
                ...  # MessageSerializer 결과
                "encrypted_content": "base64_aes_encrypted_message",
                "encrypted_session_key": "base64_rsa_encrypted_session_key",
                "self_encrypted_session_key": "base64_rsa_encrypted_session_key"
            }
        }
        {
            "type": "typing",
            "user": {...},
            "is_typing": true
        }
        {
            "type": "read_receipt",
            "user_id": "...",
            "message_ids": [...]
        }
        {
            "type": "user_status",
            "user_id": "...",
            "status": "online|offline"
        }
        {
            "type": "error",
            "message": "에러 메시지"
        }
    """
    
    async def connect(self):
        """WebSocket 연결 시"""
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'
        
        # JWT 토큰 인증
        query_string = self.scope.get('query_string', b'').decode()
        query_params = dict(param.split('=') for param in query_string.split('&') if '=' in param)
        token = query_params.get('token')
        
        if not token:
            await self.close(code=4001)
            return
        
        # 토큰 검증 및 사용자 인증
        try:
            access_token = AccessToken(token)
            user_id = access_token.get('user_id')
            self.user = await self.get_user(user_id)
            
            if not self.user:
                await self.close(code=4002)
                return
                
        except (InvalidToken, TokenError) as e:
            await self.close(code=4003)
            return
        
        # 채팅방 존재 확인 및 멤버 권한 확인
        is_member = await self.check_room_membership()
        if not is_member:
            await self.close(code=4004)
            return
        
        # 채팅방 그룹에 참여
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # 다른 사용자들에게 온라인 상태 알림
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_status',
                'user_id': str(self.user.id),
                'status': 'online'
            }
        )
    
    async def disconnect(self, close_code):
        """WebSocket 연결 해제 시"""
        if hasattr(self, 'room_group_name') and hasattr(self, 'user'):
            # 오프라인 상태 알림 (인증된 사용자인 경우에만)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_status',
                    'user_id': str(self.user.id),
                    'status': 'offline'
                }
            )
            
            # 채팅방 그룹에서 나가기
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """클라이언트로부터 메시지 수신"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'chat_message':
                await self.handle_chat_message(data)
            elif message_type == 'typing':
                await self.handle_typing(data)
            elif message_type == 'read_receipt':
                await self.handle_read_receipt(data)
            else:
                await self.send_error('Unknown message type')
                
        except json.JSONDecodeError:
            await self.send_error('Invalid JSON')
        except Exception as e:
            await self.send_error(str(e))
    
    async def handle_chat_message(self, data):
        """채팅 메시지 처리"""
        print(f"\n{'='*80}")
        print(f"[ChatConsumer] handle_chat_message 호출됨 - User: {self.user.name}, Room: {self.room_id}")
        print(f"[ChatConsumer] 전체 data: {data}")
        print(f"{'='*80}\n")
        
        msg_type = data.get('message_type', 'text')
        content = data.get('content', '')
        encrypted_content = data.get('encrypted_content')
        encrypted_session_key = data.get('encrypted_session_key')
        self_encrypted_session_key = data.get('self_encrypted_session_key')
        reply_to_id = data.get('reply_to')
        asset_id = data.get('asset_id')
        
        print(f"[ChatConsumer] 메시지 데이터:")
        print(f"  - message_type: {msg_type}")
        print(f"  - content: {content[:50] if content else None}...")
        print(f"  - encrypted_content: {'있음' if encrypted_content else '없음'}")
        print(f"  - encrypted_session_key: {'있음' if encrypted_session_key else '없음'}")
        print(f"  - self_encrypted_session_key: {'있음' if self_encrypted_session_key else '없음'}")
        print(f"  - reply_to: {reply_to_id}")
        print(f"  - asset_id: {asset_id}")
        print(f"  - asset_id type: {type(asset_id)}")
        print(f"  - asset_id is None: {asset_id is None}")
        print(f"  - asset_id == '': {asset_id == ''}")
        
        # 메시지 생성
        message = await self.create_message(
            msg_type=msg_type,
            content=content,
            encrypted_content=encrypted_content,
            encrypted_session_key=encrypted_session_key,
            self_encrypted_session_key=self_encrypted_session_key,
            reply_to_id=reply_to_id,
            asset_id=asset_id
        )
        
        if message:
            print(f"[ChatConsumer] 메시지 생성 성공 - Message ID: {message.id}")
            # 메시지를 직렬화
            try:
                message_data = await self.serialize_message(message)
                print(f"[ChatConsumer] 메시지 직렬화 성공 - Message ID: {message.id}")
                print(f"[ChatConsumer] 직렬화된 데이터 키: {message_data.keys()}")
            except Exception as e:
                print(f"[ChatConsumer] 메시지 직렬화 실패: {e}")
                import traceback
                traceback.print_exc()
                await self.send_error(f"Message serialization failed: {str(e)}")
                return
            
            print(f"[ChatConsumer] 채팅방 그룹에 메시지 전송 - Room Group: {self.room_group_name}")
            # 채팅방의 모든 사용자에게 메시지 전송
            try:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': message_data
                    }
                )
                print(f"[ChatConsumer] group_send 완료 - Room Group: {self.room_group_name}")
                
                # 알림 전송 (Global Notification)
                await self.send_global_notification(message)
                
            except Exception as e:
                print(f"[ChatConsumer] group_send 실패: {e}")
                import traceback
                traceback.print_exc()
                await self.send_error(f"Failed to send message to group: {str(e)}")
        else:
            print(f"[ChatConsumer] 메시지 생성 실패 - message가 None입니다")
            await self.send_error("Failed to create message")
    
    async def handle_typing(self, data):
        """타이핑 인디케이터 처리"""
        is_typing = data.get('is_typing', False)
        
        # 자신을 제외한 채팅방 멤버들에게 타이핑 상태 전송
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user': {
                    'id': str(self.user.id),
                    'name': self.user.name,
                    'profile_image': self.user.profile_image if self.user.profile_image else None
                },
                'is_typing': is_typing,
                'sender_channel': self.channel_name
            }
        )
    
    async def handle_read_receipt(self, data):
        """읽음 확인 처리"""
        message_ids = data.get('message_ids', [])
        
        if message_ids:
            # 메시지 읽음 처리
            await self.mark_messages_as_read(message_ids)
            
            # 채팅방의 모든 사용자에게 읽음 확인 전송
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'read_receipt',
                    'user_id': str(self.user.id),
                    'message_ids': message_ids
                }
            )

    async def send_global_notification(self, message):
        """전체 알림 전송 (채팅방 멤버들에게)"""
        try:
            import uuid
            from django.utils import timezone
            
            # 채팅방 멤버 조회 (자신 제외)
            members = await self.get_room_members(self.room_id, exclude_user_id=self.user.id)
            
            # 알림 데이터 구성
            data_payload = {
                'room_id': self.room_id,
                'room_name': self.room_group_name, # 클라이언트에서 처리 가능하면 room_name 전달
                'message_id': str(message.id),
                'message_type': message.message_type,
                'sender': {
                    'id': str(self.user.id),
                    'name': self.user.name,
                    'profile_image': self.user.profile_image if self.user.profile_image else None
                }
            }
            
            # 메시지 내용 포함
            if message.message_type == 'text':
                if message.content:
                    # 그룹 채팅: 평문 전송
                    data_payload['content'] = message.content
                elif message.encrypted_content:
                    # 1:1 채팅: 암호화된 메시지는 프리뷰만 표시
                    data_payload['content'] = '새로운 메시지'
            elif message.message_type == 'image':
                data_payload['content'] = '📷 사진'
            elif message.message_type == 'file':
                data_payload['content'] = '📎 파일'
            
            # 최종 알림 구조
            notification_payload = {
                'id': str(uuid.uuid4()),
                'type': 'new_message',
                'created_at': timezone.now().isoformat(),
                'data': data_payload
            }
                
            for member in members:
                # 알림 전송
                await self.channel_layer.group_send(
                    f'notifications_{member.user.id}',
                    {
                        'type': 'notification',
                        'notification': notification_payload
                    }
                )
                print(f"[ChatConsumer] 알림 전송 완료 - User: {member.user.name}")
                
        except Exception as e:
            print(f"[ChatConsumer] 알림 전송 실패: {e}")
            import traceback
            traceback.print_exc()

    # 채널 레이어 이벤트 핸들러
    
    async def chat_message(self, event):
        """채팅 메시지 전송"""
        try:
            message_data = event['message']
            print(f"[ChatConsumer] chat_message 핸들러 호출 - User: {self.user.name}, Message ID: {message_data.get('id', 'unknown')}")
            
            response_data = {
                'type': 'chat_message',
                'message': message_data
            }
            
            # DjangoJSONEncoder를 사용하여 UUID 등 Django 객체 직렬화
            json_string = json.dumps(response_data, cls=DjangoJSONEncoder, ensure_ascii=False)
            print(f"[ChatConsumer] 전송할 데이터: {json_string[:200]}...")
            
            await self.send(text_data=json_string)
            print(f"[ChatConsumer] 메시지 전송 완료 - User: {self.user.name}")
        except Exception as e:
            print(f"[ChatConsumer] chat_message 핸들러 에러: {e}")
            import traceback
            traceback.print_exc()
    
    async def typing_indicator(self, event):
        """타이핑 인디케이터 전송 (자신 제외)"""
        # 자신의 타이핑 상태는 전송하지 않음
        if event.get('sender_channel') != self.channel_name:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'user': event['user'],
                'is_typing': event['is_typing']
            }))
    
    async def read_receipt(self, event):
        """읽음 확인 전송"""
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'user_id': event['user_id'],
            'message_ids': event['message_ids']
        }))
    
    async def message_update(self, event):
        """메시지 수정 전송"""
        await self.send(text_data=json.dumps({
            'type': 'message_update',
            'message': event['message']
        }, cls=DjangoJSONEncoder))
    
    async def message_delete(self, event):
        """메시지 삭제 전송"""
        await self.send(text_data=json.dumps({
            'type': 'message_delete',
            'message_id': event['message_id']
        }))
    
    async def user_status(self, event):
        """사용자 상태 전송"""
        # 자신의 상태는 전송하지 않음
        if event['user_id'] != str(self.user.id):
            await self.send(text_data=json.dumps({
                'type': 'user_status',
                'user_id': event['user_id'],
                'status': event['status']
            }))
    
    async def send_error(self, message):
        """에러 메시지 전송"""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message
        }))
    
    # 데이터베이스 작업 (동기 함수를 비동기로 래핑)
    
    @database_sync_to_async
    def get_user(self, user_id):
        """사용자 조회"""
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
    
    @database_sync_to_async
    def check_room_membership(self):
        """채팅방 멤버 권한 확인"""
        try:
            room = ChatRoom.objects.get(id=self.room_id)
            return ChatRoomMember.objects.filter(room=room, user=self.user).exists()
        except ChatRoom.DoesNotExist:
            return False
    
    @database_sync_to_async
    def get_room_members(self, room_id, exclude_user_id=None):
        """채팅방 멤버 조회"""
        try:
            room = ChatRoom.objects.get(id=room_id)
            members = ChatRoomMember.objects.filter(room=room)
            if exclude_user_id:
                members = members.exclude(user_id=exclude_user_id)
            return list(members.select_related('user'))
        except Exception:
            return []

    @database_sync_to_async
    def create_message(self, msg_type, content, encrypted_content, encrypted_session_key, self_encrypted_session_key, reply_to_id, asset_id):
        """메시지 생성"""
        try:
            room = ChatRoom.objects.get(id=self.room_id)
            
            print(f"[ChatConsumer] create_message 호출")
            print(f"  - room_type: {room.room_type}")
            print(f"  - msg_type: {msg_type}")
            print(f"  - encrypted_content: {'있음' if encrypted_content else '없음'}")
            print(f"  - asset_id: {asset_id}")
            
            # 채팅방 타입에 따른 검증
            # 이미지/파일 메시지는 encrypted_content가 없어도 OK
            if room.room_type == 'direct' and not encrypted_content and msg_type == 'text':
                print(f"[ChatConsumer] ❌ 1:1 채팅인데 텍스트 메시지에 encrypted_content 없음")
                return None
            if room.room_type == 'group' and encrypted_content:
                print(f"[ChatConsumer] ❌ 그룹 채팅인데 encrypted_content 있음")
                return None
            if room.room_type == 'group' and encrypted_session_key:
                print(f"[ChatConsumer] ❌ 그룹 채팅인데 encrypted_session_key 있음")
                return None
            if room.room_type == 'group' and self_encrypted_session_key:
                print(f"[ChatConsumer] ❌ 그룹 채팅인데 self_encrypted_session_key 있음")
                return None
            
            # 답장 대상 메시지
            reply_to = None
            if reply_to_id:
                try:
                    reply_to = Message.objects.get(id=reply_to_id, room=room)
                except Message.DoesNotExist:
                    pass
            
            # asset
            asset = None
            if asset_id:
                from common.models import Asset
                try:
                    asset = Asset.objects.get(id=asset_id)
                except Asset.DoesNotExist:
                    pass
            
            # 메시지 생성
            print(f"[ChatConsumer] Message.objects.create 호출 시도...")
            print(f"  - content: {content}")
            print(f"  - encrypted_content: {encrypted_content}")
            print(f"  - asset: {asset}")
            
            message = Message.objects.create(
                room=room,
                sender=self.user,
                message_type=msg_type,
                content=content if content else None,
                encrypted_content=encrypted_content,
                encrypted_session_key=encrypted_session_key,
                self_encrypted_session_key=self_encrypted_session_key,
                reply_to=reply_to,
                asset=asset
            )
            
            # 채팅방 업데이트 시간 갱신
            room.save(update_fields=['updated_at'])
            
            print(f"[ChatConsumer] ✅ 메시지 생성 성공!")
            print(f"  - Message ID: {message.id}")
            print(f"  - Type: {message.message_type}")
            print(f"  - Asset: {message.asset}")
            if message.asset:
                print(f"  - Asset ID: {message.asset.id}")
                print(f"  - Asset URL: {message.asset.url}")
            
            return message
        except Exception as e:
            print(f"[ChatConsumer] Error creating message: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @database_sync_to_async
    def serialize_message(self, message):
        """메시지 직렬화"""
        serializer = MessageSerializer(message)
        return serializer.data
    
    @database_sync_to_async
    def mark_messages_as_read(self, message_ids):
        """메시지 읽음 처리"""
        try:
            room = ChatRoom.objects.get(id=self.room_id)
            
            # 해당 채팅방의 메시지만 읽음 처리 (자신이 보낸 메시지 제외)
            Message.objects.filter(
                id__in=message_ids,
                room=room
            ).exclude(sender=self.user).update(is_read=True)
            
            # 마지막 읽은 시간 업데이트
            ChatRoomMember.objects.filter(
                room=room,
                user=self.user
            ).update(last_read_at=timezone.now())
            
            # 갱신된 멤버 정보 가져오기
            member = ChatRoomMember.objects.get(room=room, user=self.user)
            
        except Exception as e:
            print(f"Error marking messages as read: {e}")


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    알림 WebSocket Consumer
    
    URL: ws://<host>/ws/notifications/?token=<jwt_token>
    
    전체 알림 (친구 요청, 그룹챗 초대 등)을 실시간으로 수신합니다.
    """
    
    async def connect(self):
        """WebSocket 연결 시"""
        # JWT 토큰 인증
        query_string = self.scope.get('query_string', b'').decode()
        query_params = dict(param.split('=') for param in query_string.split('&') if '=' in param)
        token = query_params.get('token')
        
        if not token:
            await self.close(code=4001)
            return
        
        # 토큰 검증 및 사용자 인증
        try:
            access_token = AccessToken(token)
            user_id = access_token.get('user_id')
            self.user = await self.get_user(user_id)
            
            if not self.user:
                await self.close(code=4002)
                return
                
        except (InvalidToken, TokenError):
            await self.close(code=4003)
            return
        
        # 사용자별 알림 그룹에 참여
        self.notification_group_name = f'notifications_{self.user.id}'
        
        await self.channel_layer.group_add(
            self.notification_group_name,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        """WebSocket 연결 해제 시"""
        if hasattr(self, 'notification_group_name'):
            await self.channel_layer.group_discard(
                self.notification_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """클라이언트로부터 메시지 수신 (현재는 사용하지 않음)"""
        pass
    
    async def notification(self, event):
        """알림 전송"""
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'notification': event['notification']
        }))
    
    @database_sync_to_async
    def get_user(self, user_id):
        """사용자 조회"""
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
