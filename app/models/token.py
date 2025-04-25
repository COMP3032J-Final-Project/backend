# 用于实现 Token 相关模型
import uuid
from datetime import datetime
from typing import Optional

from app.core.config import settings
from app.models.base import Base, BaseDB
from pydantic import ConfigDict, Field


class TokenBlacklist(BaseDB, table=True):
    """
    Token黑名单模型，用于创建Token黑名单表，防止已经撤销或注销的 token 被再次使用
    """

    __tablename__ = "token_blacklist"

    jti: str = Field(..., description="JWT ID", example="unique-jwt-id-123")
    exp: datetime = Field(..., description="过期时间", example="2024-12-31T23:59:59")
    typ: str = Field(..., description="令牌类型", example="access")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "jti": "unique-jwt-id-123",
                "exp": "2024-12-31T23:59:59",
                "type": "access",
            }
        }
    )

    def __repr__(self):
        return f"<TokenBlacklist jti={self.jti} exp={self.exp} typ={self.typ}>"


class Token(Base):
    """
    Token响应模型
    """

    access_token: str = Field(..., description="访问令牌", example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xxx")
    refresh_token: str = Field(..., description="刷新令牌", example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.yyy")
    token_type: str = Field(default="bearer", description="令牌类型", example="bearer")
    expires_in: int = Field(..., description="告知访问令牌的过期时间(秒)", example=settings.EXPIRATION_TIME)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xxx",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.yyy",
                "token_type": "bearer",
                "expires_in": settings.EXPIRATION_TIME,
            }
        }
    )


class TokenPayload(Base):
    """
    Token载荷模型(用于解析JWT)
    """

    sub: str | uuid.UUID = Field(..., description="令牌主题(通常是用户ID)", example="123")
    exp: datetime = Field(..., description="过期时间", example="2024-12-31T23:59:59")
    iat: Optional[datetime] = Field(default=None, description="签发时间", example="2024-01-01T00:00:00")
    jti: Optional[str] = Field(default=None, description="JWT ID, 用于标识JWT的唯一ID", example="unique-jwt-id-123")
    typ: str = Field(default="access", description="令牌类型(access或refresh)", example="access")


class RefreshToken(Base):
    """
    刷新令牌请求
    """

    refresh_token: str = Field(
        ..., description="刷新令牌", min_length=1, example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.yyy"
    )

    model_config = ConfigDict(
        json_schema_extra={"example": {"refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.yyy"}}
    )


class TokenMetadata(Base):
    """
    (暂未使用)Token元数据模型,用于存储额外的token信息
    """

    user_id: str | uuid.UUID = Field(..., description="用户ID", example="515d3617-af31-4d78-97c4-58375a6220ab")
    device_id: Optional[str] = Field(default=None, description="设备ID", example="device-123")
    ip_address: Optional[str] = Field(default=None, description="IP地址", example="192.168.1.1")
    user_agent: Optional[str] = Field(default=None, description="User Agent", example="Mozilla/5.0 ...")
