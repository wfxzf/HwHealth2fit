import os
import re

# 配置：要处理的根目录
ROOT_DIR = input("请输入要处理的文件夹路径（直接回车则处理当前目录）: ").strip()
if not ROOT_DIR:
    ROOT_DIR = "."

# 常见文本文件扩展名（可根据需要增删）
TEXT_EXTENSIONS = {'.txt', '.json', '.log', '.csv', '.js', '.py', '.yaml', '.yml', '.xml', '.html', '.htm', '.md'}

# 正则表达式：匹配 "partTimeMap":{...}
# 支持任意数量的浮点数键值对，允许空格、换行、逗号等
pattern = re.compile(
    r'"partTimeMap"\s*:\s*{[^}]*},',
    re.DOTALL  # 使 . 匹配换行符（虽然这里用 [^}]* 更安全）
)

def is_text_file(filepath):
    _, ext = os.path.splitext(filepath)
    return ext.lower() in TEXT_EXTENSIONS

def process_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except (UnicodeDecodeError, PermissionError):
        # 跳过非文本文件或无法读取的文件
        return

    # 查找并删除所有匹配项
    new_content, count = pattern.subn('', content)

    if count > 0:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"✅ 已修改 {filepath}（删除 {count} 处）")
        except PermissionError:
            print(f"❌ 无法写入 {filepath}（权限不足）")

def main():
    for root, _, files in os.walk(ROOT_DIR):
        for file in files:
            filepath = os.path.join(root, file)
            if is_text_file(filepath):
                process_file(filepath)

if __name__ == "__main__":
    main()
    print("🔚 处理完成！")