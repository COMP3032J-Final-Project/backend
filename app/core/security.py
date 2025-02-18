# 用于密码加密和验证
import bcrypt

def get_password_hash(password: str) -> str:
    """
    将密码进行哈希加密
    """
    salt = bcrypt.gensalt() # 生成盐值（salt），用于加密
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_password.decode('utf-8')  # 返回为字符串类型


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码是否正确
    """
    # 使用bcrypt验证输入的密码与存储的哈希值是否匹配
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
