#!/usr/bin/env python3
"""
Telegram Session 文件生成器
支持在Docker等非交互式环境中运行

使用方法 (环境变量):
    export TG_API_ID=123456
    export TG_API_HASH=your_api_hash
    export TG_PHONE=+8613800138000
    python generate_session.py

使用方法 (命令行参数):
    python generate_session.py --api-id 123456 --api-hash your_hash --phone +8613800138000

验证码会在运行后提示输入，或通过 TG_CODE 环境变量传入
两步验证密码通过 TG_PASSWORD 环境变量传入
"""

import os
import sys
import argparse
import asyncio

try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
except ImportError:
    print("请先安装 telethon 库:")
    print("pip install telethon")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description='Telegram Session 文件生成器')
    parser.add_argument('--api-id', type=int, help='Telegram API ID')
    parser.add_argument('--api-hash', type=str, help='Telegram API Hash')
    parser.add_argument('--phone', type=str, help='手机号 (带国际区号, 如 +8613800138000)')
    parser.add_argument('--code', type=str, help='验证码')
    parser.add_argument('--password', type=str, help='两步验证密码')
    parser.add_argument('--session', type=str, default='telegram_session', help='Session文件名')
    return parser.parse_args()


def get_value(arg_value, env_name, prompt=None, required=True):
    """优先级: 命令行参数 > 环境变量 > 用户输入"""
    value = arg_value or os.environ.get(env_name)
    
    if value:
        return value
    
    if prompt and sys.stdin.isatty():
        try:
            value = input(f"{prompt}: ").strip()
            if value:
                return value
        except EOFError:
            pass
    
    if required:
        print(f"错误: 请通过参数 或 环境变量 {env_name} 提供值")
        return None
    
    return None


async def main():
    args = parse_args()
    
    print("=" * 50)
    print("  Telegram Session 文件生成器 (Docker版)")
    print("=" * 50)
    print()
    
    # 获取API凭据
    api_id = get_value(args.api_id, 'TG_API_ID', '请输入 API ID')
    if not api_id:
        return
    try:
        api_id = int(api_id)
    except ValueError:
        print("错误: API ID 必须是数字")
        return
    
    api_hash = get_value(args.api_hash, 'TG_API_HASH', '请输入 API Hash')
    if not api_hash:
        return
    
    phone = get_value(args.phone, 'TG_PHONE', '请输入手机号')
    if not phone:
        return
    
    session_name = args.session or os.environ.get('TG_SESSION', 'telegram_session')
    
    print(f"API ID: {api_id}")
    print(f"手机号: {phone}")
    print(f"Session: {session_name}.session")
    print()
    
    # 创建客户端
    client = TelegramClient(session_name, api_id, api_hash)
    
    await client.connect()
    
    if await client.is_user_authorized():
        me = await client.get_me()
        print("已经登录!")
        print(f"用户: {me.first_name} (@{me.username})")
    else:
        # 发送验证码
        print("正在发送验证码...")
        try:
            await client.send_code_request(phone)
            print("验证码已发送!")
        except Exception as e:
            print(f"发送验证码失败: {e}")
            await client.disconnect()
            return
        
        # 获取验证码 - 需要用户输入或环境变量
        code = get_value(args.code, 'TG_CODE', '请输入验证码')
        if not code:
            print()
            print("提示: 验证码已发送到你的Telegram")
            print("请设置环境变量 TG_CODE 后重新运行:")
            print(f"  export TG_CODE=12345")
            print(f"  python generate_session.py --api-id {api_id} --api-hash {api_hash} --phone {phone}")
            await client.disconnect()
            return
        
        try:
            await client.sign_in(phone, code)
        except PhoneCodeInvalidError:
            print("错误: 验证码无效!")
            await client.disconnect()
            return
        except SessionPasswordNeededError:
            # 需要两步验证
            print("需要两步验证密码...")
            password = get_value(args.password, 'TG_PASSWORD', '请输入两步验证密码')
            if not password:
                print("错误: 需要两步验证密码")
                print("请设置环境变量 TG_PASSWORD 后重新运行")
                await client.disconnect()
                return
            
            try:
                await client.sign_in(password=password)
            except Exception as e:
                print(f"两步验证失败: {e}")
                await client.disconnect()
                return
    
    # 成功
    me = await client.get_me()
    print()
    print("=" * 50)
    print("  登录成功!")
    print("=" * 50)
    print(f"  用户名: {me.username or '未设置'}")
    print(f"  名称: {me.first_name} {me.last_name or ''}")
    print(f"  用户ID: {me.id}")
    print("=" * 50)
    print()
    
    session_file = f"{session_name}.session"
    abs_path = os.path.abspath(session_file)
    print(f"Session 文件已保存: {abs_path}")
    print()
    print("使用以下命令复制文件到本地:")
    print(f"  docker cp <container_id>:{abs_path} ./")
    print()
    
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
