#!/usr/bin/env python3
"""
Telegram Session 文件生成器
用于在交互式终端中登录Telegram并生成session文件

使用方法:
1. 安装依赖: pip install telethon
2. 运行脚本: python generate_session.py
3. 按提示输入API ID、API Hash、手机号和验证码
4. 生成的session文件可以复制到其他程序中使用
"""

import os
import sys

try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
except ImportError:
    print("请先安装 telethon 库:")
    print("pip install telethon")
    sys.exit(1)


def get_input(prompt: str, default: str = None) -> str:
    """获取用户输入"""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    
    value = input(prompt).strip()
    return value if value else default


async def main():
    print("=" * 50)
    print("  Telegram Session 文件生成器")
    print("=" * 50)
    print()
    print("请访问 https://my.telegram.org/apps 获取 API ID 和 API Hash")
    print()
    
    # 获取API凭据
    api_id = get_input("请输入 API ID")
    if not api_id:
        print("错误: API ID 不能为空")
        return
    
    try:
        api_id = int(api_id)
    except ValueError:
        print("错误: API ID 必须是数字")
        return
    
    api_hash = get_input("请输入 API Hash")
    if not api_hash:
        print("错误: API Hash 不能为空")
        return
    
    # Session文件名
    session_name = get_input("请输入 Session 文件名", "telegram_session")
    
    print()
    print(f"Session 文件将保存为: {session_name}.session")
    print()
    
    # 创建客户端
    client = TelegramClient(session_name, api_id, api_hash)
    
    await client.connect()
    
    if not await client.is_user_authorized():
        # 获取手机号
        phone = get_input("请输入手机号 (带国际区号, 如 +86xxxxxxxxxx)")
        if not phone:
            print("错误: 手机号不能为空")
            return
        
        # 发送验证码
        print()
        print("正在发送验证码...")
        await client.send_code_request(phone)
        
        # 获取验证码
        code = get_input("请输入收到的验证码")
        if not code:
            print("错误: 验证码不能为空")
            return
        
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            # 需要两步验证密码
            print()
            print("检测到启用了两步验证")
            password = get_input("请输入两步验证密码")
            await client.sign_in(password=password)
    
    # 获取用户信息
    me = await client.get_me()
    print()
    print("=" * 50)
    print("  登录成功!")
    print("=" * 50)
    print(f"  用户名: {me.username or '未设置'}")
    print(f"  名称: {me.first_name} {me.last_name or ''}")
    print(f"  用户ID: {me.id}")
    print(f"  手机号: {me.phone}")
    print("=" * 50)
    print()
    
    session_file = f"{session_name}.session"
    abs_path = os.path.abspath(session_file)
    print(f"Session 文件已保存: {abs_path}")
    print()
    print("你可以将此 .session 文件复制到需要使用的程序目录中")
    print()
    
    await client.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
