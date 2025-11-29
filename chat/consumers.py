import json
from typing import Optional, Tuple

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

from config.constants import (
    WEBSOCKET_ERROR_INVALID_TOKEN,
    WEBSOCKET_ERROR_NO_TOKEN,
    WEBSOCKET_ERROR_NOT_MEMBER,
    WEBSOCKET_ERROR_USER_NOT_FOUND,
)

from .models import ChatRoom, ChatRoomMember, Message
from .serializers import MessageSerializer

User = get_user_model()


class BaseAuthConsumer(AsyncWebsocketConsumer):
    user = None
    
    def parse_token_from_query_string(self) -> Optional[str]:
        query_string = self.scope.get('query_string', b'').decode()
        query_params = dict(
            param.split('=') for param in query_string.split('&') if '=' in param
        )
        return query_params.get('token')
    
    async def authenticate_user(self) -> Tuple[bool, Optional[int]]:
        token = self.parse_token_from_query_string()
        
        if not token:
            return False, WEBSOCKET_ERROR_NO_TOKEN
        
        try:
            access_token = AccessToken(token)
            user_id = access_token.get('user_id')
            self.user = await self.get_user(user_id)
            
            if not self.user:
                return False, WEBSOCKET_ERROR_USER_NOT_FOUND
            
            return True, None
            
        except (InvalidToken, TokenError):
            return False, WEBSOCKET_ERROR_INVALID_TOKEN
    
    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None


class ChatConsumer(BaseAuthConsumer):
    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'
        
        is_authenticated, error_code = await self.authenticate_user()
        if not is_authenticated:
            await self.close(code=error_code)
            return
        
        is_member = await self.check_room_membership()
        if not is_member:
            await self.close(code=WEBSOCKET_ERROR_NOT_MEMBER)
            return
        
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_status',
                'user_id': str(self.user.id),
                'status': 'online'
            }
        )
    
    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name') and hasattr(self, 'user'):
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_status',
                    'user_id': str(self.user.id),
                    'status': 'offline'
                }
            )
            
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
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
        msg_type = data.get('message_type', 'text')
        content = data.get('content', '')
        encrypted_content = data.get('encrypted_content')
        encrypted_session_key = data.get('encrypted_session_key')
        self_encrypted_session_key = data.get('self_encrypted_session_key')
        reply_to_id = data.get('reply_to')
        asset_id = data.get('asset_id')
        
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
            try:
                message_data = await self.serialize_message(message)
            except Exception as e:
                import traceback
                traceback.print_exc()
                await self.send_error(f"Message serialization failed: {str(e)}")
                return
            
            try:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': message_data
                    }
                )
                await self.send_global_notification(message)
                
            except Exception as e:
                import traceback
                traceback.print_exc()
                await self.send_error(f"Failed to send message to group: {str(e)}")
        else:
            await self.send_error("Failed to create message")
    
    async def handle_typing(self, data):
        is_typing = data.get('is_typing', False)
        
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
        message_ids = data.get('message_ids', [])
        
        if message_ids:
            await self.mark_messages_as_read(message_ids)
            
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'read_receipt',
                    'user_id': str(self.user.id),
                    'message_ids': message_ids
                }
            )

    async def send_global_notification(self, message):
        try:
            import uuid

            from django.utils import timezone
            
            members = await self.get_room_members(self.room_id, exclude_user_id=self.user.id)
            
            data_payload = {
                'room_id': self.room_id,
                'room_name': self.room_group_name,
                'message_id': str(message.id),
                'message_type': message.message_type,
                'sender': {
                    'id': str(self.user.id),
                    'name': self.user.name,
                    'profile_image': self.user.profile_image if self.user.profile_image else None
                }
            }
            
            if message.message_type == 'text':
                if message.content:
                    data_payload['content'] = message.content
                elif message.encrypted_content:
                    data_payload['content'] = '새로운 메시지'
            elif message.message_type == 'image':
                data_payload['content'] = '📷 사진'
            elif message.message_type == 'file':
                data_payload['content'] = '📎 파일'
            
            notification_payload = {
                'id': str(uuid.uuid4()),
                'type': 'new_message',
                'created_at': timezone.now().isoformat(),
                'data': data_payload
            }
                
            for member in members:
                await self.channel_layer.group_send(
                    f'notifications_{member.user.id}',
                    {
                        'type': 'notification',
                        'notification': notification_payload
                    }
                )
        except Exception:
            pass

    async def chat_message(self, event):
        try:
            message_data = event['message']
            
            response_data = {
                'type': 'chat_message',
                'message': message_data
            }
            
            json_string = json.dumps(response_data, cls=DjangoJSONEncoder, ensure_ascii=False)
            await self.send(text_data=json_string)
        except Exception:
            pass
    
    async def typing_indicator(self, event):
        if event.get('sender_channel') != self.channel_name:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'user': event['user'],
                'is_typing': event['is_typing']
            }))
    
    async def read_receipt(self, event):
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'user_id': event['user_id'],
            'message_ids': event['message_ids']
        }))
    
    async def message_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_update',
            'message': event['message']
        }, cls=DjangoJSONEncoder))
    
    async def message_delete(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_delete',
            'message_id': event['message_id']
        }))
    
    async def user_status(self, event):
        if event['user_id'] != str(self.user.id):
            await self.send(text_data=json.dumps({
                'type': 'user_status',
                'user_id': event['user_id'],
                'status': event['status']
            }))
    
    async def send_error(self, message):
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message
        }))
    
    @database_sync_to_async
    def check_room_membership(self):
        try:
            room = ChatRoom.objects.get(id=self.room_id)
            return ChatRoomMember.objects.filter(room=room, user=self.user).exists()
        except ChatRoom.DoesNotExist:
            return False
    
    @database_sync_to_async
    def get_room_members(self, room_id, exclude_user_id=None):
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
        try:
            room = ChatRoom.objects.get(id=self.room_id)
            
            if room.room_type == 'direct' and not encrypted_content and msg_type == 'text':
                return None
            if room.room_type == 'group' and encrypted_content:
                return None
            if room.room_type == 'group' and encrypted_session_key:
                return None
            if room.room_type == 'group' and self_encrypted_session_key:
                return None
            
            reply_to = None
            if reply_to_id:
                try:
                    reply_to = Message.objects.get(id=reply_to_id, room=room)
                except Message.DoesNotExist:
                    pass
            
            asset = None
            if asset_id:
                from common.models import Asset
                try:
                    asset = Asset.objects.get(id=asset_id)
                except Asset.DoesNotExist:
                    pass
            
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
            
            room.save(update_fields=['updated_at'])
            
            return message
        except Exception:
            return None
    
    @database_sync_to_async
    def serialize_message(self, message):
        serializer = MessageSerializer(message)
        return serializer.data
    
    @database_sync_to_async
    def mark_messages_as_read(self, message_ids):
        try:
            room = ChatRoom.objects.get(id=self.room_id)
            
            Message.objects.filter(
                id__in=message_ids,
                room=room
            ).exclude(sender=self.user).update(is_read=True)
            
            ChatRoomMember.objects.filter(
                room=room,
                user=self.user
            ).update(last_read_at=timezone.now())
            
        except Exception:
            pass


class NotificationConsumer(BaseAuthConsumer):
    async def connect(self):
        is_authenticated, error_code = await self.authenticate_user()
        if not is_authenticated:
            await self.close(code=error_code)
            return
        
        self.notification_group_name = f'notifications_{self.user.id}'
        
        await self.channel_layer.group_add(
            self.notification_group_name,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        if hasattr(self, 'notification_group_name'):
            await self.channel_layer.group_discard(
                self.notification_group_name,
                self.channel_name
            )
    
    async def notification(self, event):
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'notification': event['notification']
        }))
