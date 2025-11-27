"""
加密工具模块
使用 Fernet 对称加密安全存储敏感配置
"""
import os
import base64
import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# 加密密钥文件路径
KEY_FILE_PATH = Path("data/.encryption_key")
# 盐值文件路径（用于密钥派生）
SALT_FILE_PATH = Path("data/.encryption_salt")


class EncryptionManager:
    """加密管理器 - 用于加密/解密敏感配置"""
    
    _instance: Optional["EncryptionManager"] = None
    _fernet: Optional[Fernet] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """初始化加密器"""
        try:
            key = self._get_or_create_key()
            self._fernet = Fernet(key)
            logger.info("加密管理器初始化成功")
        except Exception as e:
            logger.error(f"加密管理器初始化失败: {e}")
            self._fernet = None
    
    def _get_or_create_key(self) -> bytes:
        """获取或创建加密密钥"""
        # 确保data目录存在
        KEY_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # 检查是否有环境变量指定的密钥
        env_key = os.getenv("ENCRYPTION_KEY")
        if env_key:
            # 使用环境变量中的密钥派生实际密钥
            return self._derive_key_from_password(env_key)
        
        # 如果密钥文件存在，读取它
        if KEY_FILE_PATH.exists():
            with open(KEY_FILE_PATH, "rb") as f:
                key = f.read()
                if len(key) == 44:  # Fernet key 是 44 字节 base64
                    return key
        
        # 生成新密钥
        key = Fernet.generate_key()
        
        # 保存密钥（设置只读权限）
        with open(KEY_FILE_PATH, "wb") as f:
            f.write(key)
        
        # 设置文件权限为只有所有者可读写
        try:
            os.chmod(KEY_FILE_PATH, 0o600)
        except Exception:
            pass  # Windows 可能不支持
        
        logger.info("已生成新的加密密钥")
        return key
    
    def _derive_key_from_password(self, password: str) -> bytes:
        """从密码派生加密密钥"""
        # 确保data目录存在
        SALT_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # 获取或创建盐值
        if SALT_FILE_PATH.exists():
            with open(SALT_FILE_PATH, "rb") as f:
                salt = f.read()
        else:
            salt = os.urandom(16)
            with open(SALT_FILE_PATH, "wb") as f:
                f.write(salt)
            try:
                os.chmod(SALT_FILE_PATH, 0o600)
            except Exception:
                pass
        
        # 使用 PBKDF2 派生密钥
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    def encrypt(self, plaintext: str) -> str:
        """
        加密字符串
        
        Args:
            plaintext: 要加密的明文
            
        Returns:
            加密后的 base64 编码字符串，带有 ENC: 前缀
        """
        if not self._fernet:
            logger.warning("加密器未初始化，返回原文")
            return plaintext
        
        if not plaintext:
            return plaintext
        
        try:
            encrypted = self._fernet.encrypt(plaintext.encode())
            # 添加前缀标识这是加密的内容
            return f"ENC:{encrypted.decode()}"
        except Exception as e:
            logger.error(f"加密失败: {e}")
            return plaintext
    
    def decrypt(self, ciphertext: str) -> str:
        """
        解密字符串
        
        Args:
            ciphertext: 要解密的密文（带 ENC: 前缀）
            
        Returns:
            解密后的明文
        """
        if not self._fernet:
            logger.warning("加密器未初始化")
            return ciphertext
        
        if not ciphertext:
            return ciphertext
        
        # 检查是否是加密的内容
        if not ciphertext.startswith("ENC:"):
            # 不是加密的内容，直接返回
            return ciphertext
        
        try:
            # 移除前缀
            encrypted_data = ciphertext[4:]
            decrypted = self._fernet.decrypt(encrypted_data.encode())
            return decrypted.decode()
        except InvalidToken:
            logger.error("解密失败: 无效的令牌（可能密钥已更换）")
            return ""
        except Exception as e:
            logger.error(f"解密失败: {e}")
            return ""
    
    def is_encrypted(self, value: str) -> bool:
        """检查值是否是加密的"""
        return value.startswith("ENC:") if value else False
    
    @property
    def is_available(self) -> bool:
        """检查加密器是否可用"""
        return self._fernet is not None


# 全局加密管理器实例
encryption_manager = EncryptionManager()


# 便捷函数
def encrypt(plaintext: str) -> str:
    """加密字符串"""
    return encryption_manager.encrypt(plaintext)


def decrypt(ciphertext: str) -> str:
    """解密字符串"""
    return encryption_manager.decrypt(ciphertext)


def is_encrypted(value: str) -> bool:
    """检查值是否是加密的"""
    return encryption_manager.is_encrypted(value)
